import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health():
    from app.main import app as _app

    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ingest_then_measurement(app_with_adapter):
    async with AsyncClient(transport=ASGITransport(app=app_with_adapter), base_url="http://t") as c:
        r = await c.post(
            "/ingest/wifi-scan",
            json={"device_id": "dev1", "scan": {"AA:AA:AA:AA:AA:01": -50, "BB:BB:BB:BB:BB:01": -65}},
        )
        assert r.status_code == 200

        r2 = await c.get("/measurement/dev1")
        assert r2.status_code == 200
        body = r2.json()
        assert body["source"] == "wifi"
        assert "x" in body and "z" in body
        assert body["accuracy_m"] >= 1.0
        assert 0.0 < body["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_measurement_404_for_unknown_device(app_with_adapter):
    async with AsyncClient(transport=ASGITransport(app=app_with_adapter), base_url="http://t") as c:
        r = await c.get("/measurement/never-seen")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_ingest_rejects_unknown_bssid(app_with_adapter):
    async with AsyncClient(transport=ASGITransport(app=app_with_adapter), base_url="http://t") as c:
        r = await c.post(
            "/ingest/wifi-scan",
            json={"device_id": "d", "scan": {"FF:FF:FF:FF:FF:FF": -40}},
        )
    assert r.status_code == 422
