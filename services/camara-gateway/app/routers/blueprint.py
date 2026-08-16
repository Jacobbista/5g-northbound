"""Vendor extension: read-only proxy of the engine's blueprint.

The demo renders the venue (rooms, walls, anchors, georef) from the blueprint
but, per the MEC constraint in AGENTS.md, must not call the engine directly.
The gateway proxies the engine's `GET /blueprint` so the demo reads it through
its single allowed backend. Read-only: authoring goes editor -> engine, never
through here.
"""

from typing import Any

from fastapi import APIRouter, Depends

from ..auth import require_location_role
from ..errors import CamaraError
from ..position import get_blueprint

router = APIRouter(prefix="/blueprint", tags=["Blueprint (vendor extension)"])


@router.get("")
async def blueprint(_claims: dict = Depends(require_location_role)) -> dict[str, Any]:
    raw = await get_blueprint()
    if raw is None:
        raise CamaraError(404, "NOT_FOUND", "No blueprint available from the engine.")
    return raw
