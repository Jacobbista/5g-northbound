"""GET /devices - device discovery for onboarding (standard adapter shape).

The mock serves a fixed, configured set of device ids (DEVICE_IDS), so its
discovery is an `inventory`: a stable, known list, bulk-onboardable. Positions
are omitted here - the walker synthesises them on /measurement, and listing
should not advance the walk.
"""

from fastapi import APIRouter

from ..config import settings

router = APIRouter(tags=["devices"])


@router.get("/devices")
async def devices() -> dict:
    ids = sorted({d.strip() for d in settings.device_ids.split(",") if d.strip()})
    return {"origin": "inventory", "devices": [{"id": d} for d in ids]}
