"""Placement editor service: operator-facing.

Minimal scaffold: serves a static index page (placeholder UI) and exposes a
small REST surface for reading/writing the layout JSON. The eventual UI is a
drag-drop floor-plan editor; this image is the artefact that the testbed
dashboard will mount alongside its own console.

Distinct realm role (`placement-admin`) is assumed when auth is wired in;
SKIP_AUTH=true is dev-only.
"""

import logging
import os
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .config import get_settings

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Placement editor",
    description="Operator UI + BFF for editing the floor-plan layout.",
    version="0.0.1",
)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# Baked env contract. First existing path wins: CONTRACT_PATH override, the
# image's /app/env.contract.yaml, then the repo-relative file for local runs.
_CONTRACT_CANDIDATES = [
    os.environ.get("CONTRACT_PATH"),
    "/app/env.contract.yaml",
    str(Path(__file__).resolve().parent.parent / "env.contract.yaml"),
]


def _sanitize_contract(entries: list) -> list:
    """Strip value-bearing fields from sensitive entries: the contract is
    schema only, never a value for a secret field."""
    out = []
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("sensitive"):
            entry = {k: v for k, v in entry.items() if k not in ("default", "example")}
        out.append(entry)
    return out


@app.get("/contract")
async def contract() -> dict:
    """Serve this service's env contract (schema only, never values or
    secrets). No auth, no dependency on business config, so a deploy
    dashboard can read it from a live-but-unconfigured pod."""
    for candidate in _CONTRACT_CANDIDATES:
        if candidate and Path(candidate).is_file():
            raw = yaml.safe_load(Path(candidate).read_text()) or {}
            return {
                "service": raw.get("service"),
                "kind": raw.get("kind"),
                "external_origin": raw.get("external_origin"),
                "description": raw.get("description"),
                "env": {
                    "required": _sanitize_contract(raw.get("required")),
                    "recommended": _sanitize_contract(raw.get("recommended")),
                    "optional": _sanitize_contract(raw.get("optional")),
                },
            }
    raise HTTPException(500, detail="env.contract.yaml not found")


@app.get("/api/layout")
async def get_layout(request: Request) -> Response:
    """Read the canonical blueprint from the engine (the authority). The editor
    is a pure client - no shared PVC. Engine 404 (nothing authored yet) is
    surfaced as 404 so the frontend opens a blank canvas."""
    base = get_settings().positioning_engine_url
    return await _proxy(base, "/blueprint", request, "positioning-engine")


@app.put("/api/layout")
async def put_layout(request: Request) -> Response:
    """Write the blueprint back to the engine. Write authorisation is the
    editor's front-door gate (oauth2-proxy / admin), not the engine: the engine
    is ClusterIP and never externally exposed. See docs/blueprint-vs-bindings.md."""
    base = get_settings().positioning_engine_url
    return await _proxy(base, "/blueprint", request, "positioning-engine")


async def _proxy(target_base: str, suffix: str, request: Request, label: str) -> Response:
    """Tiny generic proxy: forward the inbound method + body to `target_base + suffix`.

    The placement editor hosts thin UI flows that drive adapter-side tools
    (calibration, vendor discovery). Direct browser-to-adapter calls would
    need CORS on every adapter; routing through here keeps every adapter
    internal-only.
    """
    target = f"{target_base.rstrip('/')}{suffix}"
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upstream = await client.request(
                request.method,
                target,
                content=body,
                params=dict(request.query_params),
                headers={
                    k: v for k, v in request.headers.items()
                    if k.lower() in ("content-type", "accept")
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(502, detail=f"{label} unreachable: {exc}") from exc
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


# --- WiFi calibration proxy -------------------------------------------------
@app.api_route(
    "/api/wifi/calibration/{path:path}",
    methods=["GET", "POST", "DELETE", "PUT"],
)
async def proxy_calibration(path: str, request: Request) -> Response:
    base = get_settings().wifi_positioning_url
    return await _proxy(base, f"/calibration/{path}", request, "wifi-positioning")


# --- Vendor discovery proxy -------------------------------------------------
#
# Browser hits /api/vendor/discover. Editor backend forwards to the
# rest-adapter's GET /discover, which uses the currently loaded vendor
# schema (Wittra by default in dev) to walk the vendor's device list.
@app.api_route(
    "/api/vendor/discover",
    methods=["GET"],
)
async def proxy_vendor_discover(request: Request) -> Response:
    base = get_settings().rest_adapter_url
    return await _proxy(base, "/discover", request, "rest-adapter")


# --- Asset Identity Map proxy ----------------------------------------------
#
# GET/PUT /assets on the camara-gateway (the asset authority). The editor only
# proxies; asset onboarding (importing discovered tags) is the KELT dashboard's
# job, per the ownership split. PUT replaces the whole map, so a caller must
# GET, merge additively, then PUT - never blind-write.
@app.api_route(
    "/api/assets",
    methods=["GET", "PUT"],
)
async def proxy_assets(request: Request) -> Response:
    base = get_settings().camara_gateway_url
    return await _proxy(base, "/assets", request, "camara-gateway")


@app.api_route(
    "/api/vendor/schema",
    methods=["GET"],
)
async def proxy_vendor_schema(request: Request) -> Response:
    """Lets the editor read the current vendor schema (mostly to surface
    the vendor name in the sync panel header). Read-only proxy."""
    base = get_settings().rest_adapter_url
    return await _proxy(base, "/schema", request, "rest-adapter")


@app.get("/env-config.js", include_in_schema=False)
async def env_config_js() -> Response:
    """Serve the runtime env-config.js with no-cache so a token rotation
    (e.g. via a k8s Secret update + pod restart that rewrites the file via
    entrypoint.sh) is picked up on the next page load without stale browser
    caching."""
    path = _STATIC_DIR / "env-config.js"
    if not path.exists():
        return Response(content="window.__ENV__ = {};", media_type="application/javascript")
    return Response(
        content=path.read_text(),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# Serve the SPA at /. Mounted last so explicit routes above (/api/*, /health)
# still match first. `html=True` makes StaticFiles serve index.html on /.
if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="ui")
