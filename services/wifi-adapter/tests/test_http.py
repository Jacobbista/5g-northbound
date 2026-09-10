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
        assert body["accuracy"] >= 1.0
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


_SCAN = {"AA:AA:AA:AA:AA:01": -50, "BB:BB:BB:BB:BB:01": -65}


@pytest.mark.asyncio
async def test_ingest_accepts_the_current_field_name(app_with_adapter):
    async with AsyncClient(transport=ASGITransport(app=app_with_adapter), base_url="http://t") as c:
        r = await c.post("/ingest/wifi-scan", json={"positioningId": "dev-new", "scan": _SCAN})
        assert r.status_code == 200
        assert r.json() == {"ok": True}  # nothing to warn about
        assert (await c.get("/measurement/dev-new")).status_code == 200

        listed = {d["id"]: d for d in (await c.get("/devices")).json()["devices"]}
        assert "supersededIngestField" not in listed["dev-new"]


@pytest.mark.asyncio
async def test_ingest_still_accepts_the_superseded_name_and_says_so(app_with_adapter, caplog):
    # A scanner deployed before the rename keeps reporting; its operator learns
    # from the response, not from a silent failure.
    async with AsyncClient(transport=ASGITransport(app=app_with_adapter), base_url="http://t") as c:
        with caplog.at_level("WARNING"):
            r = await c.post("/ingest/wifi-scan", json={"device_id": "dev-old", "scan": _SCAN})
        assert r.status_code == 200
        assert "positioningId" in r.json()["warning"]
        assert (await c.get("/measurement/dev-old")).status_code == 200
        assert sum("dev-old" in m for m in caplog.messages) == 1

        # The adapter already knows which device sent the scan, so the fact is
        # reported per device instead of only in the log.
        listed = {d["id"]: d for d in (await c.get("/devices")).json()["devices"]}
        assert listed["dev-old"]["supersededIngestField"] == "device_id"

        # A second scan from the same device carries the warning without
        # repeating the log line.
        before = len(caplog.messages)
        with caplog.at_level("WARNING"):
            r2 = await c.post("/ingest/wifi-scan", json={"device_id": "dev-old", "scan": _SCAN})
        assert "warning" in r2.json()
        assert len(caplog.messages) == before


@pytest.mark.asyncio
async def test_ingest_rejects_a_body_with_no_identifier(app_with_adapter):
    async with AsyncClient(transport=ASGITransport(app=app_with_adapter), base_url="http://t") as c:
        r = await c.post("/ingest/wifi-scan", json={"scan": _SCAN})
    assert r.status_code == 422
