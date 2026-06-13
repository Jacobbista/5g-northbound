"""Vendor extension: device discovery + per-device details for the demo UI.

Not part of CAMARA Device Location. Lets the demo:
- list registered devices (so the user can pick which to track)
- read engine-side telemetry (strategy, contributing sources, accuracy) that
  the CAMARA Location response intentionally hides.
"""

from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import require_location_role
from ..errors import CamaraError
from ..position import get_position_details
from ..registry import load_devices

router = APIRouter(prefix="/devices", tags=["Device discovery (vendor extension)"])


class DiscoveryDevice(BaseModel):
    phoneNumber: str
    deviceId: str
    label: str
    simulated: bool = False


class DiscoveryResponse(BaseModel):
    devices: list[DiscoveryDevice]


class DeviceTelemetry(BaseModel):
    latitude: float
    longitude: float
    accuracy_m: float
    lastLocationTime: str
    strategy: str
    sources: list[str]


class DeviceDetailsResponse(BaseModel):
    phoneNumber: str
    deviceId: str
    label: str
    telemetry: Optional[DeviceTelemetry] = None


@router.get("", response_model=DiscoveryResponse)
async def list_devices(_claims: dict = Depends(require_location_role)) -> DiscoveryResponse:
    return DiscoveryResponse(
        devices=[
            DiscoveryDevice(
                phoneNumber=d.phoneNumber,
                deviceId=d.deviceId,
                label=d.label,
                simulated=d.simulated,
            )
            for d in load_devices()
        ]
    )


def _rfc3339(dt) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/{phone_number}/details", response_model=DeviceDetailsResponse)
async def device_details(
    phone_number: str,
    _claims: dict = Depends(require_location_role),
) -> DeviceDetailsResponse:
    match = next((d for d in load_devices() if d.phoneNumber == phone_number), None)
    if match is None:
        raise CamaraError(404, "IDENTIFIER_NOT_FOUND", "Device identifier not found.")

    details = await get_position_details(match.deviceId)
    telemetry = None
    if details is not None:
        telemetry = DeviceTelemetry(
            latitude=details.latitude,
            longitude=details.longitude,
            accuracy_m=details.radius_m,
            lastLocationTime=_rfc3339(details.last_location_time),
            strategy=details.strategy,
            sources=details.sources,
        )
    return DeviceDetailsResponse(
        phoneNumber=match.phoneNumber,
        deviceId=match.deviceId,
        label=match.label,
        telemetry=telemetry,
    )
