import httpx
import pytest

ROLE = "camara-location-read"
PATH = "/assets/discoverable"


@pytest.fixture
def auth_headers(make_token):
    return {"Authorization": f"Bearer {make_token(roles=[ROLE])}"}


async def test_discoverable_requires_auth(client):
    resp = await client.get(PATH)
    assert resp.status_code == 401


async def test_discoverable_subtracts_onboarded(client, respx_mock, auth_headers, monkeypatch):
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://engine.test/devices").mock(
        return_value=httpx.Response(200, json={
            "devices": [
                # wittra-tag-01 is already onboarded in the seed map -> excluded
                {"id": "wittra-tag-01", "source": "wittra", "origin": "inventory"},
                {"id": "D002", "source": "wittra", "origin": "inventory", "label": "Tag 2",
                 "role": "infrastructure", "source_class": "uwb"},
                {"id": "wifi-new", "source": "wifi", "origin": "observed",
                 "last_seen": 12.0, "role": "asset", "source_class": "wifi"},
            ]
        })
    )
    resp = await client.get(PATH, headers=auth_headers)
    assert resp.status_code == 200
    cands = {c["id"]: c for c in resp.json()["candidates"]}
    assert set(cands) == {"D002", "wifi-new"}  # onboarded id subtracted
    assert cands["wifi-new"]["origin"] == "observed"
    assert cands["wifi-new"]["source"] == "wifi"
    assert cands["wifi-new"]["role"] == "asset"
    assert cands["wifi-new"]["source_class"] == "wifi"
    assert cands["D002"]["label"] == "Tag 2"
    # role + source_class pass through so KELT separates infrastructure + badges tech.
    assert cands["D002"]["role"] == "infrastructure"
    assert cands["D002"]["source_class"] == "uwb"


async def test_discoverable_empty_when_engine_absent(client, auth_headers, monkeypatch):
    monkeypatch.delenv("POSITIONING_ENGINE_URL", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    resp = await client.get(PATH, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"candidates": []}
