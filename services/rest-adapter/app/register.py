"""Self-registration client: announce this adapter to the engine's registry.

The engine is the adapter-registry authority. Each adapter POSTs itself to
`POSITIONING_ENGINE_URL/adapters` at boot and re-POSTs on a heartbeat; the
engine evicts entries that stop beating. On shutdown the adapter best-effort
DELETEs itself. Disabled (no-op) when the required env is not set, so the
adapter still runs standalone.

Bundled per adapter (no cross-service import, per AGENTS.md); identical shape
in every adapter.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import httpx

try:
    import yaml
except Exception:  # pragma: no cover - yaml is a dependency, guard anyway
    yaml = None

log = logging.getLogger(__name__)

# Baked declarative source of truth. First existing path wins (image vs repo).
_CONTRACT_PATHS = (
    "/app/adapter.contract.yaml",
    str(Path(__file__).resolve().parents[1] / "adapter.contract.yaml"),
)


def _contract_caps() -> dict:
    """Capabilities the image declares about itself, from the baked
    adapter.contract.yaml. Lets the adapter self-advertise without the
    deployment restating the JSON in an env var."""
    if yaml is None:
        return {}
    for path in _CONTRACT_PATHS:
        try:
            data = yaml.safe_load(Path(path).read_text()) or {}
        except OSError:
            continue
        except Exception:
            return {}
        caps = data.get("capabilities")
        return dict(caps) if isinstance(caps, dict) else {}
    return {}


def _caps() -> dict:
    """Advertised capabilities: the baked adapter.contract.yaml is the base
    (so the image self-declares calibration / discover / etc. with no env
    plumbing), and ADAPTER_CAPABILITIES (JSON) overrides/extends it for a
    deployment that tweaks without a rebuild. `make positioning-check`
    validates the two agree."""
    caps = _contract_caps()
    try:
        override = json.loads(os.environ.get("ADAPTER_CAPABILITIES") or "{}")
    except ValueError:
        override = {}
    if isinstance(override, dict):
        caps.update(override)
    return caps


def _cfg() -> dict:
    return {
        "engine_url": os.environ.get("POSITIONING_ENGINE_URL", "").rstrip("/"),
        "name": os.environ.get("ADAPTER_NAME", ""),
        "base_url": os.environ.get("ADAPTER_BASE_URL", ""),
        "kind": os.environ.get("ADAPTER_KIND", "adapter"),
        "heartbeat_s": float(os.environ.get("ADAPTER_HEARTBEAT_S", "15")),
        "capabilities": _caps(),
    }


def _enabled(c: dict) -> bool:
    return bool(c["engine_url"] and c["name"] and c["base_url"])


async def heartbeat_loop() -> None:
    """Register + heartbeat forever. The first POST is the registration; each
    subsequent POST is the heartbeat (the engine upserts idempotently)."""
    c = _cfg()
    if not _enabled(c):
        log.info(
            "self-registration disabled "
            "(POSITIONING_ENGINE_URL / ADAPTER_NAME / ADAPTER_BASE_URL not all set)"
        )
        return
    payload = {"name": c["name"], "base_url": c["base_url"], "kind": c["kind"], "capabilities": c["capabilities"]}
    url = f"{c['engine_url']}/adapters"
    first = True
    while True:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(url, json=payload)
            if first:
                log.info("registered with engine as '%s' -> %s", c["name"], c["base_url"])
                first = False
        except Exception as exc:
            log.warning("self-registration heartbeat failed (%s)", exc)
        await asyncio.sleep(c["heartbeat_s"])


async def deregister() -> None:
    c = _cfg()
    if not (c["engine_url"] and c["name"]):
        return
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.delete(f"{c['engine_url']}/adapters/{c['name']}")
        log.info("deregistered '%s' from engine", c["name"])
    except Exception:
        pass  # best-effort; the engine TTL-evicts us anyway
