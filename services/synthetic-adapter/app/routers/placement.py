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
    # The room whose frame x and y are in. Room and point are absent when the
    # device is not placed.
    room: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    placed: bool


def _anchors() -> set[str]:
    return {d.strip() for d in settings.anchor_ids.split(",") if d.strip()}


@router.put("/devices/{device_id}/placement", response_model=PlacementResult)
async def place(device_id: str, body: Placement, request: Request):
    """Put the device at a point and start it walking from there.

    Placing an id the inventory does not declare creates the device: for a
    simulated source, a device exists once it is put somewhere. It walks and
    reports like a declared one until it is removed.

    Idempotent: placing an already-placed device moves it, which is what
    dropping it somewhere else means. The response carries where it actually
    landed, since the point is clamped into the room.
    """
    if device_id in _anchors():
        raise HTTPException(422, detail=f"{device_id} is fixed infrastructure and cannot be placed")
    x, y = request.app.state.walker.place(device_id, body.x, body.y)
    log.info("placed %s at room (%.2f, %.2f)", device_id, x, y)
    return PlacementResult(id=device_id, room=request.app.state.walker.room_id, x=x, y=y, placed=True)


@router.delete("/devices/{device_id}/placement", response_model=PlacementResult)
async def remove(device_id: str, request: Request):
    """Stop the device reporting. It disappears from every consumer the same
    way any source that stops reporting does, with no special case downstream.

    A device that exists only because it was placed ceases to exist.

    Idempotent: removing a device that is not placed is not an error, the
    caller wanted it gone and it is gone.
    """
    existed = request.app.state.walker.remove(device_id)
    if existed:
        log.info("removed %s", device_id)
    return PlacementResult(id=device_id, placed=False)
