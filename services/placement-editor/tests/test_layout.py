import httpx
import respx


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@respx.mock
async def test_get_layout_proxies_engine_blueprint(client, engine_url):
    body = {"room_w": 13, "room_h": 32, "floor_plans": [], "rooms": []}
    respx.get(f"{engine_url}/blueprint").mock(return_value=httpx.Response(200, json=body))
    resp = await client.get("/api/layout")
    assert resp.status_code == 200
    assert resp.json()["room_w"] == 13


@respx.mock
async def test_get_layout_404_when_engine_has_none(client, engine_url):
    respx.get(f"{engine_url}/blueprint").mock(return_value=httpx.Response(404))
    resp = await client.get("/api/layout")
    assert resp.status_code == 404


@respx.mock
async def test_put_layout_forwards_to_engine(client, engine_url):
    captured = {}

    def _capture(request):
        captured["body"] = request.content
        return httpx.Response(200, json={"status": "ok", "floor_plans": 1, "rooms": 1})

    respx.put(f"{engine_url}/blueprint").mock(side_effect=_capture)
    payload = {"room_w": 10, "rooms": [{"width_m": 10}], "future_field": {"foo": "bar"}}
    resp = await client.put("/api/layout", json=payload)
    assert resp.status_code == 200
    # body forwarded verbatim, including unknown keys
    assert b"future_field" in captured["body"]


@respx.mock
async def test_put_layout_502_when_engine_unreachable(client, engine_url):
    respx.put(f"{engine_url}/blueprint").mock(side_effect=httpx.ConnectError("down"))
    resp = await client.put("/api/layout", json={"room_w": 1})
    assert resp.status_code == 502
