"""Vendor extension: proxy of the engine's adapter health snapshot.

Lets the demo (which talks only to the gateway, per architecture) surface
"wittra: degraded" without reaching past the gateway.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import require_location_role
from ..position import get_adapter_status

router = APIRouter(prefix="/adapters", tags=["Adapter health (vendor extension)"])


class AdapterStatus(BaseModel):
    name: str
    base_url: str
    fail_count: int
    in_cooldown: bool
    cooldown_seconds_remaining: float


class AdaptersResponse(BaseModel):
    adapters: list[AdapterStatus]


@router.get("", response_model=AdaptersResponse)
async def adapter_status(_claims: dict = Depends(require_location_role)) -> AdaptersResponse:
    raw = await get_adapter_status()
    if not raw:
        return AdaptersResponse(adapters=[])
    return AdaptersResponse(adapters=[AdapterStatus(**a) for a in raw])
