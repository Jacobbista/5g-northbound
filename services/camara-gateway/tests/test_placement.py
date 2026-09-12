"""Placing a synthetic asset, through the gateway's asset-shaped surface."""

import httpx
import pytest

ROLE = "camara-location-read"
# `forklift-7` is the seeded synthetic asset; `pkg-4471` is the wittra one.
SYNTHETIC = "/assets/forklift-7/placement"
REAL = "/assets/pkg-4471/placement"


@pytest.fixture
def auth_headers(make_token):
    return {"Authorization": f"Bearer {make_token(roles=[ROLE])}"}


@pytest.fixture
def fabric(respx_mock, monkeypatch):
    """A stub engine advertising one placeable source and one that is not."""
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()
    respx_mock.get("http://engine.test/adapters").mock(
        return_value=httpx.Response(200, json={"adapters": [
            {"name": "synthetic", "baseUrl": "http://synthetic.test",
             "capabilities": {"source": "synthetic", "placement": True}},
            {"name": "wittra", "baseUrl": "http://wittra.test",
             "capabilities": {"source": "wittra"}},
        ]})
    )
    return respx_mock


async def test_placing_an_asset_reaches_its_source_by_positioning_id(client, auth_headers, fabric):
    # The caller names an asset. The positioning id is the gateway's business
    # and never appears in the request or the response.
    route = fabric.put("http://synthetic.test/devices/synthetic-demo-01/placement").mock(
        return_value=httpx.Response(200, json={"id": "synthetic-demo-01", "x": 4.0, "z": 9.0, "placed": True})
    )
    r = await client.put(SYNTHETIC, json={"x": 4.0, "z": 9.0}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"assetId": "forklift-7", "x": 4.0, "z": 9.0, "placed": True}
    assert route.called
    assert route.calls[0].request.read() == b'{"x":4.0,"z":9.0}'


async def test_removing_an_asset_takes_it_off_the_floor(client, auth_headers, fabric):
    fabric.delete("http://synthetic.test/devices/synthetic-demo-01/placement").mock(
        return_value=httpx.Response(200, json={"id": "synthetic-demo-01", "x": 0.0, "z": 0.0, "placed": False})
    )
    r = await client.delete(SYNTHETIC, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["placed"] is False


async def test_a_measured_source_cannot_be_placed(client, auth_headers, fabric):
    # Refused here, where the reason is known, rather than 404ing inside an
    # adapter that has no such endpoint.
    r = await client.put(REAL, json={"x": 1.0, "z": 1.0}, headers=auth_headers)
    assert r.status_code == 422
    assert r.json()["code"] == "NOT_PLACEABLE"


async def test_placing_an_unknown_asset_is_not_found(client, auth_headers, fabric):
    r = await client.put("/assets/nope/placement", json={"x": 1.0, "z": 1.0}, headers=auth_headers)
    assert r.status_code == 404


async def test_placement_requires_auth(client, fabric):
    r = await client.put(SYNTHETIC, json={"x": 1.0, "z": 1.0})
    assert r.status_code == 401


async def test_an_unreachable_fabric_is_reported_as_unavailable(client, auth_headers, respx_mock, monkeypatch):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()
    respx_mock.get("http://engine.test/adapters").mock(side_effect=httpx.ConnectError("down"))
    r = await client.put(SYNTHETIC, json={"x": 1.0, "z": 1.0}, headers=auth_headers)
    assert r.status_code == 503
