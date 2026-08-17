from fastapi import APIRouter, HTTPException, Request

from ..config import settings
from ..models import Measurement

router = APIRouter(tags=["measurement"])


def _served_ids() -> set[str]:
    return {d.strip() for d in settings.device_ids.split(",") if d.strip()}


@router.get("/measurement/{device_id}", response_model=Measurement)
async def get_measurement(device_id: str, request: Request):
    # Honest capability boundary: 404 for devices this mock does not own, so the
    # engine can fan out to every adapter (no DEVICE_MAP) without the walker
    # answering for - and polluting - other adapters' devices. Empty set = serve
    # all (standalone / legacy).
    served = _served_ids()
    if served and device_id not in served:
        raise HTTPException(404, detail=f"{device_id} not served by this mock")
    walker = request.app.state.walker
    x, y, z, ts = walker.step(device_id)
    # The walker steps in room-local (canvas-y); lift to the engine's
    # documented `local` frame (floor-plan-local, north-up) before emitting.
    fx, fz = walker.project_to_floor_plan(x, z)
    return Measurement(
        source=settings.source,
        frame="local",
        x=round(fx, 4),
        y=round(y, 4),
        z=round(fz, 4),
        accuracy_m=settings.accuracy_m,
        confidence=settings.confidence,
        timestamp=ts,
    )
