"""Place a synthetic asset on the floor plan, and take it off again.

A profile extension, not CAMARA: the public API reports where a device is, it
has no notion of putting one somewhere. This exists because one source class
synthesises its position instead of measuring it, so where it starts is a
choice rather than a fact, and the demo hands that choice to the operator.

Asset-shaped like every other consumer surface: the caller names an assetId,
the gateway resolves it to the capability's positioningId and the adapter that
serves it. A positioning id never reaches a consumer. Only an adapter that
advertises the `placement` capability is proxied, so asking to place a real
source is refused here rather than 404ing somewhere downstream.
"""

import logging

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ..assets import asset_by_id
from ..auth import require_location_role
from ..errors import CamaraError
from ..obs import corr_headers
from ..position import adapter_base_url, authorize_asset, get_adapter_status

log = logging.getLogger(__name__)
router = APIRouter(prefix="/assets", tags=["placement"])

_TIMEOUT_S = 3.0


class Placement(BaseModel):
    """A point on the floor plan, in room-local metres: origin top-left, x
    right, z down. The frame the placement editor stores and the demo renders,
    so a point picked on screen travels unchanged."""

    model_config = ConfigDict(extra="ignore")
    x: float
    z: float


async def _placeable_adapter(source: str) -> str:
    """The base URL of the adapter serving `source`, once it is established
    that it accepts placement. Raises rather than returning None: every caller
    here wants the same refusals worded the same way."""
    adapters = await get_adapter_status()
    if adapters is None:
        raise CamaraError(503, "UNAVAILABLE", "The positioning fabric is unreachable.")
    for a in adapters:
        if a.get("name") != source:
            continue
        if not (a.get("capabilities") or {}).get("placement"):
            raise CamaraError(
                422, "NOT_PLACEABLE",
                f"source '{source}' reports a measured position and cannot be placed.",
            )
        base = a.get("baseUrl")
        if base:
            return base
    raise CamaraError(404, "IDENTIFIER_NOT_FOUND", f"no adapter serves source '{source}'.")


async def _proxy(method: str, asset_id: str, claims: dict, json: dict | None = None) -> dict:
    asset = asset_by_id(asset_id)
    if asset is None:
        raise CamaraError(404, "IDENTIFIER_NOT_FOUND", "Asset not found.")
    authorize_asset(asset, claims)  # cross-tenant reads as absent
    cap = asset.primary
    base = await _placeable_adapter(cap.source)
    url = f"{base.rstrip('/')}/devices/{cap.positioningId}/placement"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as c:
            r = await c.request(method, url, json=json, headers=corr_headers())
    except httpx.HTTPError as exc:
        log.warning("placement %s %s unreachable: %s", method, url, exc)
        raise CamaraError(503, "UNAVAILABLE", "The source is unreachable.") from exc
    if r.status_code >= 400:
        log.warning("placement %s %s -> %d", method, url, r.status_code)
        raise CamaraError(502, "BAD_GATEWAY", "The source rejected the placement.")
    body = r.json()
    # Answer in the caller's vocabulary: it asked about an asset.
    return {"assetId": asset_id, "x": body.get("x"), "z": body.get("z"),
            "placed": body.get("placed", False)}


@router.put("/{asset_id}/placement")
async def place(asset_id: str, body: Placement, claims: dict = Depends(require_location_role)):
    """Put the asset at a point and start it reporting from there. Placing an
    already-placed asset moves it. The response carries where it landed, since
    the source clamps the point into the room."""
    return await _proxy("PUT", asset_id, claims, json=body.model_dump())


@router.delete("/{asset_id}/placement")
async def remove(asset_id: str, claims: dict = Depends(require_location_role)):
    """Stop the asset reporting. It then has no position, exactly as if its
    source had gone quiet, with no special case anywhere downstream."""
    return await _proxy("DELETE", asset_id, claims)
