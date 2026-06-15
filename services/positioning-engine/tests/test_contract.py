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
    assert body["service"] == "positioning-engine"
    assert body["kind"] == "internal"
    assert body["external_origin"] is None
    assert "required" in body["env"]
    assert "recommended" in body["env"]
    assert "optional" in body["env"]


async def test_contract_exposes_required_names_only_no_values():
    r = await _get("/contract")
    body = r.json()
    names = [e["name"] for e in body["env"]["required"]]
    assert "ADAPTER_URLS" in names
    # Schema only: entries describe vars, they never carry a runtime value.
    for tier in body["env"].values():
        for entry in tier:
            assert "name" in entry
            assert "value" not in entry
