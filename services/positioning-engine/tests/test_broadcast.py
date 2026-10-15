import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.models import GpsOrigin
from app.registry import SEED, AdapterRegistry
from app.routers import websocket as ws


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, msg):
        self.sent.append(msg)

    async def send_bytes(self, msg):  # pragma: no cover - not exercised
        self.sent.append(msg)


@pytest.fixture(autouse=True)
def fast_intervals(monkeypatch):
    monkeypatch.setattr(settings, "websocket_interval_ms", 1)
    monkeypatch.setattr(settings, "device_discovery_interval_s", 0.0)


async def _run_until_called(app, mock):
    client = _FakeWS()
    ws.manager.connections.add(client)
    task = asyncio.create_task(ws.broadcast_loop(app))
    try:
        for _ in range(200):
            if mock.await_count:
                return
            await asyncio.sleep(0.005)
        raise AssertionError("get_position was never called")
    finally:
        task.cancel()
        ws.manager.connections.discard(client)
        try:
            await task
        except asyncio.CancelledError:
            pass


async def test_broadcast_routes_to_discovered_source(tmp_path):
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=str(tmp_path / "a.json"))
    reg.upsert("wifi", "http://wifi:8080", "adapter", SEED, {"devices": True})
    reg.adapters["wifi"].get_devices = AsyncMock(
        return_value={"origin": "observed", "devices": [{"id": "puppypi-01"}]}
    )
    get_position = AsyncMock(return_value=None)
    app = SimpleNamespace(state=SimpleNamespace(
        registry=reg,
        position_service=SimpleNamespace(get_position=get_position),
        floor_plan=SimpleNamespace(gps_origin=GpsOrigin(latitude=59.40, longitude=17.95)),
    ))
    await _run_until_called(app, get_position)
    # Broadcast routed puppypi-01 to the adapter that reported it, not fan-out.
    get_position.assert_awaited_with("puppypi-01", "wifi")


async def test_broadcast_falls_back_to_seed_when_no_capability(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "device_ids", "seed-tag-01")
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=str(tmp_path / "a.json"))
    reg.upsert("nocaps", "http://x:8080", "adapter", SEED, {})  # no `devices` capability
    get_position = AsyncMock(return_value=None)
    app = SimpleNamespace(state=SimpleNamespace(
        registry=reg,
        position_service=SimpleNamespace(get_position=get_position),
        floor_plan=SimpleNamespace(gps_origin=GpsOrigin(latitude=59.40, longitude=17.95)),
    ))
    await _run_until_called(app, get_position)
    # No capable adapter -> seed id with source None (legacy fan-out).
    get_position.assert_awaited_with("seed-tag-01", None)


async def test_a_slow_source_does_not_hold_back_the_other_devices(tmp_path, monkeypatch):
    """A tick waits at most one interval: the fast device is sent while the
    slow one's request is still running, and the slow one is not asked twice."""
    import json

    from app.fusion.base import FusedPosition
    from app.services.position_service import PositionResult, StrategyResult

    monkeypatch.setattr(settings, "websocket_interval_ms", 20)
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=str(tmp_path / "a.json"))
    reg.upsert("mix", "http://mix:8080", "adapter", SEED, {"devices": True})
    reg.adapters["mix"].get_devices = AsyncMock(
        return_value={"origin": "inventory", "devices": [{"id": "fast"}, {"id": "slow"}]}
    )
    fused = FusedPosition(x=1.0, y=1.0, z=None, accuracy=1.0, sources=["mix"], timestamp=1.0)
    result = PositionResult(primary=StrategyResult(name="weighted_avg", fused=fused), compare=[])
    calls = {"fast": 0, "slow": 0}

    async def get_position(did, source):
        calls[did] += 1
        if did == "slow":
            await asyncio.sleep(10)
        return result

    app = SimpleNamespace(state=SimpleNamespace(
        registry=reg,
        position_service=SimpleNamespace(get_position=get_position),
        floor_plan=SimpleNamespace(gps_origin=GpsOrigin(latitude=59.40, longitude=17.95)),
    ))
    client = _FakeWS()
    ws.manager.connections.add(client)
    task = asyncio.create_task(ws.broadcast_loop(app))
    try:
        await asyncio.sleep(0.3)
    finally:
        task.cancel()
        ws.manager.connections.discard(client)
        try:
            await task
        except asyncio.CancelledError:
            pass
    # The first frames can precede the first discovery and carry nothing.
    frames = [f for f in (json.loads(m) for m in client.sent) if f]
    assert frames and all([i["positioningId"] for i in f] == ["fast"] for f in frames)
    assert calls["slow"] == 1 and calls["fast"] > 1


async def test_a_slow_discovery_does_not_hold_back_the_frames(tmp_path, monkeypatch):
    """/devices of a vendor adapter calls its cloud. The ticks keep sending
    while a discovery is still running."""
    monkeypatch.setattr(settings, "websocket_interval_ms", 20)
    reg = AdapterRegistry(ttl_s=45.0, heartbeat_s=15.0, persist_path=str(tmp_path / "a.json"))
    reg.upsert("slowcloud", "http://slow:8080", "adapter", SEED, {"devices": True})

    async def slow_devices():
        await asyncio.sleep(10)

    reg.adapters["slowcloud"].get_devices = slow_devices
    app = SimpleNamespace(state=SimpleNamespace(
        registry=reg,
        position_service=SimpleNamespace(get_position=AsyncMock(return_value=None)),
        floor_plan=SimpleNamespace(gps_origin=GpsOrigin(latitude=59.40, longitude=17.95)),
    ))
    client = _FakeWS()
    ws.manager.connections.add(client)
    task = asyncio.create_task(ws.broadcast_loop(app))
    try:
        await asyncio.sleep(0.3)
    finally:
        task.cancel()
        ws.manager.connections.discard(client)
        try:
            await task
        except asyncio.CancelledError:
            pass
    assert len(client.sent) > 5
