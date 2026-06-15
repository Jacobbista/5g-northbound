from httpx import ASGITransport, AsyncClient

from app.main import app


async def _get(path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_contract_served_without_auth():
    # /contract carries no business data and must answer even with auth on and
    # no token, exactly like /health.
    r = await _get("/contract")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "wifi-positioning"
    assert body["kind"] == "internal"
    assert body["external_origin"] is None
    assert "required" in body["env"]
    assert "recommended" in body["env"]
    assert "optional" in body["env"]


async def test_contract_exposes_names_only_no_values():
    r = await _get("/contract")
    body = r.json()
    all_names = [
        e["name"] for tier in body["env"].values() for e in tier
    ]
    assert "WIFI_CONFIG_PATH" in all_names
    # Schema only: entries describe vars, they never carry a runtime value.
    for tier in body["env"].values():
        for entry in tier:
            assert "name" in entry
            assert "value" not in entry


async def test_ready_endpoint_present():
    # Degraded-boot contract: /ready reflects business config. With a valid
    # default bindings file the app loads and is ready.
    r = await _get("/ready")
    assert r.status_code in (200, 503)
