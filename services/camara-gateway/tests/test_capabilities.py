import httpx
import pytest

ROLE = "camara-location-read"


@pytest.fixture
def auth_headers(make_token):
    return {"Authorization": f"Bearer {make_token(roles=[ROLE])}"}


@pytest.mark.parametrize("declared, expected", [
    ({"z": True}, True),
    ({"z": False}, False),
    ({}, False),
])
async def test_altitude_follows_the_declared_height_capability(
    client, respx_mock, auth_headers, monkeypatch, declared, expected
):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()
    respx_mock.get("http://engine.test/adapters").mock(return_value=httpx.Response(200, json={
        "adapters": [{"name": "a", "state": "live", "capabilities": {"source": "a", **declared}}],
    }))
    r = await client.get("/capabilities", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["altitude"] is expected


async def test_kinds_come_from_the_asset_map_only(client, respx_mock, auth_headers, monkeypatch):
    # An adapter from before 0.21.0 still announces `kinds`. It names no asset.
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()
    respx_mock.get("http://engine.test/adapters").mock(return_value=httpx.Response(200, json={
        "adapters": [{"name": "a", "state": "live", "capabilities": {"source": "a", "kinds": ["uwb-tag"]}}],
    }))
    body = (await client.get("/capabilities", headers=auth_headers)).json()
    assert "uwb-tag" not in body["kinds"]
    assert "kinds" not in body["adapters"][0]["capabilities"]
