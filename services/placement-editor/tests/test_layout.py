import json


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_get_layout_404_when_missing(client, layout_file):
    resp = await client.get("/api/layout")
    assert resp.status_code == 404


async def test_get_layout_round_trip(client, layout_file):
    layout_file.write_text(json.dumps({"room_w": 13, "room_h": 32, "aps": []}))
    resp = await client.get("/api/layout")
    assert resp.status_code == 200
    body = resp.json()
    assert body["room_w"] == 13
    assert body["room_h"] == 32


async def test_put_layout_writes_file(client, layout_file):
    payload = {
        "room_w": 10,
        "room_h": 20,
        "aps": [{"id": "AP01", "x": 1, "y": 2}],
    }
    resp = await client.put("/api/layout", json=payload)
    assert resp.status_code == 200
    saved = json.loads(layout_file.read_text())
    assert saved["room_w"] == 10
    assert saved["aps"][0]["id"] == "AP01"


async def test_put_layout_preserves_extra_fields(client, layout_file):
    """Unknown keys round-trip - schema is extra=allow so the editor can
    evolve fields without backend changes."""
    payload = {"room_w": 5, "future_field": {"foo": "bar"}}
    resp = await client.put("/api/layout", json=payload)
    assert resp.status_code == 200
    saved = json.loads(layout_file.read_text())
    assert saved["future_field"] == {"foo": "bar"}
