import pytest
from httpx import ASGITransport, AsyncClient

from app.models import Measurement, WifiConfig
from app.wifi import WifiAdapter


def test_observed_devices_newest_first():
    a = WifiAdapter(WifiConfig(room_w=10, room_h=10, routers=[]))
    a._cache["d1"] = Measurement(
        source="wifi", x=1.0, y=0.0, z=2.0, accuracy_m=1.0, confidence=0.5, timestamp=100.0
    )
    a._cache["d2"] = Measurement(
        source="wifi", x=3.0, y=0.0, z=4.0, accuracy_m=1.0, confidence=0.5, timestamp=200.0
    )
    out = a.observed_devices()
    assert [d["id"] for d in out] == ["d2", "d1"]  # newest activity first
    assert out[0]["position"] == {"x": 3.0, "y": 0.0, "z": 4.0}
    assert out[0]["last_seen"] == 200.0
    # A device seen on the air is always a mobile asset, never an anchor.
    assert all(d["role"] == "trackable" for d in out)


@pytest.mark.asyncio
async def test_devices_endpoint_observed_origin(app_with_adapter):
    async with AsyncClient(transport=ASGITransport(app=app_with_adapter), base_url="http://t") as c:
        r = await c.get("/devices")
    assert r.status_code == 200
    assert r.json()["origin"] == "observed"


@pytest.mark.asyncio
async def test_devices_endpoint_degraded_returns_empty():
    # Adapter not wired yet (blueprint still loading): /devices must not 500.
    from app.main import app

    app.state.adapter = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/devices")
    assert r.status_code == 200
    assert r.json() == {"origin": "observed", "devices": []}
