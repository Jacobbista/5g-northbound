from datetime import timezone
from math import asin, cos, radians, sin, sqrt

from fastapi import APIRouter, Depends

from ..auth import require_location_role
from ..errors import CamaraError
from ..models import VerifyLocationRequest, VerifyLocationResponse
from ..position import get_position, resolve_device_id

router = APIRouter(prefix="/location-verification/v3", tags=["Location verification"])

_EARTH_RADIUS_M = 6_371_000.0


def _rfc3339(dt) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * asin(sqrt(a))


@router.post("/verify", response_model=VerifyLocationResponse, response_model_exclude_none=True)
async def verify(
    body: VerifyLocationRequest,
    _claims: dict = Depends(require_location_role),
) -> VerifyLocationResponse:
    if body.device is None:
        raise CamaraError(422, "MISSING_IDENTIFIER", "The device cannot be identified.")

    device_id = resolve_device_id(body.device)
    pos = await get_position(device_id)

    distance = _haversine_m(
        pos.latitude, pos.longitude, body.area.center.latitude, body.area.center.longitude
    )
    # MVP uses a single-point estimate: inside -> TRUE, otherwise FALSE (no PARTIAL).
    result = "TRUE" if distance <= body.area.radius else "FALSE"
    return VerifyLocationResponse(
        verificationResult=result,
        lastLocationTime=_rfc3339(pos.last_location_time),
    )
