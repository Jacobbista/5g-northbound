"""Vendor extension: proxy of the engine's adapter health snapshot.

Lets the demo (which talks only to the gateway, per architecture) surface
"wittra: degraded" without reaching past the gateway.
"""

from typing import Any

from fastapi import APIRouter, Depends

from ..auth import require_location_role
from ..position import get_adapter_status

router = APIRouter(prefix="/adapters", tags=["Adapter health (vendor extension)"])


@router.get("")
async def adapter_status(_claims: dict = Depends(require_location_role)) -> dict[str, Any]:
    """Pass the engine's adapter registry snapshot through unchanged so the demo
    sees every field (state, kind, registered_via, last_seen_s_ago, cooldown).
    The gateway does not reshape it - the engine owns the contract."""
    raw = await get_adapter_status()
    return {"adapters": raw or []}
