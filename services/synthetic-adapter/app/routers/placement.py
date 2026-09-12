"""Place and remove a synthetic device.

Only this adapter has these endpoints, and only it can: a real source reports
where its hardware actually is, and there is nothing to place. This one
synthesises the position, so where it starts is a choice, and the demo hands
that choice to the operator.

Coordinates are room-local canvas-y metres (origin top-left, x right, z down),
the frame the walker keeps, the placement editor stores, and the demo's 3D
scene renders. A point picked on screen needs no conversion on the way in.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ..config import settings

log = logging.getLogger(__name__)
router = APIRouter(tags=["placement"])


class Placement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    x: float
    z: float


class PlacementResult(BaseModel):
    id: str
    x: float
    z: float
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
    x, z = request.app.state.walker.place(device_id, body.x, body.z)
    log.info("placed %s at room-local (%.2f, %.2f)", device_id, x, z)
    return PlacementResult(id=device_id, x=x, z=z, placed=True)


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
    return PlacementResult(id=device_id, x=0.0, z=0.0, placed=False)
