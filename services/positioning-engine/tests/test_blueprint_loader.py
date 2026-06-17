import json

from httpx import ASGITransport, AsyncClient

from app.blueprint import floor_plan_from_blueprint, load_blueprint, save_blueprint
from app.main import app


def test_gps_origin_from_floor_plan_georef():
    raw = {
        "floor_plans": [
            {"label": "6th floor", "georef": {
                "latitude": 59.4042, "longitude": 17.9492,
                "azimuth_deg": -36.4, "altitude_m": 0, "width_m": 40, "height_m": 40}}
        ],
        "rooms": [{"width_m": 13, "height_m": 32}],
    }
    fp = floor_plan_from_blueprint(raw)
    assert fp.gps_origin is not None
    assert fp.gps_origin.latitude == 59.4042
    assert fp.gps_origin.azimuth_deg == -36.4
    assert fp.floors[0].width_m == 40 and fp.floors[0].depth_m == 40
    assert fp.floors[0].label == "6th floor"


def test_falls_back_to_legacy_top_level_gps_origin():
    raw = {"gps_origin": {"latitude": 45.0, "longitude": 7.0, "azimuth_deg": 0},
           "rooms": [{"width_m": 13, "height_m": 32}]}
    fp = floor_plan_from_blueprint(raw)
    assert fp.gps_origin.latitude == 45.0
    assert fp.floors[0].width_m == 13 and fp.floors[0].depth_m == 32


def test_no_georef_yields_none_origin_not_crash():
    fp = floor_plan_from_blueprint({"rooms": [{"width_m": 10, "height_m": 10}]})
    assert fp.gps_origin is None
    assert fp.floors[0].width_m == 10


def test_load_seeds_from_seed_path_then_persists(tmp_path):
    store = tmp_path / "blueprint.json"
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"floor_plans": [{"georef": {"latitude": 1.0, "longitude": 2.0}}]}))
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
    assert (tmp_path / "bp.json").is_file()
