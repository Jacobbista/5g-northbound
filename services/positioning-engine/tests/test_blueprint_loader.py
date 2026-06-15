from app.main import _floor_plan_from_blueprint


def test_gps_origin_from_floor_plan_georef():
    raw = {
        "floor_plans": [
            {"label": "6th floor", "georef": {
                "latitude": 59.4042, "longitude": 17.9492,
                "azimuth_deg": -36.4, "altitude_m": 0, "width_m": 40, "height_m": 40}}
        ],
        "rooms": [{"width_m": 13, "height_m": 32}],
    }
    fp = _floor_plan_from_blueprint(raw)
    assert fp.gps_origin is not None
    assert fp.gps_origin.latitude == 59.4042
    assert fp.gps_origin.azimuth_deg == -36.4
    assert fp.floors[0].width_m == 40 and fp.floors[0].depth_m == 40
    assert fp.floors[0].label == "6th floor"


def test_falls_back_to_legacy_top_level_gps_origin():
    raw = {"gps_origin": {"latitude": 45.0, "longitude": 7.0, "azimuth_deg": 0},
           "rooms": [{"width_m": 13, "height_m": 32}]}
    fp = _floor_plan_from_blueprint(raw)
    assert fp.gps_origin.latitude == 45.0
    # no floor_plans -> floor dims come from the first room
    assert fp.floors[0].width_m == 13 and fp.floors[0].depth_m == 32


def test_no_georef_yields_none_origin_not_crash():
    fp = _floor_plan_from_blueprint({"rooms": [{"width_m": 10, "height_m": 10}]})
    assert fp.gps_origin is None
    assert fp.floors[0].width_m == 10
