import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings
from ..services.discovery import resolve_broadcast_targets
from ..services.geo import local_to_gps, venue_altitude
from ..services.position_service import now_iso, ts_to_iso

log = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    def __init__(self):
        self.connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self.connections.discard(ws)


manager = ConnectionManager()


def build_payload_item(did, res, origin):
    """One broadcast item from a fused result. `timestamp` is the fix time
    (freezes for a stationary asset); `observed_at` is this tick; `lastSeen` is
    when the device last communicated with its source, present only when a
    source reports it. Liveness is derived from `lastSeen`, never from
    `observed_at` (which is fresh on every tick) or `timestamp` (which freezes).
    `diagnostics` (stream tier, e.g. motion) is attached only when the routed
    source reports it."""
    lat, lon = local_to_gps(res.primary.fused.x, res.primary.fused.y, origin)
    alt = venue_altitude(res.primary.fused.z, origin)
    item = {
        "positioningId": did,
        "latitude": lat,
        "longitude": lon,
        "accuracy": round(res.primary.fused.accuracy, 4),
        "altitude": alt,
        "timestamp": ts_to_iso(res.primary.fused.timestamp),
        "observedAt": now_iso(),
        "sources": res.primary.fused.sources,
        "strategy": res.primary.name,
    }
    va = res.primary.fused.verticalAccuracy
    if alt is not None and va is not None:
        item["verticalAccuracy"] = round(va, 4)
    lastSeen = getattr(res.primary.fused, "lastSeen", None)
    if lastSeen is not None:
        item["lastCommunicationTime"] = ts_to_iso(lastSeen)
    diag = getattr(res.primary.fused, "diagnostics", None)
    if diag:
        item["diagnostics"] = diag
    return item


@router.websocket("/ws/positions")
async def ws_positions(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def broadcast_loop(app):
    interval = settings.websocket_interval_ms / 1000.0
    discovery_interval = settings.device_discovery_interval_s
    # Static seed: used only when no adapter advertises the `devices`
    # capability, so a minimal engine still broadcasts (source unset -> the
    # legacy fan-out-and-fuse path).
    seed_ids = [d.strip() for d in settings.device_ids.split(",") if d.strip()]

    # positioning_id -> source (None means fan out). Learned from adapter
    # capability and refreshed on its own cadence, not every broadcast tick -
    # /devices polling must not run at the broadcast rate.
    targets: dict[str, Optional[str]] = {}
    last_discovery = -discovery_interval  # force discovery on the first tick
    # One position request in flight per device. A tick waits at most one
    # interval, sends what has arrived, and leaves a slow request running: a
    # source that takes its whole budget delays only its own devices, which
    # join the frame of the tick in which their answer arrives.
    inflight: dict[str, asyncio.Task] = {}
    discovery: Optional[asyncio.Task] = None

    def _finished(did: str) -> Optional[object]:
        """Collect a finished request, retrieving its outcome."""
        task = inflight.pop(did)
        if task.cancelled() or task.exception() is not None:
            return None
        return task.result()

    loop = asyncio.get_running_loop()
    next_tick = loop.time()
    try:
        while True:
            # Ticks keep one interval apart, however long the previous one
            # waited for answers.
            next_tick = max(next_tick + interval, loop.time())
            await asyncio.sleep(next_tick - loop.time())
            if not manager.connections:
                # Nobody listens: an answer that arrives now would be stale by
                # the time a client connects.
                for did in [d for d, t in inflight.items() if t.done()]:
                    _finished(did)
                continue

            # Discovery asks every adapter's /devices, which a vendor adapter
            # answers by calling its cloud. It runs beside the ticks, and the
            # ticks use the targets it last found.
            now = time.monotonic()
            if discovery is not None and discovery.done():
                if not discovery.cancelled() and discovery.exception() is None:
                    targets = discovery.result() or {sid: None for sid in seed_ids}
                discovery = None
            if discovery is None and now - last_discovery >= discovery_interval:
                discovery = asyncio.create_task(resolve_broadcast_targets(app.state.registry))
                last_discovery = now

            svc = app.state.position_service
            origin = app.state.floor_plan.gps_origin
            if origin is None:
                # No georeference, no WGS84 position to broadcast.
                continue
            for did, source in targets.items():
                if did not in inflight:
                    inflight[did] = asyncio.create_task(svc.get_position(did, source))
            if inflight:
                # Wait for answers until the next tick is due, not longer.
                await asyncio.wait(list(inflight.values()), timeout=max(0.0, next_tick + interval - loop.time()))

            payload_items = []
            for did in [d for d, t in inflight.items() if t.done()]:
                res = _finished(did)
                if res is not None and did in targets:
                    payload_items.append(build_payload_item(did, res, origin))
            payload = json.dumps(payload_items)

            dead: set[WebSocket] = set()
            for ws in list(manager.connections):
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.add(ws)
            for ws in dead:
                manager.disconnect(ws)
    finally:
        for task in [*inflight.values(), *([discovery] if discovery is not None else [])]:
            task.cancel()

