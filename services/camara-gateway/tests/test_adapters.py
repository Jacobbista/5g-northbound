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
async def test_adapters_proxies_engine_response(client, make_token, monkeypatch, respx_mock):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://engine.test/adapters").mock(
        return_value=httpx.Response(200, json={
            "adapters": [
                {
                    "name": "wifi",
                    "base_url": "http://wifi-adapter:8080",
                    "fail_count": 0,
                    "in_cooldown": False,
                    "cooldown_seconds_remaining": 0.0,
                },
                {
                    "name": "wittra",
                    "base_url": "https://api.wittra.example.com",
                    "fail_count": 5,
                    "in_cooldown": True,
                    "cooldown_seconds_remaining": 8.0,
                },
            ]
        })
    )

    token = make_token(roles=["camara-location-read"])
    r = await client.get("/adapters", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert {a["name"] for a in body["adapters"]} == {"wifi", "wittra"}
    wittra = next(a for a in body["adapters"] if a["name"] == "wittra")
    assert wittra["in_cooldown"] is True
    assert wittra["fail_count"] == 5


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
