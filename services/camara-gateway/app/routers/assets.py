"""Asset Identity Map: authoring, read, and per-asset telemetry.

The gateway is the authority for the asset registry exactly as the engine is
for the blueprint: GET /assets returns the current map, PUT /assets replaces it
(persisted to the store / PVC). The KELT dashboard writes here over HTTP -
never by mounting a file (mounted files have shadowed runtime state twice).

GET /assets/{asset_id}/details is a vendor extension for the demo UI: it joins
the asset to live engine telemetry (strategy, contributing sources, accuracy,
altitude) that the CAMARA Location response intentionally hides.

Conforms to schema/asset.schema.json. Writes and discovery take an operator
token, one without an `org` claim.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..assets import AssetMap, asset_by_id, list_assets, load_asset_map, save_asset_map, validate_for_write
from ..auth import consumer_org, require_location_role, require_operator
from ..errors import CamaraError
from ..position import authorize_asset, get_adapter_status, get_engine_devices, get_fused_details

router = APIRouter(prefix="/assets", tags=["Asset Identity Map"])


@router.get("", response_model=AssetMap)
async def get_assets(claims: dict = Depends(require_location_role)) -> AssetMap:
    amap = load_asset_map()
    org = consumer_org(claims)
    if org:  # tenant gate: a consumer sees only its own org's assets
        amap = AssetMap(version=amap.version, assets=[a for a in amap.assets if a.org == org])
    return amap


async def _known_sources() -> Optional[set[str]]:
    """The sources the live fabric currently serves, or None when it cannot be
    asked. The set comes from the engine's adapter registry rather than a list
    in this file: the valid sources are whichever adapters are deployed right
    now, and that changes without a gateway release. `GET /capabilities`
    aggregates the same data for consumers.

    A source matches either the adapter's registered name (what the engine
    routes on) or the `source` its capabilities declare. Deployments keep the
    two equal by convention, and accepting both means a deployment that does
    not is still writable.
    """
    adapters = await get_adapter_status()
    if adapters is None:
        return None
    sources: set[str] = set()
    for ad in adapters:
        caps = ad.get("capabilities") or {}
        if ad.get("name"):
            sources.add(ad["name"])
        if caps.get("source"):
            sources.add(caps["source"])
    return sources


def _reject_unknown_source(amap: AssetMap, sources: set[str]) -> None:
    """An asset whose source no adapter serves gets no position, ever, and says
    nothing about why. A typo in that field would be accepted and then silent.
    Catch it where it is written. The asset's `kind` is the site's own word for
    the object and is not checked: no adapter can know it."""
    for asset in amap.assets:
        for cap in asset.capabilities:
            if cap.source not in sources:
                raise CamaraError(
                    422, "UNKNOWN_SOURCE",
                    f"asset '{asset.assetId}': source '{cap.source}' is served by no "
                    f"adapter. Known: {', '.join(sorted(sources)) or 'none'}.",
                )


@router.put("", response_model=AssetMap)
async def put_assets(
    body: AssetMap,
    _claims: dict = Depends(require_operator),
) -> AssetMap:
    validate_for_write(body)
    sources = await _known_sources()
    if sources is not None:
        # Sources the stored map already uses are not typos, so they stay
        # writable even while their adapter is down long enough to be evicted
        # from the registry. The cost is that a typo written before this check
        # existed is grandfathered rather than caught.
        current = load_asset_map()
        sources |= {c.source for a in current.assets for c in a.capabilities}
        _reject_unknown_source(body, sources)
    # An engine that cannot be reached cannot be asked, and a check that cannot
    # run must not block an operator from writing.
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
    # When the device last communicated with its source, RFC 3339 UTC. Absent
    # when the source exposes no such signal.
    lastCommunicationTime: Optional[str] = None


class DiscoverableResponse(BaseModel):
    candidates: list[DiscoverableDevice]


@router.get("/discoverable", response_model=DiscoverableResponse)
async def discoverable(_claims: dict = Depends(require_operator)) -> DiscoverableResponse:
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
                lastCommunicationTime=(
                    _rfc3339(datetime.fromtimestamp(d["lastSeen"], timezone.utc))
                    if d.get("lastSeen") is not None else None
                ),
            )
        )
    return DiscoverableResponse(candidates=candidates)


class AssetTelemetry(BaseModel):
    latitude: float
    longitude: float
    accuracy: float
    altitude: Optional[float] = None
    verticalAccuracy: Optional[float] = None
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
            verticalAccuracy=details.vertical_accuracy_m,
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
