import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..models import EnginePosition, FusionOutput
from ..services.geo import local_to_gps, venue_altitude
from ..services.position_service import (
    PositionService,
    get_position_service,
    ts_to_iso,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/position", tags=["position"])


@router.get("/{device_id}", response_model=EnginePosition)
async def get_position(
    device_id: str,
    request: Request,
    source: str | None = None,
    svc: PositionService = Depends(get_position_service),
):
    origin = request.app.state.floor_plan.gps_origin
    if origin is None:
        # No georeference, no WGS84 position. Not a missing fix: the venue
        # cannot be placed on the Earth until the blueprint carries a georef.
        raise HTTPException(503, detail="the venue has no georeference")
    try:
        result = await svc.get_position(device_id, source)

        if result is None:
            # No adapter has a fix for this device. Surface as 404 so the
            # gateway (and the demo) can distinguish "offline" from a bad fix.
            raise HTTPException(404, detail=f"no fix for {device_id}")

        primary = result.primary.fused
        lat, lon = local_to_gps(primary.x, primary.y, origin)
        altitude = venue_altitude(primary.z, origin)

        fusions = None
        if result.compare:
            fusions = {}
            for sr in result.compare:
                f_lat, f_lon = local_to_gps(sr.fused.x, sr.fused.y, origin)
                fusions[sr.name] = FusionOutput(
                    latitude=f_lat,
                    longitude=f_lon,
                    accuracy=round(sr.fused.accuracy, 4),
                    sources=sr.fused.sources,
                )

        return EnginePosition(
            positioningId=device_id,
            latitude=lat,
            longitude=lon,
            accuracy=round(primary.accuracy, 4),
            timestamp=ts_to_iso(primary.timestamp),
            sources=primary.sources,
            strategy=result.primary.name,
            fusions=fusions,
            altitude=altitude,
            verticalAccuracy=(
                round(primary.verticalAccuracy, 4)
                if altitude is not None and primary.verticalAccuracy is not None else None
            ),
            establishedAt=(
                ts_to_iso(primary.establishedAt) if primary.establishedAt is not None else None
            ),
            current=primary.current,
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("get_position failed for %s", device_id)
        raise HTTPException(500, detail=str(exc)) from exc
