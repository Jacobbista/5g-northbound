#!/usr/bin/env python3
"""Positioning fabric check.

Validates that the declarative pieces of the positioning fabric agree, the
same self-validating spirit as the env contracts:

  1. each adapter's compose ADAPTER_CAPABILITIES matches its
     adapter.contract.yaml `capabilities` (closes the "value in compose,
     source in contract" loop - no silent drift);
  2. every asset's `source` in dev/assets.json is advertised by some adapter;
  3. every asset's `kind` is advertised by some adapter;
  4. dev/assets.json conforms to schema/asset.schema.json (best-effort: only
     when jsonschema is importable).

Static: reads files, runs no containers. Exit 0 = consistent, 1 = drift.

Usage: deploy/tools/positioning_check.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "deploy" / "compose" / "docker-compose.yml"
ASSETS = REPO / "dev" / "assets.json"
ASSET_SCHEMA = REPO / "schema" / "asset.schema.json"

OK, BAD = "\033[32m✓\033[0m", "\033[31m✗\033[0m"


def _compose_services() -> dict:
    return (yaml.safe_load(COMPOSE.read_text()) or {}).get("services", {}) or {}


def _env_map(service: dict) -> dict:
    """Compose environment may be a dict or a list of KEY=VALUE strings."""
    env = service.get("environment") or {}
    if isinstance(env, list):
        out = {}
        for item in env:
            k, _, v = str(item).partition("=")
            out[k] = v
        return out
    return env


def main() -> int:
    errors: list[str] = []
    services = _compose_services()

    # adapter dir -> compose service name (basename matches the service key).
    contracts = sorted(REPO.glob("services/*/adapter.contract.yaml")) + \
        sorted(REPO.glob("mocks/*/adapter.contract.yaml"))
    if not contracts:
        print(f"{BAD} no adapter.contract.yaml found")
        return 1

    advertised_sources: set[str] = set()
    advertised_kinds: set[str] = set()

    print("· adapter capabilities (compose vs contract)")
    for path in contracts:
        svc_name = path.parent.name
        contract = yaml.safe_load(path.read_text()) or {}
        caps = contract.get("capabilities") or {}
        advertised_sources.add(caps.get("source"))
        advertised_kinds.update(caps.get("kinds") or [])

        svc = services.get(svc_name)
        if svc is None:
            errors.append(f"{svc_name}: contract present but no compose service")
            print(f"  {BAD} {svc_name}: no compose service")
            continue
        raw = _env_map(svc).get("ADAPTER_CAPABILITIES")
        if not raw:
            errors.append(f"{svc_name}: compose has no ADAPTER_CAPABILITIES")
            print(f"  {BAD} {svc_name}: ADAPTER_CAPABILITIES unset in compose")
            continue
        try:
            compose_caps = json.loads(raw)
        except ValueError as exc:
            errors.append(f"{svc_name}: ADAPTER_CAPABILITIES not valid JSON ({exc})")
            print(f"  {BAD} {svc_name}: ADAPTER_CAPABILITIES invalid JSON")
            continue
        if compose_caps != caps:
            errors.append(f"{svc_name}: compose ADAPTER_CAPABILITIES != contract capabilities")
            print(f"  {BAD} {svc_name}: drift\n      contract: {caps}\n      compose:  {compose_caps}")
        else:
            print(f"  {OK} {svc_name}: {caps.get('source')} ({caps.get('accuracy_class')})")

    # Asset coverage: every source + kind must be served by some adapter.
    print("· asset coverage (assets.json vs advertised capabilities)")
    amap = json.loads(ASSETS.read_text())
    for a in amap.get("assets", []):
        if a["source"] not in advertised_sources:
            errors.append(f"asset {a['asset_id']}: source '{a['source']}' not advertised by any adapter")
            print(f"  {BAD} {a['asset_id']}: source '{a['source']}' unserved")
        elif a["kind"] not in advertised_kinds:
            errors.append(f"asset {a['asset_id']}: kind '{a['kind']}' not advertised by any adapter")
            print(f"  {BAD} {a['asset_id']}: kind '{a['kind']}' unadvertised")
        else:
            print(f"  {OK} {a['asset_id']}: {a['kind']} via {a['source']}")

    # Schema conformance (best-effort).
    print("· schema (assets.json vs schema/asset.schema.json)")
    try:
        import jsonschema  # noqa
        jsonschema.validate(amap, json.loads(ASSET_SCHEMA.read_text()))
        print(f"  {OK} assets.json conforms to asset.schema.json")
    except ImportError:
        print("  · jsonschema not installed; schema check skipped")
    except Exception as exc:  # jsonschema.ValidationError + friends
        errors.append(f"assets.json schema violation: {exc.args[0] if exc.args else exc}")
        print(f"  {BAD} assets.json does not conform: {str(exc).splitlines()[0]}")

    print()
    if errors:
        print(f"{BAD} positioning-check: {len(errors)} problem(s)")
        for e in errors:
            print(f"    - {e}")
        return 1
    print(f"{OK} positioning-check: fabric consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
