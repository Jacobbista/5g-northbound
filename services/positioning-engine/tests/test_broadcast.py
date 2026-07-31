import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
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
        floor_plan=SimpleNamespace(gps_origin=None),
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
        floor_plan=SimpleNamespace(gps_origin=None),
    ))
    await _run_until_called(app, get_position)
    # No capable adapter -> seed id with source None (legacy fan-out).
    get_position.assert_awaited_with("seed-tag-01", None)
