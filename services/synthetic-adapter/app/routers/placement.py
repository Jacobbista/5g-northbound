"""Place and remove a synthetic device.

Only this adapter has these endpoints, and only it can: a real source reports
where its hardware actually is, and there is nothing to place. This one
synthesises the position, so where it starts is a choice, and the demo hands
that choice to the operator.

Coordinates are in the room frame: metres from the room's lower-left corner, x
along the width, y along the depth. It is the frame the walker keeps and the
blueprint stores.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ..config import settings

log = logging.getLogger(__name__)
router = APIRouter(tags=["placement"])


class Placement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    x: float
    y: float


class PlacementResult(BaseModel):
    id: str
    # The room whose frame x and y are in.
    room: Optional[str] = None
    x: float
    y: float
    placed: bool


def _served(device_id: str) -> bool:
    """Same scoping the measurement endpoint applies: an empty DEVICE_IDS
    serves everything, otherwise only the configured ids."""
    served = {d.strip() for d in settings.device_ids.split(",") if d.strip()}
    return not served or device_id in served


@router.put("/devices/{device_id}/placement", response_model=PlacementResult)
async def place(device_id: str, body: Placement, request: Request):
    """Put the device at a point and start it walking from there.

    Idempotent: placing an already-placed device moves it, which is what
    dropping it somewhere else means. The response carries where it actually
    landed, since the point is clamped into the room.
    """
    if not _served(device_id):
        raise HTTPException(404, detail=f"{device_id} not served by this adapter")
    x, y = request.app.state.walker.place(device_id, body.x, body.y)
    log.info("placed %s at room (%.2f, %.2f)", device_id, x, y)
    return PlacementResult(id=device_id, room=request.app.state.walker.room_id, x=x, y=y, placed=True)


@router.delete("/devices/{device_id}/placement", response_model=PlacementResult)
async def remove(device_id: str, request: Request):
    """Stop the device reporting. It disappears from every consumer the same
    way any source that stops reporting does, with no special case downstream.

    Idempotent: removing a device that is not placed is not an error, the
    caller wanted it gone and it is gone.
    """
    if not _served(device_id):
        raise HTTPException(404, detail=f"{device_id} not served by this adapter")
    existed = request.app.state.walker.remove(device_id)
    if existed:
        log.info("removed %s", device_id)
    return PlacementResult(id=device_id, x=0.0, y=0.0, placed=False)
