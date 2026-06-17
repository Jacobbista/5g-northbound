from datetime import timezone

from fastapi import APIRouter, Depends

from ..auth import require_location_role
from ..errors import CamaraError
from ..models import Circle, Location, Point, RetrievalLocationRequest
from ..position import authorize_asset, get_position, resolve_asset

router = APIRouter(prefix="/location-retrieval/v0.5", tags=["Location retrieval"])


def _rfc3339(dt) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.post("/retrieve", response_model=Location, response_model_exclude_none=True)
async def retrieve(
    body: RetrievalLocationRequest,
    claims: dict = Depends(require_location_role),
) -> Location:
    # Two-legged token: subject is not in the token, so device is mandatory.
    if body.device is None:
        raise CamaraError(422, "MISSING_IDENTIFIER", "The asset cannot be identified.")

    asset = resolve_asset(body.device)
    authorize_asset(asset, claims)  # tenant gate (org claim vs asset.org)
    pos = await get_position(asset.positioning_id)
    return Location(
        lastLocationTime=_rfc3339(pos.last_location_time),
        area=Circle(
            center=Point(latitude=pos.latitude, longitude=pos.longitude),
            # CAMARA Circle requires radius >= 1 m
            radius=max(pos.radius_m, 1.0),
        ),
        # Private-asset profile extensions.
        source=asset.source,
        kind=asset.kind,
        altitude=pos.altitude_m,
        verticalAccuracy=pos.vertical_accuracy_m,
    )
