from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app as _app
from app.registry import SEED, AdapterRegistry


@pytest.fixture
def registry(tmp_path):
    fake = [100.0]
    reg = AdapterRegistry(
        ttl_s=45.0, heartbeat_s=15.0,
        persist_path=str(tmp_path / "a.json"), clock=lambda: fake[0],
    )
    reg.upsert("wifi", "http://wifi:8080", "adapter", SEED, {"devices": True})
    reg.upsert("wittra", "http://wittra:8080", "adapter", SEED, {"devices": True})
    reg.upsert("nocaps", "http://x:8080", "adapter", SEED, {})  # no `devices` -> excluded
    reg.adapters["wifi"].get_devices = AsyncMock(
        return_value={"origin": "observed", "devices": [{"id": "w1", "last_seen": 5.0}]}
    )
    reg.adapters["wittra"].get_devices = AsyncMock(
        return_value={"origin": "inventory", "devices": [{"id": "D001", "label": "Tag"}]}
    )
    reg.adapters["nocaps"].get_devices = AsyncMock(
        return_value={"origin": "inventory", "devices": [{"id": "zzz"}]}
    )
    _app.state.registry = reg
    return reg


async def _get(path):
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        return await c.get(path)


async def test_devices_aggregates_capable_live_adapters(registry):
    r = await _get("/devices")
    assert r.status_code == 200
    devs = {d["id"]: d for d in r.json()["devices"]}
    assert set(devs) == {"w1", "D001"}  # nocaps excluded: no `devices` capability
    assert devs["w1"]["source"] == "wifi"
    assert devs["w1"]["origin"] == "observed"
    assert devs["D001"]["source"] == "wittra"
    assert devs["D001"]["label"] == "Tag"


async def test_devices_skips_unreachable_capable_adapter(registry):
    # Force wittra into cooldown: it is capable but not `live`, so excluded.
    degraded = registry.adapters["wittra"]
    degraded._fail_count = 5
    degraded._cooldown_until = degraded._clock() + 10.0
    r = await _get("/devices")
    ids = {d["id"] for d in r.json()["devices"]}
    assert ids == {"w1"}
