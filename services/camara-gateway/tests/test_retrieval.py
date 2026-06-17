import httpx
import pytest

ROLE = "camara-location-read"
RETRIEVE = "/location-retrieval/v0.5/retrieve"

# asset_id tool-880 -> positioning_id wifi-asset-01 (see conftest _TEST_ASSETS).
ASSET = {"assetId": "tool-880"}


@pytest.fixture
def auth_headers(make_token):
    return {"Authorization": f"Bearer {make_token(roles=[ROLE])}"}


async def test_retrieve_returns_spec_shaped_circle(client, auth_headers, location_validator):
    resp = await client.post(RETRIEVE, json={"device": ASSET}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["area"]["areaType"] == "CIRCLE"
    assert body["area"]["radius"] >= 1
    assert "lastLocationTime" in body
    # Private-asset profile extensions.
    assert body["source"] == "wifi"
    assert body["kind"] == "tool"
    location_validator.validate(body)


async def test_retrieve_via_nai_asset_alias(client, auth_headers, location_validator):
    """networkAccessIdentifier as the `<asset_id>@<org>.assets` alias resolves."""
    body = {"device": {"networkAccessIdentifier": "tool-880@fiskarheden.assets"}}
    resp = await client.post(RETRIEVE, json=body, headers=auth_headers)
    assert resp.status_code == 200
    location_validator.validate(resp.json())


async def test_retrieve_missing_identifier_422(client, auth_headers):
    resp = await client.post(RETRIEVE, json={"maxAge": 120}, headers=auth_headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "MISSING_IDENTIFIER"


async def test_retrieve_invalid_asset_id_400(client, auth_headers):
    # space violates the assetId pattern -> request validation error -> 400.
    resp = await client.post(RETRIEVE, json={"device": {"assetId": "bad id"}}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_ARGUMENT"


async def test_retrieve_unknown_asset_404(client, auth_headers):
    resp = await client.post(RETRIEVE, json={"device": {"assetId": "nope-999"}}, headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "IDENTIFIER_NOT_FOUND"


async def test_retrieve_404_when_engine_has_no_fix(
    client, respx_mock, auth_headers, monkeypatch
):
    """Engine 404 ("no measurements") must surface as a NOT_FOUND CAMARA
    error rather than being papered over by the gateway's mock fallback."""
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        return_value=httpx.Response(404, json={"detail": "no fix"})
    )
    resp = await client.post(RETRIEVE, json={"device": ASSET}, headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


async def test_retrieve_503_when_engine_unreachable(
    client, respx_mock, auth_headers, monkeypatch
):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        side_effect=httpx.ConnectError("down")
    )
    resp = await client.post(RETRIEVE, json={"device": ASSET}, headers=auth_headers)
    assert resp.status_code == 503
    assert resp.json()["code"] == "SERVICE_UNAVAILABLE"


def _engine_ok():
    return httpx.Response(200, json={
        "device_id": "wifi-asset-01",
        "latitude": 45.064312,
        "longitude": 7.659154,
        "accuracy_m": 1.5,
        "timestamp": "2026-06-03T14:36:17+00:00",
        "sources": ["wifi"],
        "strategy": "weighted_avg",
    })


async def test_retrieve_retries_once_on_engine_5xx_then_succeeds(
    client, respx_mock, auth_headers, monkeypatch
):
    """Transient engine 5xx (pod restart, brief crash) recovers within one retry."""
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    route = respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        side_effect=[httpx.Response(503, json={"detail": "starting up"}), _engine_ok()]
    )
    resp = await client.post(RETRIEVE, json={"device": ASSET}, headers=auth_headers)
    assert resp.status_code == 200
    assert route.call_count == 2  # the initial 503 + the successful retry


async def test_retrieve_502_when_engine_5xx_persists(
    client, respx_mock, auth_headers, monkeypatch
):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    route = respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        return_value=httpx.Response(500, json={"detail": "boom"})
    )
    resp = await client.post(RETRIEVE, json={"device": ASSET}, headers=auth_headers)
    assert resp.status_code == 502
    assert resp.json()["code"] == "BAD_GATEWAY"
    assert route.call_count == 2  # initial attempt + one retry, then gives up


async def test_retrieve_does_not_retry_on_engine_404(
    client, respx_mock, auth_headers, monkeypatch
):
    """404 is a legitimate 'no fix' - retrying would only delay the response."""
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    route = respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        return_value=httpx.Response(404, json={"detail": "no fix"})
    )
    resp = await client.post(RETRIEVE, json={"device": ASSET}, headers=auth_headers)
    assert resp.status_code == 404
    assert route.call_count == 1


async def test_retrieve_retries_once_on_network_error_then_succeeds(
    client, respx_mock, auth_headers, monkeypatch
):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    route = respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        side_effect=[httpx.ConnectError("transient"), _engine_ok()]
    )
    resp = await client.post(RETRIEVE, json={"device": ASSET}, headers=auth_headers)
    assert resp.status_code == 200
    assert route.call_count == 2
