from httpx import ASGITransport, AsyncClient

from app.main import app
from app.store import State


async def test_devices_empty_without_schema():
    app.state.store = State()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/devices")
    assert r.status_code == 200
    assert r.json() == {"origin": "inventory", "devices": []}


async def test_devices_maps_discover_output(wittra_schema, monkeypatch):
    app.state.store = State()
    app.state.store.schema = wittra_schema

    async def fake_discover(schema):
        return [
            {"vendor_device_id": "D001", "label": "Tag 1",
             "latitude": 59.4, "longitude": 17.9, "height_m": 0},
            {"vendor_device_id": "D002", "latitude": None, "longitude": None},
            {"label": "no-id"},  # dropped: no vendor_device_id
        ]

    monkeypatch.setattr("app.routers.devices.discover", fake_discover)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/devices")
    body = r.json()
    assert body["origin"] == "inventory"
    devs = {d["id"]: d for d in body["devices"]}
    assert set(devs) == {"D001", "D002"}  # the id-less entry is dropped
    assert devs["D001"]["label"] == "Tag 1"
    assert devs["D001"]["position"] == {"latitude": 59.4, "longitude": 17.9}
    assert "position" not in devs["D002"]  # no coords -> no position
