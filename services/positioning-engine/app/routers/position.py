import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..models import EnginePosition, FusionOutput
from ..services.geo import local_to_gps
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
    svc: PositionService = Depends(get_position_service),
):
    try:
        result = await svc.get_position(device_id)
        origin = request.app.state.floor_plan.gps_origin
        if origin is None:
            log.warning("floor plan has no gps_origin; returning 0,0 for %s", device_id)

        if result is None:
            # No adapter has a fix for this device. Surface as 404 so the
            # gateway (and the demo) can distinguish "offline" from a bad fix.
            raise HTTPException(404, detail=f"no fix for {device_id}")

        primary = result.primary.fused
        lat, lon = local_to_gps(primary.x, primary.z, origin)

        fusions = None
        if result.compare:
            fusions = {}
            for sr in result.compare:
                f_lat, f_lon = local_to_gps(sr.fused.x, sr.fused.z, origin)
                fusions[sr.name] = FusionOutput(
                    latitude=f_lat,
                    longitude=f_lon,
                    accuracy_m=round(sr.fused.accuracy_m, 4),
                    sources=sr.fused.sources,
                )

        return EnginePosition(
            device_id=device_id,
            latitude=lat,
            longitude=lon,
            accuracy_m=round(primary.accuracy_m, 4),
            timestamp=ts_to_iso(primary.timestamp),
            sources=primary.sources,
            strategy=result.primary.name,
            fusions=fusions,
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("get_position failed for %s", device_id)
        raise HTTPException(500, detail=str(exc)) from exc
