from fastapi import APIRouter, HTTPException, Request

from ..config import settings
from ..models import Measurement

router = APIRouter(tags=["measurement"])


@router.get("/measurement/{device_id}", response_model=Measurement)
async def get_measurement(device_id: str, request: Request):
    # A device this source neither declares nor has placed is unknown: 404, so
    # an engine that asks every adapter never receives an invented position
    # for another source's device.
    walker = request.app.state.walker
    if not walker.knows(device_id):
        raise HTTPException(404, detail=f"{device_id} is not a device of this source")
    if not walker.is_active(device_id):
        # Declared but not placed: no fix, the same answer an adapter gives
        # for a device it cannot currently locate. The engine skips this source
        # for this cycle without entering cooldown, and the asset simply has no
        # position until it is placed.
        raise HTTPException(404, detail=f"{device_id} is not placed")
    room = walker.ensure_room()
    if room is None:
        # The walk is in a room the blueprint has not named yet: the engine
        # could not place the fix, so there is none to report.
        raise HTTPException(404, detail="no blueprint room to report in")
    x, y, z, ts = walker.step(device_id)
    # Synthesised, not measured: read after the step that advanced the quality
    # they map from, so the pair matches the fix just produced.
    accuracy, confidence = walker.fidelity(device_id)
    return Measurement(
        source=settings.source,
        frame="room",
        room=room,
        x=round(x, 4),
        y=round(y, 4),
        z=round(z, 4),
        accuracy=accuracy,
        confidence=confidence,
        timestamp=ts,
    )
