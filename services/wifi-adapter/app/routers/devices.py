"""GET /devices - device discovery for onboarding.

Lists the device ids this adapter currently knows, so the management layer
(KELT Assets tab) can offer them for one-click onboarding instead of hand
entry. This is the standard adapter discovery endpoint; the engine aggregates
it across sources and the gateway subtracts already-onboarded ids.

`origin: observed` - wifi devices appear by activity (a scan tagged with the
id was ingested), so they are candidates a human claims + names, not a stable
vendor inventory.
"""

from fastapi import APIRouter, Request

router = APIRouter(tags=["devices"])


@router.get("/devices")
async def devices(request: Request) -> dict:
    adapter = getattr(request.app.state, "adapter", None)
    if adapter is None:
        # Degraded boot (blueprint still loading): no tracker yet, no devices.
        return {"origin": "observed", "devices": []}
    return {"origin": "observed", "devices": adapter.observed_devices()}
