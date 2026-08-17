from httpx import ASGITransport, AsyncClient

from app.main import app
from app.store import State


async def test_devices_empty_without_schema():
    app.state.store = State()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/devices")
    assert r.status_code == 200
    assert r.json() == {"origin": "inventory", "devices": []}


async def test_devices_unfiltered_passes_role_and_source_class(wittra_schema, monkeypatch):
    app.state.store = State()
    app.state.store.schema = wittra_schema
    calls = {}

    async def fake_discover(schema, *, apply_filter=True):
        calls["apply_filter"] = apply_filter
        # discover() has already merged classify (role/source_class) per entry.
        return [
            {"vendor_device_id": "BEACON1", "label": "b1", "latitude": 59.4,
             "longitude": 17.9, "role": "infrastructure", "source_class": "uwb"},
            {"vendor_device_id": "TAG1", "role": "asset", "source_class": "uwb"},
            {"label": "no-id"},  # dropped: no vendor_device_id
        ]

    monkeypatch.setattr("app.routers.devices.discover", fake_discover)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/devices")
    # Onboarding must read the list UNFILTERED (else the editor's anchor filter
    # would drop the tags).
    assert calls["apply_filter"] is False
    body = r.json()
    assert body["origin"] == "inventory"
    devs = {d["id"]: d for d in body["devices"]}
    assert set(devs) == {"BEACON1", "TAG1"}
    assert devs["BEACON1"]["role"] == "infrastructure"
    assert devs["BEACON1"]["source_class"] == "uwb"
    assert devs["BEACON1"]["position"] == {"latitude": 59.4, "longitude": 17.9}
    assert devs["TAG1"]["role"] == "asset"
    assert "position" not in devs["TAG1"]  # a tag has no fixedLocation
