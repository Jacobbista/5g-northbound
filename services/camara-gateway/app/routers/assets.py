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

from ..assets import AssetMap, asset_by_id, list_assets, load_asset_map, save_asset_map
from ..auth import consumer_org, require_location_role
from ..errors import CamaraError
from ..position import authorize_asset, get_engine_devices, get_fused_details

router = APIRouter(prefix="/assets", tags=["Asset Identity Map"])


@router.get("", response_model=AssetMap)
async def get_assets(claims: dict = Depends(require_location_role)) -> AssetMap:
    amap = load_asset_map()
    org = consumer_org(claims)
    if org:  # tenant gate: a consumer sees only its own org's assets
        amap = AssetMap(version=amap.version, assets=[a for a in amap.assets if a.org == org])
    return amap


def _reject_duplicate_positioning_ids(amap: AssetMap) -> None:
    """The engine routes a `positioningId` to exactly one adapter-learned
    source (docs/asset-registry.md); two assets claiming the same one starve
    one of them on the stream (an internal lookup keyed by positioningId can
    resolve to only one asset) and would blend one asset's telemetry into the
    other's fusion. Reject at write time instead of letting it land - the
    store is not re-validated on every read, so this is the only gate."""
    seen: dict[str, str] = {}
    for asset in amap.assets:
        for cap in asset.capabilities:
            prior = seen.get(cap.positioningId)
            if prior is not None:
                raise CamaraError(
                    422, "DUPLICATE_POSITIONING_ID",
                    f"positioningId '{cap.positioningId}' is claimed by both "
                    f"'{prior}' and '{asset.assetId}'.",
                )
            seen[cap.positioningId] = asset.assetId


@router.put("", response_model=AssetMap)
async def put_assets(
    body: AssetMap,
    _claims: dict = Depends(require_location_role),
) -> AssetMap:
    _reject_duplicate_positioning_ids(body)
    save_asset_map(body)
    return body


class DiscoverableDevice(BaseModel):
    # `id` is the source's device id; it becomes the asset's positioningId on
    # onboarding. `origin` = inventory (vendor, bulk-safe) | observed (wifi,
    # claim + label). `role` (paper vocab) = infrastructure (fixed sensor -
    # anchor/gateway, outside 3GPP trust, NOT onboardable) | asset (the tracked
    # entity); absent when the source did not classify it. `sourceClass` = the
    # positioning technology (uwb/ble/wifi/gnss/cellular/other). `deviceType`
    # is the native vendor type. No `org` yet - assigned at onboard.
    id: str
    source: str
    origin: Optional[str] = None
    role: Optional[str] = None
    sourceClass: Optional[str] = None
    deviceType: Optional[str] = None
    label: Optional[str] = None
    lastSeen: Optional[float] = None


class DiscoverableResponse(BaseModel):
    candidates: list[DiscoverableDevice]


@router.get("/discoverable", response_model=DiscoverableResponse)
async def discoverable(_claims: dict = Depends(require_location_role)) -> DiscoverableResponse:
    """Vendor extension: devices the live sources report that are NOT yet
    onboarded as assets. KELT's Assets tab offers these for one-click
    onboarding with `source` prefilled, so the operator picks from discovery
    instead of hand-typing every asset. Already-mapped positioning_ids are
    subtracted. Candidates are unclaimed (no org) until onboarded."""
    devices = await get_engine_devices() or []
    mapped = {cap.positioningId for a in list_assets() for cap in a.capabilities}
    seen: set[str] = set()
    candidates: list[DiscoverableDevice] = []
    for d in devices:
        device_id = d.get("id")
        if not device_id or device_id in mapped or device_id in seen:
            continue
        seen.add(device_id)
        candidates.append(
            DiscoverableDevice(
                id=device_id,
                source=d.get("source", ""),
                origin=d.get("origin"),
                role=d.get("role"),
                sourceClass=d.get("sourceClass"),
                deviceType=d.get("deviceType"),
                label=d.get("label"),
                lastSeen=d.get("lastSeen"),
            )
        )
    return DiscoverableResponse(candidates=candidates)


class AssetTelemetry(BaseModel):
    latitude: float
    longitude: float
    accuracy: float
    altitude: Optional[float] = None
    lastLocationTime: str
    strategy: str
    sources: list[str]


class AssetDetailsResponse(BaseModel):
    assetId: str
    positioningId: str
    kind: str
    source: str
    org: str
    label: str
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

    details = await get_fused_details(asset.capabilities)
    telemetry = None
    if details is not None:
        telemetry = AssetTelemetry(
            latitude=details.latitude,
            longitude=details.longitude,
            accuracy=details.radius_m,
            altitude=details.altitude_m,
            lastLocationTime=_rfc3339(details.last_location_time),
            strategy=details.strategy,
            sources=details.sources,
        )
    return AssetDetailsResponse(
        assetId=asset.assetId,
        positioningId=asset.positioning_id,
        kind=asset.kind,
        source=asset.source,
        org=asset.org,
        label=asset.label or asset.assetId,
        telemetry=telemetry,
    )
