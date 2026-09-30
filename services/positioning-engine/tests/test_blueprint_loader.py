import json

from httpx import ASGITransport, AsyncClient

from app.blueprint import floor_plan_from_blueprint, load_blueprint, save_blueprint
from app.main import app


def test_floor_plan_from_a_v3_blueprint():
    raw = {
        "version": 3,
        "floor_plans": [
            {"id": "fp", "label": "6th floor", "georef": {
                "latitude": 59.4042, "longitude": 17.9492,
                "azimuth_deg": -36.4, "altitude_m": 31.0, "width_m": 40, "depth_m": 30}}
        ],
        "rooms": [{"id": "r1", "floor_plan_id": "fp", "x_m": 4, "y_m": 16, "width_m": 10,
                   "depth_m": 8, "rotation_deg": 15}],
    }
    fp = floor_plan_from_blueprint(raw)
    assert fp.gps_origin.latitude == 59.4042
    assert fp.gps_origin.azimuth_deg == -36.4
    assert fp.gps_origin.altitude_m == 31.0
    assert (fp.width_m, fp.depth_m) == (40, 30)
    assert fp.rooms["r1"].y_m == 16 and fp.rooms["r1"].rotation_deg == 15


def test_no_georef_yields_none_origin_not_crash():
    room = {"id": "r", "x_m": 0, "y_m": 0, "width_m": 10, "depth_m": 10}
    fp = floor_plan_from_blueprint({"version": 3, "rooms": [room]})
    assert fp.gps_origin is None
    assert "r" in fp.rooms
    assert fp.rooms["r"].rotation_deg == 0.0


def test_a_georef_without_its_bearing_is_no_georeference():
    georef = {"latitude": 59.4042, "longitude": 17.9492, "width_m": 40, "depth_m": 30}
    fp = floor_plan_from_blueprint({"version": 3, "floor_plans": [{"id": "fp", "georef": georef}], "rooms": []})
    assert fp.gps_origin is None
    georef["azimuth_deg"] = 0
    assert floor_plan_from_blueprint(
        {"version": 3, "floor_plans": [{"id": "fp", "georef": georef}], "rooms": []}
    ).gps_origin is not None


def test_a_room_that_is_not_placed_is_skipped():
    fp = floor_plan_from_blueprint({"version": 3, "rooms": [{"id": "r", "width_m": 10, "depth_m": 10}]})
    assert "r" not in fp.rooms


def test_a_stored_v2_blueprint_is_migrated_and_persisted_once(tmp_path):
    store = tmp_path / "blueprint.json"
    store.write_text(json.dumps({"version": 2, "floor_plans": [{"id": "fp", "georef": {
        "latitude": 59.4, "longitude": 17.9, "width_m": 10, "height_m": 20}}],
        "rooms": [{"id": "r", "floor_plan_id": "fp", "x_m": 0, "y_m": 0, "width_m": 5, "height_m": 4}]}))
    raw = load_blueprint(str(store), "")
    assert raw["version"] == 3
    assert raw["rooms"][0]["y_m"] == 16.0
    assert json.loads(store.read_text())["version"] == 3


def test_load_seeds_from_seed_path_then_persists(tmp_path):
    store = tmp_path / "blueprint.json"
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"version": 3, "floor_plans": [{"georef": {"latitude": 1.0, "longitude": 2.0}}], "rooms": []}))
    raw = load_blueprint(str(store), str(seed))
    assert raw["floor_plans"][0]["georef"]["latitude"] == 1.0
    # seed migrated into the persisted store
    assert store.is_file()
    assert json.loads(store.read_text())["floor_plans"][0]["georef"]["longitude"] == 2.0


def test_load_returns_none_when_nothing(tmp_path):
    assert load_blueprint(str(tmp_path / "absent.json"), "") is None


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_get_blueprint_404_when_absent():
    app.state.blueprint = None
    async with await _client() as c:
        r = await c.get("/blueprint")
    assert r.status_code == 404


async def test_put_then_get_roundtrip(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config.settings, "blueprint_path", str(tmp_path / "bp.json"))
    # A client still writing version 2 is migrated on PUT.
    body = {"version": 2,
            "floor_plans": [{"georef": {"latitude": 59.4, "longitude": 17.9, "azimuth_deg": -36.0}}],
            "rooms": [{"x_m": 0, "y_m": 0, "width_m": 13, "height_m": 32}]}
    async with await _client() as c:
        put = await c.put("/blueprint", json=body)
        assert put.status_code == 200
        assert put.json()["gps_origin"] == "set"
        got = await c.get("/blueprint")
    assert got.status_code == 200
    assert got.json()["floor_plans"][0]["georef"]["latitude"] == 59.4
    assert got.json()["version"] == 3
    assert got.json()["rooms"][0]["depth_m"] == 32
    assert (tmp_path / "bp.json").is_file()
