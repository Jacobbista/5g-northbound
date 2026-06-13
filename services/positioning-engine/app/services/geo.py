from math import cos, radians, sin
from typing import Optional

from ..models import GpsOrigin

# Metres per degree of latitude (and of longitude at the equator).
_M_PER_DEG = 111_320.0


def _rot_matrix(azimuth_deg: float) -> tuple[float, float, float, float]:
    """Rotation matrix [c, s, -s, c] applied as local(x, z) -> earth(east, north).

    Convention: azimuth_deg is the bearing of local +z relative to true
    north, clockwise. With azimuth=0 the floor-plan is north-aligned and the
    rotation is identity.
    """
    a = radians(azimuth_deg)
    return cos(a), sin(a), -sin(a), cos(a)


def local_to_gps(x: float, z: float, origin: Optional[GpsOrigin]) -> tuple[float, float]:
    """Convert floor-plan local metres to WGS84 lat/lon.

    Local frame: origin at the floor plan's lower-left corner, x = east-ish,
    z = north-ish. With `azimuth_deg` set, the local axes are rotated relative
    to true north/east; this function applies the rotation before the
    metres-to-degrees projection.

    Returns (0.0, 0.0) when no GPS origin is configured (graceful degradation).
    """
    if origin is None:
        return 0.0, 0.0
    c, s, _, _ = _rot_matrix(origin.azimuth_deg)
    east = x * c + z * s
    north = -x * s + z * c
    lat = origin.latitude + north / _M_PER_DEG
    lon = origin.longitude + east / (_M_PER_DEG * cos(radians(origin.latitude)))
    return lat, lon


def gps_to_local(latitude: float, longitude: float, origin: Optional[GpsOrigin]) -> tuple[float, float]:
    """Inverse of local_to_gps. Returns (x, z) in metres.

    Used to project WGS84-native adapter measurements (e.g. Wittra) into the
    floor-plan-local frame so the fusion stage operates in one coordinate
    space. Returns (0.0, 0.0) when no GPS origin is configured.
    """
    if origin is None:
        return 0.0, 0.0
    d_east = (longitude - origin.longitude) * _M_PER_DEG * cos(radians(origin.latitude))
    d_north = (latitude - origin.latitude) * _M_PER_DEG
    c, s, _, _ = _rot_matrix(origin.azimuth_deg)
    # Transpose of the rotation used in local_to_gps (rotation matrices are orthogonal).
    x = d_east * c - d_north * s
    z = d_east * s + d_north * c
    return x, z
