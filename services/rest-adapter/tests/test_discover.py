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
    # label maps from the real Wittra `name` field.
    assert out["label"] == "Position Beacon 01"
    # deviceType is a clean string, surfaced verbatim as device_type.
    assert out["device_type"] == "beacon"
    assert out["latitude"] == pytest.approx(45.064547)
    assert out["longitude"] == pytest.approx(7.659272)
    # height_m maps from fixedLocation.height.
    assert out["height_m"] == pytest.approx(2.0)


def test_classify_entry_role_from_devicetype(wittra_schema):
    from app.mapper import classify_entry

    cl = wittra_schema.discover.classify
    # role is derived only from the vendor's own deviceType. The example asserts
    # NO source_class: /devices does not expose positioning tech per unit, so the
    # adapter invents none - the operator adds rules when they have a real signal.
    assert classify_entry(cl, {"deviceType": "tag"}) == {"role": "asset"}
    for infra_type in ("beacon", "meshrouter", "gateway"):
        assert classify_entry(cl, {"deviceType": infra_type}) == {"role": "infrastructure"}
    # An UNKNOWN deviceType defaults to infrastructure (asset_when: not
    # auto-onboarded), never asset.
    assert classify_entry(cl, {"deviceType": "some-future-node"}) == {"role": "infrastructure"}


def test_classify_entry_source_class_rules_grammar():
    # source_class is operator-authored: the adapter APPLIES rules but asserts
    # nothing on its own. Grammar exercised on a hand-built classify (not the
    # example), so the contract stays covered without the Wittra example
    # claiming a per-unit radio it cannot know.
    from app.mapper import classify_entry
    from app.schema import Classify, ClassifyPredicate, SourceClassRule

    cl = Classify(
        source_class_rules=[
            SourceClassRule(when=ClassifyPredicate(require_path="miotyConfig"), value="mioty"),
        ],
    )
    assert classify_entry(cl, {"miotyConfig": {"eui": "x"}}) == {"source_class": "mioty"}
    # No rule matches and no default -> no source_class emitted at all.
    assert classify_entry(cl, {"deviceType": "beacon"}) == {}


async def test_discover_unfiltered_keeps_tags(wittra_schema, monkeypatch):
    # With an anchor-only filter, apply_filter=True drops the tag; onboarding's
    # apply_filter=False keeps it.
    from app.discover import discover
    from app.schema import DiscoverFilter

    wittra_schema.discover.filter = DiscoverFilter(require_path="fixedLocation.latitude")
    raw = [
        {
            "deviceId": "BEACON1",
            "deviceType": "beacon",
            "fixedLocation": {"latitude": 59.4, "longitude": 17.9},
        },
        {"deviceId": "TAG1", "deviceType": "tag", "fixedLocation": None},
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
    # No `name` on this record -> label is None (default).
    assert out["label"] is None
    assert out["latitude"] is None
    assert out["longitude"] is None
    # height_m falls back to the mapping default (0) when fixedLocation is absent.
    assert out["height_m"] == 0
    assert out["device_type"] is None


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
    assert len(devices) == 3
    assert devices[0]["vendor_device_id"] == "D001"
    by_id = {d["vendor_device_id"]: d for d in devices}
    assert by_id["D001"]["role"] == "infrastructure"
    assert by_id["MR1"]["role"] == "infrastructure"
    assert by_id["TAG1"]["role"] == "asset"


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
    assert len(body["devices"]) == 3


@respx.mock
async def test_discover_route_raw_returns_verbatim_records(
    wittra_schema, wittra_sample_discover_page, monkeypatch
):
    # ?raw=1 returns the vendor payload untouched (no mapping/filter/classify),
    # for the guided schema builder.
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
        r = await c.get("/discover?raw=1")
    assert r.status_code == 200
    body = r.json()
    assert "devices" not in body
    assert body["raw"] == wittra_sample_discover_page  # byte-for-byte, deviceType + all


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
