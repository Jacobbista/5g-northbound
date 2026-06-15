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
    assert body["service"] == "camara-gateway"
    assert body["kind"] == "api"
    assert body["external_origin"] == "CAMARA_GATEWAY_EXTERNAL_ORIGIN"
    assert "required" in body["env"]
    assert "recommended" in body["env"]
    assert "optional" in body["env"]


async def test_contract_exposes_required_names_only_no_values():
    r = await _get("/contract")
    body = r.json()
    names = [e["name"] for e in body["env"]["required"]]
    assert "KEYCLOAK_URL" in names
    # Schema only: entries describe vars, they never carry a runtime value.
    # Sensitive entries additionally drop any value-bearing field (default /
    # example), even a committed placeholder, so a dashboard never pre-fills
    # a secret.
    for tier in body["env"].values():
        for entry in tier:
            assert "name" in entry
            assert "value" not in entry
            if entry.get("sensitive"):
                assert "default" not in entry
                assert "example" not in entry
