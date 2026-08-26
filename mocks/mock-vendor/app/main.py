"""Schema-driven vendor cloud double.

Reads the SAME vendor schema `vendor-adapter` consumes and serves responses
shaped to satisfy that schema, so a fresh clone exercises the vendor integration
end to end without a real vendor account. It is not tied to any one vendor: mount
a different schema and it emits that vendor's shape, on that vendor's URL paths,
behind that vendor's auth.

Only the `rest` transport is served (the schema default). The synthetic position
is a slow walk around a fixed point; the value is an init placeholder - a mock
drives the real ingest pipeline (vendor-adapter pull), it is not geographically
meaningful.
"""

import base64
import json
import os
import random
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request

from .mockgen import build_diagnostics, build_discover, build_telemetry, match_template

SCHEMA_FILE = os.environ.get("SCHEMA_FILE", "/app/config/schema.json")
with open(SCHEMA_FILE) as f:
    SCHEMA = json.load(f)

TRANSPORT = SCHEMA.get("transport", "rest")

# Init placeholder only: the point the synthetic device starts from before the
# walk moves it. Not meaningful - a real source emits its own coordinates.
_CENTER = (45.064312, 7.659154)
_HEIGHT_M = 1.2
_state: dict[str, dict] = {}

app = FastAPI(
    title="mock-vendor",
    description="Schema-driven fake of a vendor positioning cloud.",
    version="0.3.0",
)


def _env(ref) -> str | None:
    if isinstance(ref, dict) and "env" in ref:
        return os.environ.get(ref["env"])
    return None


def _check_auth(request: Request) -> None:
    auth = SCHEMA.get("auth") or {"scheme": "none"}
    scheme = auth.get("scheme", "none")
    if scheme == "none":
        return
    header = request.headers.get("authorization")
    if scheme == "basic":
        if not header or not header.startswith("Basic "):
            raise HTTPException(401, detail="Missing Basic auth")
        try:
            user, pwd = base64.b64decode(header[6:]).decode("utf-8", "replace").split(":", 1)
        except ValueError:
            raise HTTPException(401, detail="Malformed Basic auth")
        if user != _env(auth.get("username")) or pwd != _env(auth.get("password")):
            raise HTTPException(401, detail="Invalid credentials")
    elif scheme == "bearer":
        if header != f"Bearer {_env(auth.get('token'))}":
            raise HTTPException(401, detail="Invalid bearer token")
    elif scheme == "header":
        if request.headers.get(auth["header"].lower()) != _env(auth.get("value")):
            raise HTTPException(401, detail="Invalid credentials")


def _check_path_vars(path_vars: dict, extracted: dict) -> None:
    """The schema's path vars (org_id, project_id) carry the operator's real
    account values via env; a request must address that account."""
    for var, ref in (path_vars or {}).items():
        if extracted.get(var) != _env(ref):
            raise HTTPException(404, detail=f"Unknown {var}")


def _walk(device_id: str) -> tuple[float, float]:
    s = _state.setdefault(device_id, {"lat": _CENTER[0], "lon": _CENTER[1]})
    s["lat"] += random.uniform(-0.000005, 0.000005)
    s["lon"] += random.uniform(-0.000005, 0.000005)
    return s["lat"], s["lon"]


@app.get("/health")
async def health():
    return {"status": "ok", "vendor": SCHEMA.get("vendor"), "transport": TRANSPORT}


@app.get("/{full_path:path}")
async def serve(full_path: str, request: Request):
    if TRANSPORT != "rest":
        raise HTTPException(501, detail=f"mock-vendor serves the rest transport, not {TRANSPORT}")
    req_path = "/" + full_path
    query = dict(request.query_params)

    telem = match_template(SCHEMA["path"], req_path, query)
    if telem is not None:
        _check_auth(request)
        _check_path_vars(SCHEMA.get("path_vars", {}), telem)
        device_id = telem.get("device_id", "unknown")
        lat, lon = _walk(device_id)
        values = {
            "frame": "wgs84",
            "latitude": lat,
            "longitude": lon,
            "accuracy_m": round(0.6 + random.random() * 0.35, 2),
            "confidence": 0.5,
            "y": _HEIGHT_M,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return build_telemetry(SCHEMA["mapping"], values)

    discover = SCHEMA.get("discover")
    if discover:
        disc = match_template(discover["path"], req_path, query)
        if disc is not None:
            _check_auth(request)
            _check_path_vars(discover.get("path_vars", {}), disc)
            lat, lon = _walk("_discover")
            return build_discover(discover, lat, lon, _HEIGHT_M)

    for entry in SCHEMA.get("diagnostics", {}).get("on_demand", []):
        diag = match_template(entry["path"], req_path, query)
        if diag is not None:
            _check_auth(request)
            _check_path_vars(entry.get("path_vars", {}), diag)
            return build_diagnostics(entry.get("mapping", {}))

    raise HTTPException(404, detail="No schema route matches this path")
