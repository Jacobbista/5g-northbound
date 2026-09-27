"""Private-profile extension: GET /device-diagnostics/v0/{assetId}.

Not CAMARA Device Location. Resolves the asset to its positioning id + source,
proxies the source adapter's /diagnostics, and returns the namespaced payload.
Ids with no registered asset are rejected (same no-raw-id rule as the pull
path); org scoping matches retrieve."""

import httpx
from fastapi import APIRouter, Depends

from ..assets import asset_by_id
from ..auth import consumer_org, require_location_role
from ..config import get_settings
from ..errors import CamaraError
from ..obs import corr_headers
from ..position import adapter_base_url

router = APIRouter(tags=["diagnostics"])


@router.get("/device-diagnostics/v0/{asset_id}")
async def device_diagnostics(asset_id: str, claims: dict = Depends(require_location_role)):
    org = consumer_org(claims)
    asset = asset_by_id(asset_id)
    if asset is None or (org and asset.org != org):
        raise CamaraError(404, "IDENTIFIER_NOT_FOUND", "Asset not found.")
    base = await adapter_base_url(asset.source)
    if not base:
        raise CamaraError(404, "NOT_FOUND", "The asset's source exposes no diagnostics.")
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{base.rstrip('/')}/diagnostics/{asset.positioning_id}", headers=corr_headers())
    except httpx.HTTPError as exc:
        raise CamaraError(503, "UNAVAILABLE", "The source is unreachable.") from exc
    if r.status_code == 404:
        raise CamaraError(404, "NOT_FOUND", "The source has no diagnostics for this asset.")
    if r.status_code != 200:
        raise CamaraError(502, "BAD_GATEWAY", "The source failed to answer.")
    return {"assetId": asset.assetId, "source": asset.source, "diagnostics": r.json().get("diagnostics", {})}
