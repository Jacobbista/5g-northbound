"""mock-vendor is schema-driven: it serves whatever the mounted schema declares.

These tests point it at an `acme` schema whose shape is deliberately unlike
Wittra's (dict-root telemetry, bearer auth, a `list_path` wrapper, its own URL
paths) to prove the mock is vendor-agnostic - it reads the schema, not hardcoded
Wittra knowledge.
"""

import os
from pathlib import Path

os.environ["SCHEMA_FILE"] = str(Path(__file__).with_name("acme-schema.json"))
os.environ["ACME_TENANT"] = "t-1"
os.environ["ACME_TOKEN"] = "sekret"

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

_BEARER = {"Authorization": "Bearer sekret"}
_TELEMETRY = "/api/t-1/device/dev-9/pos"
_DISCOVER = "/api/t-1/devices"


def _get_path(obj, dotted):
    """Mirror of the adapter's dotted-path lookup, to prove the mock's output
    resolves back to the injected values (the inverse property)."""
    cur = obj
    for part in dotted.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur.get(part)
    return cur


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["vendor"] == "acme"
    assert r.json()["transport"] == "rest"


async def test_telemetry_satisfies_schema_mapping(client):
    r = await client.get(_TELEMETRY, headers=_BEARER)
    assert r.status_code == 200
    body = r.json()
    # The response must resolve via the schema's own mapping paths.
    assert isinstance(_get_path(body, "data.lat"), float)
    assert isinstance(_get_path(body, "data.lng"), float)
    assert isinstance(_get_path(body, "data.acc"), float)
    assert isinstance(_get_path(body, "data.ts"), str)


async def test_telemetry_walks(client):
    a = await client.get(_TELEMETRY, headers=_BEARER)
    b = await client.get(_TELEMETRY, headers=_BEARER)
    assert _get_path(a.json(), "data.lat") != _get_path(b.json(), "data.lat")


async def test_telemetry_missing_auth_401(client):
    r = await client.get(_TELEMETRY)
    assert r.status_code == 401


async def test_telemetry_wrong_token_401(client):
    r = await client.get(_TELEMETRY, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


async def test_telemetry_wrong_tenant_404(client):
    r = await client.get("/api/other/device/dev-9/pos", headers=_BEARER)
    assert r.status_code == 404


async def test_discover_wraps_in_list_path_and_classifies(client):
    r = await client.get(_DISCOVER, headers=_BEARER)
    assert r.status_code == 200
    body = r.json()
    items = _get_path(body, "items")
    assert isinstance(items, list) and len(items) == 2
    kinds = {_get_path(e, "kind") for e in items}
    # One entry carries the schema's asset device_type; one does not, so
    # onboarding sees both an asset and an infrastructure candidate.
    assert "mobile" in kinds
    assert kinds != {"mobile"}
    # The fixed node resolves an anchor position; the mobile asset does not.
    fixed = [e for e in items if _get_path(e, "anchor.lat") is not None]
    assert len(fixed) == 1
    assert all(_get_path(e, "id") for e in items)


async def test_unknown_path_404(client):
    r = await client.get("/api/t-1/nonsense", headers=_BEARER)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_on_demand_diagnostics(client):
    r = await client.get("/api/t-1/device/dev-1/uwb", headers=_BEARER)
    assert r.status_code == 200
    body = r.json()
    assert _get_path(body, "uwb.rssi") is not None
