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
    assert body["service"] == "placement-editor"
    assert body["kind"] == "ui"
    assert body["external_origin"] == "PLACEMENT_EDITOR_EXTERNAL_ORIGIN"
    assert "required" in body["env"]
    assert "recommended" in body["env"]
    assert "optional" in body["env"]


async def test_contract_exposes_required_names_only_no_values():
    r = await _get("/contract")
    body = r.json()
    all_names = [e["name"] for tier in body["env"].values() for e in tier]
    assert "WIFI_POSITIONING_URL" in all_names
    # Schema only: entries describe vars, they never carry a runtime value.
    for tier in body["env"].values():
        for entry in tier:
            assert "name" in entry
            assert "value" not in entry
