import math

from app.models import GpsOrigin
from app.services.geo import gps_to_local, local_to_gps


def test_local_to_gps_identity_when_origin_none():
    lat, lon = local_to_gps(5.0, 10.0, None)
    assert (lat, lon) == (0.0, 0.0)


def test_local_to_gps_no_rotation():
    """With azimuth=0, local +z is true north and local +x is true east."""
    origin = GpsOrigin(latitude=45.0, longitude=7.0)
    lat, lon = local_to_gps(0.0, 111_320.0, origin)
    # 111_320 m north == 1 degree of latitude.
    assert lat == 45.0 + 1.0
    # No east displacement → same longitude.
    assert math.isclose(lon, 7.0)


def test_local_to_gps_rotation_90deg_swaps_axes():
    """azimuth=90: local +z points east (instead of north)."""
    origin = GpsOrigin(latitude=45.0, longitude=7.0, azimuth_deg=90.0)
    lat, lon = local_to_gps(0.0, 111_320.0, origin)
    # 111_320 m along local +z, which is now east → longitude shifts, latitude stays.
    assert math.isclose(lat, 45.0, abs_tol=1e-9)
    assert lon > 7.0


def test_roundtrip_local_gps_local_no_rotation():
    origin = GpsOrigin(latitude=45.064312, longitude=7.659154)
    x, z = 12.5, 47.0
    lat, lon = local_to_gps(x, z, origin)
    x2, z2 = gps_to_local(lat, lon, origin)
    assert math.isclose(x, x2, abs_tol=1e-6)
    assert math.isclose(z, z2, abs_tol=1e-6)


def test_roundtrip_local_gps_local_with_rotation():
    origin = GpsOrigin(latitude=45.064312, longitude=7.659154, azimuth_deg=37.5)
    x, z = 8.3, -21.4
    lat, lon = local_to_gps(x, z, origin)
    x2, z2 = gps_to_local(lat, lon, origin)
    assert math.isclose(x, x2, abs_tol=1e-6)
    assert math.isclose(z, z2, abs_tol=1e-6)


def test_rotation_preserves_distance():
    """Rotating the local frame should not change the radial distance of a point
    from the origin (rotation is a rigid transformation)."""
    plain = GpsOrigin(latitude=45.0, longitude=7.0)
    rotated = GpsOrigin(latitude=45.0, longitude=7.0, azimuth_deg=42.0)

    p_lat, p_lon = local_to_gps(30.0, 40.0, plain)        # 50 m at bearing
    r_lat, r_lon = local_to_gps(30.0, 40.0, rotated)

    def dist_m(lat, lon):
        d_lat = (lat - 45.0) * 111_320.0
        d_lon = (lon - 7.0) * 111_320.0 * math.cos(math.radians(45.0))
        return math.hypot(d_lat, d_lon)

    assert math.isclose(dist_m(p_lat, p_lon), dist_m(r_lat, r_lon), abs_tol=1e-6)


def test_altitude_field_round_trips_through_model():
    origin = GpsOrigin(latitude=45.0, longitude=7.0, altitude_m=237.5)
    assert origin.altitude_m == 237.5
