from fastapi import APIRouter, HTTPException, Request

from ..models import Measurement

router = APIRouter(tags=["measurement"])


@router.get("/measurement/{device_id}", response_model=Measurement)
async def get_measurement(device_id: str, request: Request):
    m = request.app.state.adapter.get_measurement(device_id)
    if m is None:
        # 404 lets positioning-engine treat us as "no fix yet" without retrying
        raise HTTPException(404, detail="no measurement for device")
    return m
