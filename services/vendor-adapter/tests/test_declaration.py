"""The declared behaviour of the source, against the schema and the payloads."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.declaration import Observed, check
from app.main import app
from app.store import State

ON_MOTION = {"reporting": "on_motion", "reportingInterval": 60, "z": True}


def _without(schema, field):
    return schema.model_copy(update={"mapping": schema.mapping.model_copy(update={field: None})})


def test_a_consistent_declaration_passes(wittra_schema):
    assert check(wittra_schema, ON_MOTION) == []


def test_an_undeclared_source_is_not_refused(wittra_schema):
    # Nothing declared is the strictest reading, handled by the engine.
    assert check(wittra_schema, {}) == []


def test_on_motion_needs_the_last_communication(wittra_schema):
    errors = check(_without(wittra_schema, "lastSeen"), ON_MOTION)
    assert any("lastSeen" in e for e in errors)


@pytest.mark.parametrize("reporting", ["periodic", "on_motion"])
def test_an_interval_is_required(wittra_schema, reporting):
    errors = check(wittra_schema, {"reporting": reporting, "z": True})
    assert any("reportingInterval" in e for e in errors)


def test_a_declared_height_needs_a_mapping(wittra_schema):
    errors = check(_without(wittra_schema, "z"), ON_MOTION)
    assert any("z mapping" in e for e in errors)


def test_a_mapped_height_needs_the_declaration(wittra_schema):
    errors = check(wittra_schema, {**ON_MOTION, "z": False})
    assert any("z: true" in e for e in errors)


def test_a_nominal_vertical_error_needs_a_declared_height(wittra_schema):
    ok = check(wittra_schema, {**ON_MOTION, "nominalVerticalAccuracy": 0.8})
    assert not any("nominalVerticalAccuracy" in e for e in ok)
    flat = check(_without(wittra_schema, "z"), {**ON_MOTION, "z": False, "nominalVerticalAccuracy": 0.8})
    assert any("nominalVerticalAccuracy requires z: true" in e for e in flat)


def _m(ts, seen=None, lat=59.4, **extra):
    out = {"frame": "wgs84", "latitude": lat, "longitude": 17.9, "timestamp": ts, **extra}
    if seen is not None:
        out["lastSeen"] = seen
    return out


def test_counts_mapped_fields_that_do_not_resolve(wittra_schema):
    obs = Observed()
    obs.record("d", wittra_schema.mapping, _m(100.0), ON_MOTION)
    assert obs.as_dict()["unresolved"]["lastSeen"] == 1


def test_counts_reports_further_apart_than_the_interval(wittra_schema):
    obs = Observed()
    obs.record("d", wittra_schema.mapping, _m(100.0, seen=100.0), ON_MOTION)
    obs.record("d", wittra_schema.mapping, _m(100.0, seen=150.0), ON_MOTION)
    obs.record("d", wittra_schema.mapping, _m(100.0, seen=300.0), ON_MOTION)
    assert obs.intervalExceeded == 1


def test_counts_a_move_without_a_new_fix_for_on_motion(wittra_schema):
    obs = Observed()
    obs.record("d", wittra_schema.mapping, _m(100.0, seen=110.0, lat=59.4), ON_MOTION)
    obs.record("d", wittra_schema.mapping, _m(100.0, seen=120.0, lat=59.5), ON_MOTION)
    assert obs.movedWithoutFix == 1


async def _put_schema(body):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.put("/schema", json=body)


async def test_put_schema_refuses_a_contradiction(wittra_schema_dict, monkeypatch):
    monkeypatch.setenv("ADAPTER_CAPABILITIES", json.dumps({"z": False}))
    app.state.store = State()
    r = await _put_schema(wittra_schema_dict)
    assert r.status_code == 422
    assert r.json()["detail"]["declaration"]
    assert app.state.store.schema is None


async def test_contract_reports_the_declaration(wittra_schema, monkeypatch):
    monkeypatch.setenv("ADAPTER_CAPABILITIES", json.dumps({**ON_MOTION, "nominalVerticalAccuracy": 0.8}))
    app.state.store = State()
    app.state.store.schema = wittra_schema
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/contract")).json()
    assert body["declaration"]["reporting"] == "on_motion"
    assert body["declaration"]["nominalVerticalAccuracy"] == 0.8
    assert body["declaration"]["errors"] == []
    assert body["declaration"]["observed"]["measurements"] == 0
