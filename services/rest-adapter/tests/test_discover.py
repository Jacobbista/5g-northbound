import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.discover import discover as run_discover
from app.main import app
from app.mapper import to_discover_entry
from app.store import State


def test_to_discover_entry_extracts_known_fields(wittra_schema, wittra_sample_discover_page):
    entry = wittra_sample_discover_page[0]
    out = to_discover_entry(wittra_schema.discover.mapping, entry)
    assert out is not None
    assert out["vendor_device_id"] == "D001"
    # The schema uses deviceId for both id and label since the real Wittra v4
    # device record has no human-friendly name field.
    assert out["label"] == "D001"
    # device_type maps from the native deviceType field (drives anchor vs
    # trackable classification via the block's anchor_types).
    assert out["device_type"] == "beacon"
    assert out["latitude"] == pytest.approx(45.064547)
    assert out["longitude"] == pytest.approx(7.659272)
    # height_m is a const 0 in the example schema (v4 fixedLocation has level
    # but no metre-height).
    assert out["height_m"] == 0


def test_to_discover_entry_returns_none_when_id_missing(wittra_schema):
    out = to_discover_entry(wittra_schema.discover.mapping, {"deviceType": "beacon"})
    assert out is None


def test_to_discover_entry_handles_missing_optional_fields(wittra_schema):
    out = to_discover_entry(wittra_schema.discover.mapping, {"deviceId": "D003"})
    assert out is not None
    assert out["vendor_device_id"] == "D003"
    # label maps from deviceId, so it has a value here too.
    assert out["label"] == "D003"
    assert out["latitude"] is None
    assert out["longitude"] is None
    # height_m is a const 0 in the example schema.
    assert out["height_m"] == 0


@respx.mock
async def test_run_discover_walks_paginated_endpoint(
    wittra_schema, wittra_sample_discover_page, monkeypatch
):
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-wittra")
    monkeypatch.setenv("WITTRA_ORG_ID", "orgA")
    monkeypatch.setenv("WITTRA_PROJECT_ID", "prj1")
    monkeypatch.setenv("WITTRA_API_KEY", "k")
    respx.get(
        "http://mock-wittra/v4/organizations/orgA/projects/prj1/devices"
    ).mock(return_value=httpx.Response(200, json=wittra_sample_discover_page))

    devices = await run_discover(wittra_schema)
    assert devices is not None
    assert len(devices) == 2
    assert devices[0]["vendor_device_id"] == "D001"


@respx.mock
async def test_run_discover_returns_none_on_vendor_5xx(wittra_schema, monkeypatch):
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-wittra")
    monkeypatch.setenv("WITTRA_ORG_ID", "orgA")
    monkeypatch.setenv("WITTRA_PROJECT_ID", "prj1")
    monkeypatch.setenv("WITTRA_API_KEY", "k")
    respx.get(
        "http://mock-wittra/v4/organizations/orgA/projects/prj1/devices"
    ).mock(return_value=httpx.Response(500))

    devices = await run_discover(wittra_schema)
    assert devices is None


@respx.mock
async def test_discover_route_returns_normalised_devices(
    wittra_schema, wittra_sample_discover_page, monkeypatch
):
    monkeypatch.setenv("WITTRA_BASE_URL", "http://mock-wittra")
    monkeypatch.setenv("WITTRA_ORG_ID", "orgA")
    monkeypatch.setenv("WITTRA_PROJECT_ID", "prj1")
    monkeypatch.setenv("WITTRA_API_KEY", "k")
    respx.get(
        "http://mock-wittra/v4/organizations/orgA/projects/prj1/devices"
    ).mock(return_value=httpx.Response(200, json=wittra_sample_discover_page))

    state = State()
    state.schema = wittra_schema
    app.state.store = state
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/discover")
    assert r.status_code == 200
    body = r.json()
    assert body["vendor"] == "wittra"
    assert len(body["devices"]) == 2


async def test_discover_route_503_without_schema():
    app.state.store = State()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/discover")
    assert r.status_code == 503


async def test_discover_route_404_when_schema_has_no_discover_block(wittra_schema_dict):
    from app.schema import Schema

    dict_no_discover = {k: v for k, v in wittra_schema_dict.items() if k != "discover"}
    state = State()
    state.schema = Schema.model_validate(dict_no_discover)
    app.state.store = state
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/discover")
    assert r.status_code == 404
