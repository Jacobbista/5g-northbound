import httpx
import pytest


@pytest.mark.asyncio
async def test_adapters_requires_auth(client):
    r = await client.get("/adapters")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_adapters_returns_empty_when_engine_not_configured(client, make_token):
    # POSITIONING_ENGINE_URL is unset in the fixtures -> get_adapter_status() returns None.
    token = make_token(roles=["camara-location-read"])
    r = await client.get("/adapters", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {"adapters": []}


@pytest.mark.asyncio
async def test_adapters_reports_name_state_and_capabilities_only(client, make_token, monkeypatch, respx_mock):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://engine.test/adapters").mock(
        return_value=httpx.Response(200, json={
            "adapters": [
                {"name": "wifi", "baseUrl": "http://wifi-adapter:8080", "failCount": 0,
                 "inCooldown": False, "lastSeenSAgo": 1.2, "state": "live",
                 "capabilities": {"source": "wifi"}},
                {"name": "wittra", "baseUrl": "http://vendor-adapter:8080", "failCount": 5,
                 "inCooldown": True, "lastSeenSAgo": 40.0, "state": "unreachable",
                 "capabilities": {"source": "wittra"}},
            ]
        })
    )

    token = make_token(roles=["camara-location-read"])
    r = await client.get("/adapters", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    # The cluster address and the engine's bookkeeping stay internal.
    assert body["adapters"] == [
        {"name": "wifi", "state": "live", "capabilities": {"source": "wifi"}},
        {"name": "wittra", "state": "unreachable", "capabilities": {"source": "wittra"}},
    ]


@pytest.mark.asyncio
async def test_adapters_returns_empty_when_engine_unreachable(
    client, make_token, monkeypatch, respx_mock
):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.down")
    from app.config import get_settings

    get_settings.cache_clear()
    respx_mock.get("http://engine.down/adapters").mock(side_effect=httpx.ConnectError("down"))

    token = make_token(roles=["camara-location-read"])
    r = await client.get("/adapters", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {"adapters": []}
