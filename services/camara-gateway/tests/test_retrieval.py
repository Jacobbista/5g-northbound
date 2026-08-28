from datetime import datetime, timezone

import httpx
import pytest

ROLE = "camara-location-read"
RETRIEVE = "/location-retrieval/v0.5/retrieve"

# asset_id tool-880 -> positioning_id wifi-asset-01 (see conftest _TEST_ASSETS).
ASSET = {"assetId": "tool-880"}


@pytest.fixture
def auth_headers(make_token):
    return {"Authorization": f"Bearer {make_token(roles=[ROLE])}"}


async def test_retrieve_fuses_multi_capability(client, respx_mock, auth_headers, monkeypatch):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings
    get_settings.cache_clear()

    amap = {"version": 3, "assets": [
        {"asset_id": "robot-9", "kind": "forklift", "org": "acme",
         "capabilities": [{"source": "wifi", "positioning_id": "wifi-9"},
                          {"source": "wittra", "positioning_id": "uwb-9"}]}]}
    put = await client.put("/assets", json=amap, headers=auth_headers)
    assert put.status_code == 200

    respx_mock.get("http://engine.test/position/wifi-9?source=wifi").mock(
        return_value=httpx.Response(200, json={
            "device_id": "wifi-9", "latitude": 0.0, "longitude": 0.0,
            "accuracy_m": 3.0, "timestamp": "2026-01-01T00:00:00+00:00"}))
    respx_mock.get("http://engine.test/position/uwb-9?source=wittra").mock(
        return_value=httpx.Response(200, json={
            "device_id": "uwb-9", "latitude": 1.0, "longitude": 1.0,
            "accuracy_m": 0.5, "timestamp": "2026-01-01T00:00:05+00:00"}))

    r = await client.post(RETRIEVE, json={"device": {"assetId": "robot-9"}}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    # inverse-variance fusion pulls the fix toward the sharp UWB estimate...
    assert body["area"]["center"]["latitude"] > 0.9
    # ...and the fused radius is tighter than the best single input (0.5 m).
    assert body["area"]["radius"] < 0.5 or body["area"]["radius"] == 1.0  # CAMARA floors radius at 1 m


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
    body = {"device": {"networkAccessIdentifier": "tool-880@acme.assets"}}
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


async def test_retrieve_422_unable_to_locate_when_engine_has_no_fix(
    client, respx_mock, auth_headers, monkeypatch
):
    """Engine 404 ("no measurements") surfaces as the CAMARA
    LOCATION_RETRIEVAL.UNABLE_TO_LOCATE (422), not as the mock fallback."""
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        return_value=httpx.Response(404, json={"detail": "no fix"})
    )
    resp = await client.post(RETRIEVE, json={"device": ASSET}, headers=auth_headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "LOCATION_RETRIEVAL.UNABLE_TO_LOCATE"


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
    assert resp.json()["code"] == "UNAVAILABLE"


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
    assert resp.status_code == 422  # UNABLE_TO_LOCATE, not retried
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


def _engine_ok_fresh():
    body = _engine_ok().json()
    body["timestamp"] = datetime.now(timezone.utc).isoformat()
    return httpx.Response(200, json=body)


# --- maxAge freshness contract + cache ---


async def test_retrieve_serves_from_cache_within_ttl(
    client, respx_mock, auth_headers, monkeypatch
):
    """A second call within the freshness bound reuses the cached fix instead of
    calling the engine again."""
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    route = respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        return_value=_engine_ok_fresh()
    )
    r1 = await client.post(RETRIEVE, json={"device": ASSET, "maxAge": 60}, headers=auth_headers)
    r2 = await client.post(RETRIEVE, json={"device": ASSET, "maxAge": 60}, headers=auth_headers)
    assert r1.status_code == r2.status_code == 200
    assert route.call_count == 1  # second request served from cache


async def test_retrieve_maxage_zero_bypasses_cache(
    client, respx_mock, auth_headers, monkeypatch
):
    """maxAge=0 requests a fresh calculation, so the cache is bypassed."""
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    route = respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        return_value=_engine_ok_fresh()
    )
    await client.post(RETRIEVE, json={"device": ASSET, "maxAge": 0}, headers=auth_headers)
    await client.post(RETRIEVE, json={"device": ASSET, "maxAge": 0}, headers=auth_headers)
    assert route.call_count == 2  # each call fetches fresh


async def test_retrieve_maxage_unfulfillable_422(
    client, respx_mock, auth_headers, monkeypatch
):
    """A fix older than the requested maxAge cannot be fulfilled."""
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        return_value=_engine_ok()  # timestamp far older than maxAge
    )
    resp = await client.post(
        RETRIEVE, json={"device": ASSET, "maxAge": 120}, headers=auth_headers
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "LOCATION_RETRIEVAL.UNABLE_TO_FULFILL_MAX_AGE"


# --- identity + maxSurface ---


async def test_retrieve_public_identifier_422(client, auth_headers):
    """A public-network identifier is rejected with UNSUPPORTED_IDENTIFIER."""
    resp = await client.post(
        RETRIEVE, json={"device": {"phoneNumber": "+123456789"}}, headers=auth_headers
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "UNSUPPORTED_IDENTIFIER"


async def test_retrieve_maxsurface_unfulfillable_422(client, auth_headers):
    """The mock ~50 m radius yields an area (~7854 m2) larger than a tight
    maxSurface -> 422."""
    resp = await client.post(
        RETRIEVE, json={"device": ASSET, "maxSurface": 100}, headers=auth_headers
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "LOCATION_RETRIEVAL.UNABLE_TO_FULFILL_MAX_SURFACE"


async def test_retrieve_maxsurface_ok(client, auth_headers, location_validator):
    """A generous maxSurface is satisfied by the mock fix."""
    resp = await client.post(
        RETRIEVE, json={"device": ASSET, "maxSurface": 1000000}, headers=auth_headers
    )
    assert resp.status_code == 200
    location_validator.validate(resp.json())
