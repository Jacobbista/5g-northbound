from fastapi import APIRouter, Request

from ..config import settings
from ..models import Measurement

router = APIRouter(tags=["measurement"])


@router.get("/measurement/{device_id}", response_model=Measurement)
async def get_measurement(device_id: str, request: Request):
    walker = request.app.state.walker
    x, y, z, ts = walker.step(device_id)
    return Measurement(
        source=settings.source,
        frame="local",
        x=round(x, 4),
        y=round(y, 4),
        z=round(z, 4),
        accuracy_m=settings.accuracy_m,
        confidence=settings.confidence,
        timestamp=ts,
    )
