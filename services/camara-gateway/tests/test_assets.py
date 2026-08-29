import httpx
import pytest

ROLE = "camara-location-read"
ASSETS = "/assets"


@pytest.fixture
def auth_headers(make_token):
    return {"Authorization": f"Bearer {make_token(roles=[ROLE])}"}


async def test_assets_requires_auth(client):
    resp = await client.get(ASSETS)
    assert resp.status_code == 401


async def test_get_assets_lists_seeded_map(client, auth_headers):
    resp = await client.get(ASSETS, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 3
    ids = {a["asset_id"] for a in body["assets"]}
    assert ids == {"tool-880", "forklift-7", "pkg-4471"}
    by_id = {a["asset_id"]: a for a in body["assets"]}
    assert by_id["pkg-4471"]["capabilities"][0]["positioning_id"] == "wittra-tag-01"
    assert by_id["pkg-4471"]["org"] == "acme"
    assert "simulated" not in by_id["forklift-7"]


async def test_put_assets_replaces_map(client, auth_headers):
    new_map = {
        "version": 3,
        "assets": [
            {"asset_id": "drill-1", "kind": "tool", "org": "atlas", "label": "Drill 1",
             "capabilities": [{"source": "wifi", "positioning_id": "wifi-asset-01"}]},
        ],
    }
    put = await client.put(ASSETS, json=new_map, headers=auth_headers)
    assert put.status_code == 200

    got = await client.get(ASSETS, headers=auth_headers)
    ids = {a["asset_id"] for a in got.json()["assets"]}
    assert ids == {"drill-1"}


async def test_details_joins_engine_telemetry(client, respx_mock, auth_headers, monkeypatch):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://engine.test/position/wittra-tag-01").mock(
        return_value=httpx.Response(200, json={
            "device_id": "wittra-tag-01",
            "latitude": 45.064,
            "longitude": 7.659,
            "accuracy_m": 0.85,
            "altitude_m": 1.2,
            "timestamp": "2026-06-03T12:00:00+00:00",
            "sources": ["wittra"],
            "strategy": "weighted_avg",
        })
    )
    resp = await client.get(f"{ASSETS}/pkg-4471/details", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["asset_id"] == "pkg-4471"
    assert body["kind"] == "pallet"
    assert body["telemetry"]["sources"] == ["wittra"]
    assert body["telemetry"]["altitude"] == 1.2


async def test_details_fuses_multi_capability(client, respx_mock, auth_headers, monkeypatch):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings
    get_settings.cache_clear()

    amap = {"version": 3, "assets": [
        {"asset_id": "robot-9", "kind": "forklift", "org": "acme",
         "capabilities": [{"source": "wifi", "positioning_id": "wifi-9"},
                          {"source": "wittra", "positioning_id": "uwb-9"}]}]}
    assert (await client.put("/assets", json=amap, headers=auth_headers)).status_code == 200

    respx_mock.get("http://engine.test/position/wifi-9?source=wifi").mock(
        return_value=httpx.Response(200, json={
            "device_id": "wifi-9", "latitude": 0.0, "longitude": 0.0, "accuracy_m": 3.0,
            "timestamp": "2026-01-01T00:00:00+00:00", "sources": ["wifi"]}))
    respx_mock.get("http://engine.test/position/uwb-9?source=wittra").mock(
        return_value=httpx.Response(200, json={
            "device_id": "uwb-9", "latitude": 1.0, "longitude": 1.0, "accuracy_m": 0.5,
            "timestamp": "2026-01-01T00:00:05+00:00", "sources": ["wittra"]}))

    resp = await client.get(f"{ASSETS}/robot-9/details", headers=auth_headers)
    assert resp.status_code == 200
    tele = resp.json()["telemetry"]
    assert set(tele["sources"]) == {"wifi", "wittra"}  # fused side-panel shows both
    assert tele["latitude"] > 0.9  # pulled toward the sharp UWB fix


async def test_details_404_for_unknown_asset(client, auth_headers):
    resp = await client.get(f"{ASSETS}/nope-999/details", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "IDENTIFIER_NOT_FOUND"


async def test_details_telemetry_null_when_engine_unreachable(
    client, respx_mock, auth_headers, monkeypatch
):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        side_effect=httpx.ConnectError("nope")
    )
    resp = await client.get(f"{ASSETS}/tool-880/details", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["telemetry"] is None
