from httpx import ASGITransport, AsyncClient


async def test_devices_lists_configured_ids(app, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "device_ids", "synthetic-demo-01, forklift-7")
    monkeypatch.setattr(settings, "anchor_ids", "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/devices")
    assert r.status_code == 200
    body = r.json()
    assert body["origin"] == "inventory"
    assert [d["id"] for d in body["devices"]] == ["forklift-7", "synthetic-demo-01"]  # sorted
    assert all(d["role"] == "asset" for d in body["devices"])


async def test_devices_empty_when_none_configured(app, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "device_ids", "")
    monkeypatch.setattr(settings, "anchor_ids", "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/devices")
    assert r.json() == {"origin": "inventory", "devices": []}


async def test_devices_mixes_assets_and_infrastructure(app, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "device_ids", "tag-2, tag-1")
    monkeypatch.setattr(settings, "anchor_ids", "anchor-1")
    monkeypatch.setattr(settings, "source_class", "uwb")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/devices")
    body = r.json()
    by_id = {d["id"]: d for d in body["devices"]}
    # Assets (sorted) first, then infrastructure.
    assert [d["id"] for d in body["devices"]] == ["tag-1", "tag-2", "anchor-1"]
    assert by_id["tag-1"]["role"] == "asset"
    assert by_id["anchor-1"]["role"] == "infrastructure"
    assert all(d["source_class"] == "uwb" for d in body["devices"])


async def test_devices_omits_source_class_when_unset(app, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "device_ids", "tag-1")
    monkeypatch.setattr(settings, "anchor_ids", "")
    monkeypatch.setattr(settings, "source_class", "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/devices")
    assert "source_class" not in r.json()["devices"][0]
