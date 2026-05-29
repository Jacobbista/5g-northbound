from math import cos, radians
from typing import Optional

from ..models import GpsOrigin

# Metres per degree of latitude (and of longitude at the equator).
_M_PER_DEG = 111_320.0


def local_to_gps(x: float, z: float, origin: Optional[GpsOrigin]) -> tuple[float, float]:
    """Convert floor-plan local metres to WGS84 lat/lon.

    Local frame: origin at the floor plan's lower-left corner, x = east, z = north.
    Returns (0.0, 0.0) when no GPS origin is configured (graceful degradation).
    """
    if origin is None:
        return 0.0, 0.0
    lat = origin.latitude + z / _M_PER_DEG
    lon = origin.longitude + x / (_M_PER_DEG * cos(radians(origin.latitude)))
    return lat, lon
