import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schema import Schema
from app.store import State


def _schema(wittra_schema_dict):
    d = dict(wittra_schema_dict)
    d["diagnostics"] = {
        "stream": {"motion": {"path": "latest.data.location.value.motion"}},
        "on_demand": [{
            "path": "/v4/organizations/{org_id}/projects/{project_id}/devices/{device_id}",
            "path_vars": {"org_id": {"env": "WITTRA_ORG_ID"}, "project_id": {"env": "WITTRA_PROJECT_ID"}},
            "mapping": {
                "accuracy_value": {"path": "latest.data.location.value.accuracy"},
                "accuracy_kind": {"const": "vendor-radius"},
                "motion": {"path": "latest.data.location.value.motion"},
            },
        }],
    }
    return Schema.model_validate(d)


@pytest.mark.asyncio
@respx.mock
async def test_diagnostics_route_maps_on_demand(wittra_schema_dict, monkeypatch):
    monkeypatch.setenv("WITTRA_ORG_ID", "orgA")
    monkeypatch.setenv("WITTRA_API_KEY", "k")
    monkeypatch.setenv("WITTRA_PROJECT_ID", "prj1")
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-vendor")
    respx.get(
        "http://mock-vendor/v4/organizations/orgA/projects/prj1/devices/D001"
    ).mock(return_value=httpx.Response(200, json={
        "latest": {"data": {"location": {"value": {"accuracy": 0.9, "motion": "MOVING"}}}}
    }))
    state = State(); state.schema = _schema(wittra_schema_dict); app.state.store = state
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/diagnostics/D001")
    assert r.status_code == 200
    body = r.json()
    assert body["device_id"] == "D001"
    assert body["diagnostics"] == {"accuracy_value": 0.9, "accuracy_kind": "vendor-radius", "motion": "MOVING"}


@pytest.mark.asyncio
async def test_diagnostics_route_404_when_no_block(wittra_schema, monkeypatch):
    state = State(); state.schema = wittra_schema; app.state.store = state
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/diagnostics/D001")
    assert r.status_code == 404
