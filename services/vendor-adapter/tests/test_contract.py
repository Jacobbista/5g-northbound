from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schema import Schema
from app.store import State


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
    assert body["service"] == "vendor-adapter"
    assert body["kind"] == "internal"
    assert body["external_origin"] is None
    assert "required" in body["env"]
    assert "recommended" in body["env"]
    assert "optional" in body["env"]


async def test_contract_exposes_required_names_only_no_values():
    r = await _get("/contract")
    body = r.json()
    all_names = [e["name"] for tier in body["env"].values() for e in tier]
    assert "WITTRA_API_KEY" in all_names
    # Schema only: entries describe vars, they never carry a runtime value.
    for tier in body["env"].values():
        for entry in tier:
            assert "name" in entry
            assert "value" not in entry


async def test_contract_points_at_schema_document():
    r = await _get("/contract")
    assert r.status_code == 200
    assert r.json()["schema"] == "/contract/schema"


async def test_schema_contract_served_without_auth_and_without_instance():
    app.state.store = State()
    r = await _get("/contract/schema")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "object"
    required = body.get("required") or []
    for key in ("vendor", "default_base_url", "path", "auth", "mapping"):
        assert key in required
        assert key in body["properties"]
    assert "diagnostics" in body["properties"]
    assert "diagnostics" not in required
    defs = body.get("$defs", {})
    assert "PathSpec" in defs
    assert "ConstSpec" in defs
    assert "BoolTransform" in defs
    assert "DiagnosticsBlock" in defs


async def test_schema_contract_describes_the_pydantic_model():
    r = await _get("/contract/schema")
    assert r.json() == Schema.model_json_schema()

