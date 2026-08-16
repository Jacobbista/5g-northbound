from datetime import timezone
from math import pi

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
    pos = await get_position(
        asset.positioning_id, asset.source, body.maxAge, "LOCATION_RETRIEVAL"
    )
    # CAMARA Circle requires radius >= 1 m; the same radius drives the maxSurface
    # check, so the area tested is the one actually reported.
    radius = max(pos.radius_m, 1.0)
    if body.maxSurface is not None and pi * radius * radius > body.maxSurface:
        raise CamaraError(
            422, "LOCATION_RETRIEVAL.UNABLE_TO_FULFILL_MAX_SURFACE",
            "Unable to provide a location within the requested maxSurface.",
        )
    return Location(
        lastLocationTime=_rfc3339(pos.last_location_time),
        area=Circle(
            center=Point(latitude=pos.latitude, longitude=pos.longitude),
            radius=radius,
        ),
        # Private-asset profile extensions.
        source=asset.source,
        kind=asset.kind,
        altitude=pos.altitude_m,
        verticalAccuracy=pos.vertical_accuracy_m,
    )
