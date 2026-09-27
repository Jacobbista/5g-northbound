from math import cos, radians, sin
from typing import Optional

from ..models import GpsOrigin, RoomPlacement

# Metres per degree of latitude (and of longitude at the equator).
_M_PER_DEG = 111_320.0


def _rot_matrix(azimuth_deg: float) -> tuple[float, float, float, float]:
    """Rotation matrix [c, s, -s, c] applied as venue(x, y) -> earth(east, north).

    Convention: azimuth_deg is the bearing of venue +y relative to true north,
    clockwise. With azimuth=0 the floor plan is north-aligned and the rotation
    is identity.
    """
    a = radians(azimuth_deg)
    return cos(a), sin(a), -sin(a), cos(a)


def venue_altitude(z: Optional[float], origin: Optional[GpsOrigin]) -> Optional[float]:
    """Height above the WGS84 ellipsoid: the ellipsoidal height of the venue
    origin plus the height above the venue floor. None unless both are known."""
    if z is None or origin is None or origin.altitude_m is None:
        return None
    return round(origin.altitude_m + z, 3)


def room_to_venue(x: float, y: float, room: RoomPlacement) -> tuple[float, float]:
    """Room coordinates to venue coordinates: the room's rotation, clockwise on
    the plan about its centre, then its offset in the floor plan."""
    cx = room.x_m + room.width_m / 2
    cy = room.y_m + room.depth_m / 2
    dx = room.x_m + x - cx
    dy = room.y_m + y - cy
    a = radians(room.rotation_deg)
    return cx + dx * cos(a) + dy * sin(a), cy - dx * sin(a) + dy * cos(a)


def local_to_gps(x: float, y: float, origin: Optional[GpsOrigin]) -> tuple[float, float]:
    """Convert venue metres to WGS84 lat/lon.

    Venue frame: origin at the floor plan's lower-left corner, x along its
    width, y along its depth. `azimuth_deg` rotates the venue axes relative to
    true north/east before the metres-to-degrees projection.

    Returns (0.0, 0.0) when no GPS origin is configured (graceful degradation).
    """
    if origin is None:
        return 0.0, 0.0
    c, s, _, _ = _rot_matrix(origin.azimuth_deg)
    east = x * c + y * s
    north = -x * s + y * c
    lat = origin.latitude + north / _M_PER_DEG
    lon = origin.longitude + east / (_M_PER_DEG * cos(radians(origin.latitude)))
    return lat, lon


def gps_to_local(latitude: float, longitude: float, origin: Optional[GpsOrigin]) -> tuple[float, float]:
    """Inverse of local_to_gps. Returns venue (x, y) in metres.

    Used to project WGS84-native adapter measurements (e.g. Wittra) into the
    venue frame so the fusion stage operates in one coordinate space. Returns
    (0.0, 0.0) when no GPS origin is configured.
    """
    if origin is None:
        return 0.0, 0.0
    d_east = (longitude - origin.longitude) * _M_PER_DEG * cos(radians(origin.latitude))
    d_north = (latitude - origin.latitude) * _M_PER_DEG
    c, s, _, _ = _rot_matrix(origin.azimuth_deg)
    # Transpose of the rotation used in local_to_gps (rotation matrices are orthogonal).
    x = d_east * c - d_north * s
    y = d_east * s + d_north * c
    return x, y
