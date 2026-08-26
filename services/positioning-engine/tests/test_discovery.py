from unittest.mock import AsyncMock

import pytest

from app.registry import SEED, AdapterRegistry
from app.services.discovery import resolve_broadcast_targets


@pytest.fixture
def registry(tmp_path):
    fake = [100.0]
    reg = AdapterRegistry(
        ttl_s=45.0, heartbeat_s=15.0,
        persist_path=str(tmp_path / "a.json"), clock=lambda: fake[0],
    )
    reg.upsert("wifi", "http://wifi:8080", "adapter", SEED, {"devices": True})
    reg.upsert("mock", "http://mock:8080", "adapter", SEED, {"devices": True})
    reg.upsert("nocaps", "http://x:8080", "adapter", SEED, {})  # no `devices`
    return reg


async def test_resolves_id_to_reporting_adapter(registry):
    registry.adapters["wifi"].get_devices = AsyncMock(
        return_value={"origin": "observed", "devices": [{"id": "w1"}]}
    )
    registry.adapters["mock"].get_devices = AsyncMock(
        return_value={"origin": "inventory", "devices": [{"id": "m1"}]}
    )
    registry.adapters["nocaps"].get_devices = AsyncMock(
        return_value={"origin": "inventory", "devices": [{"id": "n1"}]}
    )
    targets = await resolve_broadcast_targets(registry)
    # nocaps has no `devices` capability -> not polled, its id never appears.
    assert targets == {"w1": "wifi", "m1": "mock"}


async def test_observed_outranks_inventory_on_overlap(registry):
    # Both report puppypi-01. Deterministic precedence: observed (a real scan
    # arrived) beats the mock's declared inventory -> route to wifi, not mock.
    registry.adapters["wifi"].get_devices = AsyncMock(
        return_value={"origin": "observed", "devices": [{"id": "puppypi-01"}]}
    )
    registry.adapters["mock"].get_devices = AsyncMock(
        return_value={"origin": "inventory", "devices": [{"id": "puppypi-01"}]}
    )
    targets = await resolve_broadcast_targets(registry)
    assert targets == {"puppypi-01": "wifi"}


async def test_same_origin_overlap_breaks_ties_by_name(registry):
    # Same origin rank -> deterministic alphabetical adapter name, never
    # first-responder (which would flip-flop between ticks).
    registry.adapters["wifi"].get_devices = AsyncMock(
        return_value={"origin": "inventory", "devices": [{"id": "dup"}]}
    )
    registry.adapters["mock"].get_devices = AsyncMock(
        return_value={"origin": "inventory", "devices": [{"id": "dup"}]}
    )
    targets = await resolve_broadcast_targets(registry)
    assert targets == {"dup": "mock"}  # "mock" < "wifi"


async def test_infrastructure_devices_are_not_broadcast_targets(registry):
    # A vendor inventory mixes trackable assets with infrastructure (anchors,
    # gateways, beacons). Only assets have a queryable fix; polling an anchor's
    # GET /measurement makes the vendor answer 422. Infrastructure must be
    # excluded from broadcast targets. Devices with no role stay in (wifi).
    registry.adapters["wifi"].get_devices = AsyncMock(
        return_value={"origin": "observed", "devices": [{"id": "w1"}]}
    )
    registry.adapters["mock"].get_devices = AsyncMock(
        return_value={"origin": "inventory", "devices": [
            {"id": "tag1", "role": "asset"},
            {"id": "gw1", "role": "infrastructure"},
            {"id": "beacon1", "role": "infrastructure"},
        ]}
    )
    targets = await resolve_broadcast_targets(registry)
    assert targets == {"w1": "wifi", "tag1": "mock"}


async def test_empty_when_no_capable_adapter(tmp_path):
    reg = AdapterRegistry(
        ttl_s=45.0, heartbeat_s=15.0, persist_path=str(tmp_path / "a.json"),
    )
    reg.upsert("nocaps", "http://x:8080", "adapter", SEED, {})
    assert await resolve_broadcast_targets(reg) == {}


async def test_skips_erroring_adapter(registry):
    registry.adapters["wifi"].get_devices = AsyncMock(
        return_value={"origin": "observed", "devices": [{"id": "w1"}]}
    )
    registry.adapters["mock"].get_devices = AsyncMock(side_effect=RuntimeError("boom"))
    targets = await resolve_broadcast_targets(registry)
    assert targets == {"w1": "wifi"}  # mock's failure does not stall the rest
