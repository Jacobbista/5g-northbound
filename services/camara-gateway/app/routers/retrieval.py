from datetime import timezone

from fastapi import APIRouter, Depends

from ..auth import require_location_role
from ..errors import CamaraError
from ..models import Circle, Location, Point, RetrievalLocationRequest
from ..position import get_position, resolve_device_id

router = APIRouter(prefix="/location-retrieval/v0.5", tags=["Location retrieval"])


def _rfc3339(dt) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.post("/retrieve", response_model=Location, response_model_exclude_none=True)
async def retrieve(
    body: RetrievalLocationRequest,
    _claims: dict = Depends(require_location_role),
) -> Location:
    # Two-legged token: subject is not in the token, so device is mandatory.
    if body.device is None:
        raise CamaraError(422, "MISSING_IDENTIFIER", "The device cannot be identified.")

    device_id = resolve_device_id(body.device)
    pos = await get_position(device_id)
    return Location(
        lastLocationTime=_rfc3339(pos.last_location_time),
        area=Circle(
            center=Point(latitude=pos.latitude, longitude=pos.longitude),
            # CAMARA Circle requires radius >= 1 m
            radius=max(pos.radius_m, 1.0),
        ),
    )
