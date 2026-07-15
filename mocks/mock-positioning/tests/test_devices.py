from httpx import ASGITransport, AsyncClient


async def test_devices_lists_configured_ids(app, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "device_ids", "mock-demo-01, forklift-7")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/devices")
    assert r.status_code == 200
    body = r.json()
    assert body["origin"] == "inventory"
    assert [d["id"] for d in body["devices"]] == ["forklift-7", "mock-demo-01"]  # sorted
    assert all(d["role"] == "trackable" for d in body["devices"])


async def test_devices_empty_when_none_configured(app, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "device_ids", "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/devices")
    assert r.json() == {"origin": "inventory", "devices": []}
