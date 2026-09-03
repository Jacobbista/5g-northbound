import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.store import State


@pytest.fixture
def fresh_state():
    """Reset app state between tests so cache + schema do not leak."""
    app.state.store = State()
    return app.state.store


@pytest.fixture
async def client(fresh_state):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_reports_unconfigured_when_no_schema(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["schema_loaded"] is False
    assert r.json()["vendor"] is None


@pytest.mark.asyncio
async def test_get_schema_404_when_unloaded(client):
    r = await client.get("/schema")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_put_schema_validates_and_persists(
    client, wittra_schema_dict, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "app.routers.schema.get_settings",
        lambda: type("S", (), {"schema_file": str(tmp_path / "schema.json")})(),
    )
    r = await client.put("/schema", json=wittra_schema_dict)
    assert r.status_code == 200
    assert r.json()["vendor"] == "wittra"
    assert r.json()["persisted"] is True

    health = await client.get("/health")
    assert health.json()["schema_loaded"] is True
    assert health.json()["vendor"] == "wittra"


@pytest.mark.asyncio
async def test_put_schema_reports_x_vendor_keys(
    client, wittra_schema_dict, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "app.routers.schema.get_settings",
        lambda: type("S", (), {"schema_file": str(tmp_path / "schema.json")})(),
    )
    d = dict(wittra_schema_dict)
    d["diagnostics"] = {
        "stream": {
            "battery": {"path": "latest.data.battery.percentage"},
            "temperature": {"path": "latest.data.temperature"},
        }
    }
    r = await client.put("/schema", json=d)
    assert r.status_code == 200
    assert "temperature" in r.json()["x_vendor_keys"]
    assert "battery" not in r.json()["x_vendor_keys"]


@pytest.mark.asyncio
async def test_put_schema_applies_live_even_when_readonly_mount(
    client, wittra_schema_dict, monkeypatch, tmp_path
):
    # ConfigMap/subPath: persistence fails, but the PUT must still apply the
    # schema live (200, persisted:false, warning) instead of 500ing.
    monkeypatch.setattr(
        "app.routers.schema.get_settings",
        lambda: type("S", (), {"schema_file": str(tmp_path / "schema.json")})(),
    )
    monkeypatch.setattr("app.routers.schema.save_schema", lambda path, schema: False)
    r = await client.put("/schema", json=wittra_schema_dict)
    assert r.status_code == 200
    body = r.json()
    assert body["persisted"] is False
    assert "warning" in body
    # Applied live regardless of persistence.
    health = await client.get("/health")
    assert health.json()["schema_loaded"] is True


@pytest.mark.asyncio
async def test_put_schema_400_on_invalid_payload(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.routers.schema.get_settings",
        lambda: type("S", (), {"schema_file": str(tmp_path / "schema.json")})(),
    )
    r = await client.put("/schema", json={"vendor": "x"})  # missing required fields
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_measurement_404_when_no_schema(client):
    r = await client.get("/measurement/anything")
    assert r.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_measurement_end_to_end(
    client, fresh_state, wittra_schema, wittra_sample_payload, monkeypatch
):
    monkeypatch.setenv("WITTRA_ORG_ID", "orgA")
    monkeypatch.setenv("WITTRA_API_KEY", "k")
    monkeypatch.setenv("WITTRA_PROJECT_ID", "prj1")
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-vendor")
    fresh_state.schema = wittra_schema

    respx.get(
        "http://mock-vendor/v4/organizations/orgA/projects/prj1/devices/D001"
    ).mock(return_value=httpx.Response(200, json=wittra_sample_payload))

    r = await client.get("/measurement/D001")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "wittra"
    assert body["frame"] == "wgs84"
    assert body["latitude"] == 45.064547


@pytest.mark.asyncio
@respx.mock
async def test_measurement_cached_within_ttl(
    client, fresh_state, wittra_schema, wittra_sample_payload, monkeypatch
):
    monkeypatch.setenv("WITTRA_ORG_ID", "orgA")
    monkeypatch.setenv("WITTRA_API_KEY", "k")
    monkeypatch.setenv("WITTRA_PROJECT_ID", "prj1")
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-vendor")
    fresh_state.schema = wittra_schema

    route = respx.get(
        "http://mock-vendor/v4/organizations/orgA/projects/prj1/devices/D001"
    ).mock(return_value=httpx.Response(200, json=wittra_sample_payload))

    await client.get("/measurement/D001")
    await client.get("/measurement/D001")
    await client.get("/measurement/D001")
    # Only one vendor call thanks to the in-process TTL cache.
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_measurement_404_when_vendor_has_no_fix(
    client, fresh_state, wittra_schema, monkeypatch
):
    monkeypatch.setenv("WITTRA_ORG_ID", "orgA")
    monkeypatch.setenv("WITTRA_API_KEY", "k")
    monkeypatch.setenv("WITTRA_PROJECT_ID", "prj1")
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-vendor")
    fresh_state.schema = wittra_schema

    respx.get(
        "http://mock-vendor/v4/organizations/orgA/projects/prj1/devices/D001"
    ).mock(return_value=httpx.Response(404))
    r = await client.get("/measurement/D001")
    assert r.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_measurement_carries_stream_diagnostics(
    client, fresh_state, wittra_schema_dict, monkeypatch
):
    monkeypatch.setenv("WITTRA_ORG_ID", "orgA")
    monkeypatch.setenv("WITTRA_API_KEY", "k")
    monkeypatch.setenv("WITTRA_PROJECT_ID", "prj1")
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-vendor")
    from app.schema import Schema
    d = dict(wittra_schema_dict)
    d["diagnostics"] = {"stream": {"motion": {"path": "latest.data.location.value.motion"}}}
    fresh_state.schema = Schema.model_validate(d)

    respx.get(
        "http://mock-vendor/v4/organizations/orgA/projects/prj1/devices/D001"
    ).mock(return_value=httpx.Response(200, json={
        "deviceId": "D001", "deviceType": "tag",
        "latest": {"data": {"location": {
            "timestamp": "2026-06-03 14:36:17+00:00",
            "value": {"latitude": 45.0, "longitude": 7.0, "accuracy": 0.85,
                      "height": 1.2, "motion": "STATIONARY"},
        }}},
    }))

    r = await client.get("/measurement/D001")
    assert r.status_code == 200
    assert r.json()["diagnostics"] == {"x_vendor": {"motion": "STATIONARY"}}
