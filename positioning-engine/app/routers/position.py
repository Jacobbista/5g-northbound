import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..models import EnginePosition
from ..services.geo import local_to_gps
from ..services.position_service import PositionService, get_position_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/position", tags=["position"])


@router.get("/{device_id}", response_model=EnginePosition)
async def get_position(
    device_id: str,
    request: Request,
    svc: PositionService = Depends(get_position_service),
):
    try:
        pos = await svc.get_position(device_id)
        origin = request.app.state.floor_plan.gps_origin
        if origin is None:
            log.warning("floor plan has no gps_origin; returning 0,0 for %s", device_id)
        lat, lon = local_to_gps(pos.x, pos.z, origin)
        return EnginePosition(
            device_id=pos.device_id,
            latitude=lat,
            longitude=lon,
            accuracy_m=pos.accuracy_m,
            timestamp=pos.timestamp,
            sources=pos.sources,
        )
    except Exception as exc:
        log.exception("get_position failed for %s", device_id)
        raise HTTPException(500, detail=str(exc)) from exc
