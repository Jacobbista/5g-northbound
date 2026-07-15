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
            {"vendor_device_id": "D001", "label": "Tag 1", "device_type": "tag",
             "latitude": 59.4, "longitude": 17.9, "height_m": 0},
            {"vendor_device_id": "D002", "device_type": "beacon",
             "latitude": None, "longitude": None},
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
    # anchor_types classification: beacon (in the example schema's anchor_types)
    # is an anchor; tag is trackable. device_type surfaces on both.
    assert devs["D001"]["device_type"] == "tag"
    assert devs["D001"]["role"] == "trackable"
    assert devs["D002"]["device_type"] == "beacon"
    assert devs["D002"]["role"] == "anchor"


async def test_devices_no_role_when_schema_declares_no_anchor_types(wittra_schema, monkeypatch):
    # A schema that never declared anchor_types leaves role off entirely, so a
    # forward-compatible consumer treats every candidate as onboardable.
    wittra_schema.discover.anchor_types = []
    app.state.store = State()
    app.state.store.schema = wittra_schema

    async def fake_discover(schema):
        return [{"vendor_device_id": "D001", "device_type": "beacon"}]

    monkeypatch.setattr("app.routers.devices.discover", fake_discover)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/devices")
    dev = r.json()["devices"][0]
    assert dev["device_type"] == "beacon"
    assert "role" not in dev
