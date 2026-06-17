"""Asset Identity Map: authoring, read, and per-asset telemetry.

The gateway is the authority for the asset registry exactly as the engine is
for the blueprint: GET /assets returns the current map, PUT /assets replaces it
(persisted to the store / PVC). The KELT dashboard writes here over HTTP -
never by mounting a file (mounted files have shadowed runtime state twice).

GET /assets/{asset_id}/details is a vendor extension for the demo UI: it joins
the asset to live engine telemetry (strategy, contributing sources, accuracy,
altitude) that the CAMARA Location response intentionally hides.

Conforms to schema/asset.schema.json. Authoring shares the read role for now;
org-scoped write authorisation lands with the 2-legged enterprise-token work.
"""

from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..assets import AssetMap, asset_by_id, load_asset_map, save_asset_map
from ..auth import consumer_org, require_location_role
from ..errors import CamaraError
from ..position import authorize_asset, get_position_details

router = APIRouter(prefix="/assets", tags=["Asset Identity Map"])


@router.get("", response_model=AssetMap)
async def get_assets(claims: dict = Depends(require_location_role)) -> AssetMap:
    amap = load_asset_map()
    org = consumer_org(claims)
    if org:  # tenant gate: a consumer sees only its own org's assets
        amap = AssetMap(version=amap.version, assets=[a for a in amap.assets if a.org == org])
    return amap


@router.put("", response_model=AssetMap)
async def put_assets(
    body: AssetMap,
    _claims: dict = Depends(require_location_role),
) -> AssetMap:
    save_asset_map(body)
    return body


class AssetTelemetry(BaseModel):
    latitude: float
    longitude: float
    accuracy_m: float
    altitude: Optional[float] = None
    lastLocationTime: str
    strategy: str
    sources: list[str]


class AssetDetailsResponse(BaseModel):
    asset_id: str
    positioning_id: str
    kind: str
    source: str
    org: str
    label: str
    simulated: bool = False
    telemetry: Optional[AssetTelemetry] = None


def _rfc3339(dt) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/{asset_id}/details", response_model=AssetDetailsResponse)
async def asset_details(
    asset_id: str,
    claims: dict = Depends(require_location_role),
) -> AssetDetailsResponse:
    asset = asset_by_id(asset_id)
    if asset is None:
        raise CamaraError(404, "IDENTIFIER_NOT_FOUND", "Asset not found.")
    authorize_asset(asset, claims)  # cross-tenant -> 404 (no existence leak)

    details = await get_position_details(asset.positioning_id)
    telemetry = None
    if details is not None:
        telemetry = AssetTelemetry(
            latitude=details.latitude,
            longitude=details.longitude,
            accuracy_m=details.radius_m,
            altitude=details.altitude_m,
            lastLocationTime=_rfc3339(details.last_location_time),
            strategy=details.strategy,
            sources=details.sources,
        )
    return AssetDetailsResponse(
        asset_id=asset.asset_id,
        positioning_id=asset.positioning_id,
        kind=asset.kind,
        source=asset.source,
        org=asset.org,
        label=asset.label or asset.asset_id,
        simulated=asset.simulated,
        telemetry=telemetry,
    )
