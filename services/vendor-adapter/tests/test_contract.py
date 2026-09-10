import json
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schema import Schema
from app.store import State


def _example() -> Schema:
    path = Path(__file__).resolve().parents[1] / "examples" / "wittra-schema.json"
    return Schema.model_validate(json.loads(path.read_text()))


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
    app.state.store = State()
    app.state.store.schema = _example()
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
    for key in ("vendor", "baseUrl", "path", "auth", "mapping"):
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


async def test_schema_contract_documents_mapping_fields():
    # The Mapping fields carry descriptions so an operator (and the thesis)
    # can read the semantics - notably that latitude/longitude double as the
    # local x/z, and that y/confidence are optional.
    r = await _get("/contract/schema")
    mapping = r.json()["$defs"]["Mapping"]["properties"]
    for field in ("frame", "latitude", "longitude", "accuracy", "confidence", "y", "timestamp"):
        assert mapping[field].get("description"), f"{field} lacks a description"



async def test_an_unbound_instance_announces_no_vendor_variables():
    app.state.store = State()
    body = (await _get("/contract")).json()
    assert body["configured"] is False
    assert body["vendor"] is None
    assert body["schema_source"] == "none"
    assert body["env"]["required"] == []
    assert body["mapping"] is None
    assert "discover_mapping" not in body


async def test_a_bound_instance_announces_its_own_variables():
    app.state.store = State()
    app.state.store.schema = _example()
    app.state.store.schema_source = "mounted"
    body = (await _get("/contract")).json()
    assert body["configured"] is True
    assert body["vendor"] == "wittra"
    assert body["schema_source"] == "mounted"
    names = [e["name"] for e in body["env"]["required"]]
    assert names == [
        "WITTRA_API_KEY",
        "WITTRA_BASE_URL",
        "WITTRA_ORG_ID",
        "WITTRA_PROJECT_ID",
    ]
    key = [e for e in body["env"]["required"] if e["name"] == "WITTRA_API_KEY"]
    assert key[0]["sensitive"] is True
    assert body["mapping"]["supported"]
    assert body["discover_mapping"]["supported"]


async def test_no_wittra_name_reaches_a_differently_bound_instance(wittra_schema_dict):
    # The regression this endpoint exists to close: a generic image must not
    # ask an acme operator for Wittra credentials.
    doc = dict(wittra_schema_dict)
    doc["vendor"] = "acme"
    doc["baseUrl"] = {"env": "ACME_BASE_URL"}
    doc["path"] = "/api/{tenant}/device/{device_id}"
    doc["pathVars"] = {"tenant": {"env": "ACME_TENANT"}}
    doc["auth"] = {"scheme": "bearer", "token": {"env": "ACME_TOKEN"}}
    doc.pop("discover", None)
    doc.pop("diagnostics", None)
    app.state.store = State()
    app.state.store.schema = Schema.model_validate(doc)
    app.state.store.schema_source = "runtime"
    body = (await _get("/contract")).json()
    assert body["vendor"] == "acme"
    assert body["schema_source"] == "runtime"
    assert [e["name"] for e in body["env"]["required"]] == [
        "ACME_BASE_URL",
        "ACME_TENANT",
        "ACME_TOKEN",
    ]
    assert "WITTRA_" not in json.dumps(body)


async def test_the_baked_contract_names_no_vendor():
    # The image is generic. Vendor variables reach /contract only through a
    # loaded schema, so the baked YAML declares none.
    app.state.store = State()
    body = (await _get("/contract")).json()
    assert "WITTRA" not in json.dumps(body["env"])
