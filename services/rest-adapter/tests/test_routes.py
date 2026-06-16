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

    health = await client.get("/health")
    assert health.json()["schema_loaded"] is True
    assert health.json()["vendor"] == "wittra"


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
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-wittra")
    fresh_state.schema = wittra_schema

    respx.get(
        "http://mock-wittra/v4/organizations/orgA/projects/prj1/data?deviceId=D001&dataType=location"
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
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-wittra")
    fresh_state.schema = wittra_schema

    route = respx.get(
        "http://mock-wittra/v4/organizations/orgA/projects/prj1/data?deviceId=D001&dataType=location"
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
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-wittra")
    fresh_state.schema = wittra_schema

    respx.get(
        "http://mock-wittra/v4/organizations/orgA/projects/prj1/data?deviceId=D001&dataType=location"
    ).mock(return_value=httpx.Response(404))
    r = await client.get("/measurement/D001")
    assert r.status_code == 404
