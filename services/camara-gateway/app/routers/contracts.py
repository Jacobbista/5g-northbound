"""Serves the consumer-facing profile contracts this gateway integrates against.

The gateway is the single backend a MEC app is allowed to call, so it also
self-describes the contracts a consumer wires against: the profiled CAMARA specs,
the asset schema, the device-diagnostics schema + spec, the streaming contract
and the extension OpenAPI. A consumer reads them from the running gateway, pinned
to the deployed image, instead of an external CDN. The GitHub Pages copy stays as
the public/offline mirror (see docs/contracts.md).

No auth and no dependency on business configuration, the same posture as
GET /contract: contract metadata carries no secrets, and an unconfigured pod must
still answer. Files resolve from a baked directory in the image, falling back to
the repo tree for local dev and tests.
"""

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

router = APIRouter(tags=["contracts"])

# Consumer-facing contracts, keyed by basename. `path` is the repo-relative path,
# kept so the Pages and raw@tag URLs in docs/contracts.md stay derivable.
_MANIFEST: list[dict] = [
    {"name": "location-retrieval.profiled.yaml",
     "path": "spec/private-profile/generated/location-retrieval.profiled.yaml",
     "media_type": "application/yaml",
     "description": "CAMARA Location Retrieval, base + overlay applied (the pinnable contract)"},
    {"name": "location-verification.profiled.yaml",
     "path": "spec/private-profile/generated/location-verification.profiled.yaml",
     "media_type": "application/yaml",
     "description": "CAMARA Location Verification, base + overlay applied"},
    {"name": "asset.schema.json",
     "path": "schema/asset.schema.json",
     "media_type": "application/json",
     "description": "Asset Identity Map entry (GET/PUT /assets)"},
    {"name": "device-diagnostics.schema.json",
     "path": "schema/device-diagnostics.schema.json",
     "media_type": "application/json",
     "description": "Device diagnostics payload; core vocabulary + x_vendor"},
    {"name": "diagnostics-vocabulary.json",
     "path": "spec/private-profile/diagnostics-vocabulary.json",
     "media_type": "application/json",
     "description": "Normative core diagnostics vocabulary: field names, units, standards, tier defaults + the x_vendor routing rule"},
    {"name": "device-diagnostics.yaml",
     "path": "spec/private-profile/device-diagnostics.yaml",
     "media_type": "application/yaml",
     "description": "GET /device-diagnostics/v0/{assetId} extension resource"},
    {"name": "asyncapi-stream.yaml",
     "path": "spec/private-profile/asyncapi-stream.yaml",
     "media_type": "application/yaml",
     "description": "Position stream channel + message (AsyncAPI)"},
    {"name": "extensions.yaml",
     "path": "spec/private-profile/extensions.yaml",
     "media_type": "application/yaml",
     "description": "Management + extension endpoints OpenAPI"},
    {"name": "hop-log.schema.json",
     "path": "schema/hop-log.schema.json",
     "media_type": "application/json",
     "description": "Per-hop latency log line"},
]

# First existing base wins: env override, the baked image dir, then the repo tree
# (parents[4] is the repo root from app/routers/contracts.py) for dev and tests.
_BASES = [
    os.environ.get("CONTRACTS_DIR"),
    "/app/contracts",
    str(Path(__file__).resolve().parents[4]),
]


def _resolve(rel_path: str) -> Path | None:
    for base in _BASES:
        if not base:
            continue
        candidate = Path(base) / rel_path
        if candidate.is_file():
            return candidate
    return None


@router.get("/contracts")
def contracts_index() -> dict:
    """Index of the baked contracts a consumer can fetch from this gateway."""
    return {"contracts": [
        {k: entry[k] for k in ("name", "path", "media_type", "description")}
        for entry in _MANIFEST
    ]}


@router.get("/contracts/{name}")
def contract_by_name(name: str) -> Response:
    entry = next((e for e in _MANIFEST if e["name"] == name), None)
    if entry is None:
        raise HTTPException(404, detail="unknown contract")
    path = _resolve(entry["path"])
    if path is None:
        raise HTTPException(404, detail="contract not available in this image")
    return Response(content=path.read_bytes(), media_type=entry["media_type"])
