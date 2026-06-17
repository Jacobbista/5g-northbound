import base64

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _basic(user: str, pwd: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()


_TELEMETRY = "/v4/organizations/demo-org/projects/demo-prj/devices/wittra-tag-01/telemetry"
_LIST = "/v4/organizations/demo-org/projects/demo-prj/devices"


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200


async def test_telemetry_unauthorised_without_auth(client):
    r = await client.get(_TELEMETRY)
    assert r.status_code == 401


async def test_telemetry_unauthorised_with_wrong_credentials(client):
    r = await client.get(_TELEMETRY, headers={"Authorization": _basic("demo-org", "wrong")})
    assert r.status_code == 401


async def test_telemetry_unknown_org_returns_404(client):
    r = await client.get(
        "/v4/organizations/other-org/projects/demo-prj/devices/wittra-tag-01/telemetry",
        headers={"Authorization": _basic("demo-org", "demo-key")},
    )
    assert r.status_code == 404


async def test_telemetry_unknown_device_returns_404(client):
    r = await client.get(
        "/v4/organizations/demo-org/projects/demo-prj/devices/unknown/telemetry",
        headers={"Authorization": _basic("demo-org", "demo-key")},
    )
    assert r.status_code == 404


async def test_telemetry_returns_wittra_v4_shape(client):
    r = await client.get(_TELEMETRY, headers={"Authorization": _basic("demo-org", "demo-key")})
    assert r.status_code == 200
    body = r.json()
    assert body["deviceId"] == "wittra-tag-01"
    loc = body["location"]
    val = loc["value"]
    assert isinstance(val["latitude"], float)
    assert isinstance(val["longitude"], float)
    assert "timestamp" in loc


async def test_list_devices_returns_raw_array(client):
    r = await client.get(_LIST, headers={"Authorization": _basic("demo-org", "demo-key")})
    assert r.status_code == 200
    body = r.json()
    # Wittra v4 returns the device array directly, no envelope: two fixed
    # beacons (fixedLocation set) + one mobile tag (fixedLocation None), so a
    # discover consumer can tell anchors from tags.
    assert isinstance(body, list)
    assert len(body) == 3
    by_id = {d["deviceId"]: d for d in body}
    assert set(by_id) == {"wittra-tag-01", "wittra-tag-02", "D00124B00249TAG01"}
    assert by_id["wittra-tag-01"]["fixedLocation"]["latitude"] is not None
    assert by_id["D00124B00249TAG01"]["fixedLocation"] is None


async def test_list_devices_unauthorised(client):
    r = await client.get(_LIST)
    assert r.status_code == 401
