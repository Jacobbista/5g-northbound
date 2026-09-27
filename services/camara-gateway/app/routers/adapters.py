"""Vendor extension: health of each positioning adapter.

Lets an application, which talks only to the gateway, show "wittra: degraded"
without reaching past it. Each entry carries the adapter's name, its state and
its declared capabilities. How the engine reaches the adapter stays internal.
"""

from typing import Any

from fastapi import APIRouter, Depends

from ..auth import require_location_role
from ..position import get_adapter_status

router = APIRouter(prefix="/adapters", tags=["Adapter health (vendor extension)"])


@router.get("")
async def adapter_status(_claims: dict = Depends(require_location_role)) -> dict[str, Any]:
    raw = await get_adapter_status() or []
    return {"adapters": [
        {"name": a.get("name", ""), "state": a.get("state"), "capabilities": a.get("capabilities") or {}}
        for a in raw
    ]}
