import json
from urllib.parse import quote

import httpx
import pytest
import respx

ROLE = "camara-location-read"
DEVICES = "/devices"


@pytest.fixture
def auth_headers(make_token):
    return {"Authorization": f"Bearer {make_token(roles=[ROLE])}"}


async def test_devices_requires_auth(client):
    resp = await client.get(DEVICES)
    assert resp.status_code == 401


async def test_devices_from_env_fallback(client, auth_headers, monkeypatch):
    monkeypatch.setenv(
        "DEVICE_REGISTRY",
        json.dumps({"+390111234567": "wifi-asset-01", "+390117654321": "mock-demo-01"}),
    )
    monkeypatch.setenv("DEVICE_REGISTRY_FILE", "")
    from app.config import get_settings

    get_settings.cache_clear()

    resp = await client.get(DEVICES, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    ids = {d["deviceId"] for d in body["devices"]}
    assert ids == {"wifi-asset-01", "mock-demo-01"}
    # label defaults to deviceId when only env map is present
    for d in body["devices"]:
        assert d["label"] == d["deviceId"]


async def test_devices_from_file_with_labels(client, auth_headers, monkeypatch, tmp_path):
    f = tmp_path / "devices.json"
    f.write_text(
        json.dumps(
            {
                "devices": [
                    {
                        "phoneNumber": "+390111234567",
                        "deviceId": "wifi-asset-01",
                        "label": "WiFi asset 01",
                    },
                    {
                        "phoneNumber": "+390117654321",
                        "deviceId": "mock-demo-01",
                        "label": "Mock demo 01",
                    },
                ]
            }
        )
    )
    monkeypatch.setenv("DEVICE_REGISTRY_FILE", str(f))
    from app.config import get_settings

    get_settings.cache_clear()

    resp = await client.get(DEVICES, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    by_id = {d["deviceId"]: d["label"] for d in body["devices"]}
    assert by_id == {"wifi-asset-01": "WiFi asset 01", "mock-demo-01": "Mock demo 01"}


async def test_devices_file_unreadable_falls_back_to_env(client, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_REGISTRY_FILE", str(tmp_path / "missing.json"))
    monkeypatch.setenv("DEVICE_REGISTRY", json.dumps({"+390111234567": "wifi-asset-01"}))
    from app.config import get_settings

    get_settings.cache_clear()

    resp = await client.get(DEVICES, headers=auth_headers)
    assert resp.status_code == 200
    ids = [d["deviceId"] for d in resp.json()["devices"]]
    assert ids == ["wifi-asset-01"]


async def test_devices_empty_when_no_config(client, auth_headers, monkeypatch):
    monkeypatch.setenv("DEVICE_REGISTRY", "{}")
    monkeypatch.setenv("DEVICE_REGISTRY_FILE", "")
    from app.config import get_settings

    get_settings.cache_clear()

    resp = await client.get(DEVICES, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"devices": []}


async def test_devices_simulated_flag_propagates(client, auth_headers, monkeypatch, tmp_path):
    """`simulated: true` on a registry entry surfaces in /devices so the UI
    can render a 'MOCK' badge for fixture-backed devices."""
    f = tmp_path / "devices.json"
    f.write_text(
        json.dumps(
            {
                "devices": [
                    {"phoneNumber": "+39001", "deviceId": "wifi-asset-01", "label": "Real"},
                    {"phoneNumber": "+39002", "deviceId": "mock-demo-01",  "label": "Mock", "simulated": True},
                ]
            }
        )
    )
    monkeypatch.setenv("DEVICE_REGISTRY_FILE", str(f))
    from app.config import get_settings

    get_settings.cache_clear()

    resp = await client.get(DEVICES, headers=auth_headers)
    assert resp.status_code == 200
    by_id = {d["deviceId"]: d for d in resp.json()["devices"]}
    assert by_id["wifi-asset-01"]["simulated"] is False
    assert by_id["mock-demo-01"]["simulated"] is True


async def test_devices_simulated_defaults_to_false_when_absent(
    client, auth_headers, monkeypatch, tmp_path
):
    f = tmp_path / "devices.json"
    f.write_text(
        json.dumps(
            {"devices": [{"phoneNumber": "+39001", "deviceId": "x", "label": "X"}]}
        )
    )
    monkeypatch.setenv("DEVICE_REGISTRY_FILE", str(f))
    from app.config import get_settings

    get_settings.cache_clear()

    resp = await client.get(DEVICES, headers=auth_headers)
    assert resp.json()["devices"][0]["simulated"] is False


# --- /devices/{phoneNumber}/details ---


def _details_url(phone: str) -> str:
    return f"{DEVICES}/{quote(phone, safe='')}/details"


async def test_details_returns_full_engine_payload(client, respx_mock, auth_headers, monkeypatch):
    monkeypatch.setenv(
        "DEVICE_REGISTRY",
        json.dumps({"+390111234567": "wifi-asset-01"}),
    )
    monkeypatch.setenv("DEVICE_REGISTRY_FILE", "")
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    engine_reply = {
        "device_id": "wifi-asset-01",
        "latitude": 45.064,
        "longitude": 7.659,
        "accuracy_m": 2.4,
        "timestamp": "2026-06-03T12:00:00+00:00",
        "sources": ["wifi", "mock"],
        "strategy": "weighted_avg",
    }
    respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        return_value=httpx.Response(200, json=engine_reply)
    )
    resp = await client.get(_details_url("+390111234567"), headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["deviceId"] == "wifi-asset-01"
    assert body["telemetry"]["sources"] == ["wifi", "mock"]
    assert body["telemetry"]["strategy"] == "weighted_avg"
    assert body["telemetry"]["accuracy_m"] == 2.4


async def test_details_404_when_phone_not_registered(client, auth_headers, monkeypatch):
    monkeypatch.setenv("DEVICE_REGISTRY", "{}")
    monkeypatch.setenv("DEVICE_REGISTRY_FILE", "")
    from app.config import get_settings

    get_settings.cache_clear()

    resp = await client.get(_details_url("+390999000000"), headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == "IDENTIFIER_NOT_FOUND"


async def test_details_telemetry_null_when_engine_unreachable(client, respx_mock, auth_headers, monkeypatch):
    monkeypatch.setenv(
        "DEVICE_REGISTRY",
        json.dumps({"+390111234567": "wifi-asset-01"}),
    )
    monkeypatch.setenv("DEVICE_REGISTRY_FILE", "")
    monkeypatch.setenv("POSITIONING_ENGINE_URL", "http://engine.test")
    from app.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://engine.test/position/wifi-asset-01").mock(
        side_effect=httpx.ConnectError("nope")
    )
    resp = await client.get(_details_url("+390111234567"), headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["telemetry"] is None
    assert body["deviceId"] == "wifi-asset-01"


async def test_details_requires_auth(client):
    resp = await client.get(_details_url("+390111234567"))
    assert resp.status_code == 401
