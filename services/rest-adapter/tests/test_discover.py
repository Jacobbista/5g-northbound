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
    # Wittra's native deviceType is an opaque object, so the schema does not map
    # device_type; classification is structural (see classify tests below).
    assert out["device_type"] is None
    assert out["latitude"] == pytest.approx(45.064547)
    assert out["longitude"] == pytest.approx(7.659272)
    # height_m is a const 0 in the example schema (v4 fixedLocation has level
    # but no metre-height).
    assert out["height_m"] == 0


def test_classify_entry_splits_role_and_source_class(wittra_schema):
    from app.mapper import classify_entry

    cl = wittra_schema.discover.classify
    # fixedLocation present -> a fixed UWB anchor (infrastructure)
    anchor = classify_entry(cl, {"fixedLocation": {"latitude": 1.0, "longitude": 2.0}})
    assert anchor == {"role": "infrastructure", "source_class": "uwb"}
    # no fixedLocation -> a mobile tag (asset)
    tag = classify_entry(cl, {"deviceId": "TAG1"})
    assert tag == {"role": "asset", "source_class": "uwb"}


async def test_discover_unfiltered_keeps_tags(wittra_schema, monkeypatch):
    # With an anchor-only filter, apply_filter=True drops the tag; onboarding's
    # apply_filter=False keeps it.
    from app.discover import discover
    from app.schema import DiscoverFilter

    wittra_schema.discover.filter = DiscoverFilter(require_path="fixedLocation.latitude")
    raw = [
        {"deviceId": "BEACON1", "fixedLocation": {"latitude": 59.4, "longitude": 17.9}},
        {"deviceId": "TAG1", "fixedLocation": None},
    ]

    async def fake_fetch(schema, page=None):
        return raw

    monkeypatch.setattr("app.discover.fetch_discover_page", fake_fetch)

    filtered = await discover(wittra_schema, apply_filter=True)
    assert {d["vendor_device_id"] for d in filtered} == {"BEACON1"}  # tag dropped

    unfiltered = await discover(wittra_schema, apply_filter=False)
    by_id = {d["vendor_device_id"]: d for d in unfiltered}
    assert set(by_id) == {"BEACON1", "TAG1"}  # tag kept
    assert by_id["BEACON1"]["role"] == "infrastructure"
    assert by_id["TAG1"]["role"] == "asset"


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
