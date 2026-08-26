"""Private-profile extension: GET /device-diagnostics/v0/{assetId}.

Not CAMARA Device Location. Resolves the asset to its positioning id + source,
proxies the source adapter's /diagnostics, and returns the namespaced payload.
Ids with no registered asset are rejected (same no-raw-id rule as the pull
path); org scoping matches retrieve."""

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..assets import asset_by_id
from ..auth import consumer_org, require_location_role
from ..config import get_settings
from ..obs import corr_headers

router = APIRouter(tags=["diagnostics"])


async def _adapter_base_url(source: str) -> str | None:
    """Ask the engine which adapter serves `source` and return its base_url."""
    engine = get_settings().positioning_engine_url.rstrip("/")
    if not engine:
        return None
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{engine}/adapters", headers=corr_headers())
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    for a in r.json().get("adapters", []):
        if a.get("name") == source:
            return a.get("base_url")
    return None


@router.get("/device-diagnostics/v0/{asset_id}")
async def device_diagnostics(asset_id: str, claims: dict = Depends(require_location_role)):
    org = consumer_org(claims)
    asset = asset_by_id(asset_id)
    if asset is None or (org and asset.org != org):
        raise HTTPException(404, detail="unknown asset")
    base = await _adapter_base_url(asset.source)
    if not base:
        raise HTTPException(404, detail="source has no diagnostics")
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{base.rstrip('/')}/diagnostics/{asset.positioning_id}", headers=corr_headers())
    except httpx.HTTPError:
        raise HTTPException(404, detail="no diagnostics")
    if r.status_code != 200:
        raise HTTPException(404, detail="no diagnostics")
    return {"assetId": asset.asset_id, "source": asset.source, "diagnostics": r.json().get("diagnostics", {})}
