from datetime import timezone
from math import acos, asin, cos, pi, radians, sin, sqrt

from fastapi import APIRouter, Depends

from ..auth import require_location_role
from ..errors import CamaraError
from ..models import VerifyLocationRequest, VerifyLocationResponse
from ..position import authorize_asset, get_position, resolve_asset

router = APIRouter(prefix="/location-verification/v3", tags=["Location verification"])

_EARTH_RADIUS_M = 6_371_000.0


def _rfc3339(dt) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * asin(sqrt(a))


def _circle_overlap_fraction(d: float, r_fix: float, r_area: float) -> float:
    """Fraction of the fix circle (radius r_fix) covered by the area circle
    (radius r_area) whose centres are d apart. Called only when the two circles
    partially overlap."""
    if d <= 0:
        return min(1.0, (r_area * r_area) / (r_fix * r_fix))
    d2 = d * d
    inter = (
        r_fix * r_fix * acos((d2 + r_fix * r_fix - r_area * r_area) / (2 * d * r_fix))
        + r_area * r_area * acos((d2 + r_area * r_area - r_fix * r_fix) / (2 * d * r_area))
        - 0.5 * sqrt(
            max(0.0, (-d + r_fix + r_area) * (d + r_fix - r_area)
                * (d - r_fix + r_area) * (d + r_fix + r_area))
        )
    )
    return max(0.0, min(1.0, inter / (pi * r_fix * r_fix)))


def _classify(pos, area) -> tuple[str, int | None]:
    """TRUE/FALSE/PARTIAL from the fix's uncertainty circle against the queried
    area. The fix is a circle (centre, radius = accuracy): TRUE when it lies
    fully inside the area, FALSE when fully outside, PARTIAL when it straddles
    the boundary - with matchRate the percentage of the fix circle inside."""
    d = _haversine_m(
        pos.latitude, pos.longitude, area.center.latitude, area.center.longitude
    )
    r_fix = max(pos.radius_m, 1.0)
    r_area = area.radius
    if d + r_fix <= r_area:
        return "TRUE", None
    if d >= r_area + r_fix:
        return "FALSE", None
    frac = _circle_overlap_fraction(d, r_fix, r_area)
    return "PARTIAL", min(99, max(1, round(frac * 100)))


@router.post("/verify", response_model=VerifyLocationResponse, response_model_exclude_none=True)
async def verify(
    body: VerifyLocationRequest,
    claims: dict = Depends(require_location_role),
) -> VerifyLocationResponse:
    if body.device is None:
        raise CamaraError(422, "MISSING_IDENTIFIER", "The asset cannot be identified.")

    asset = resolve_asset(body.device)
    authorize_asset(asset, claims)  # tenant gate (org claim vs asset.org)
    pos = await get_position(
        asset.positioning_id, asset.source, body.maxAge, "LOCATION_VERIFICATION"
    )

    result, match_rate = _classify(pos, body.area)
    return VerifyLocationResponse(
        verificationResult=result,
        lastLocationTime=_rfc3339(pos.last_location_time),
        matchRate=match_rate,
    )
