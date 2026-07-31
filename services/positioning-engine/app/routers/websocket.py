import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings
from ..services.discovery import resolve_broadcast_targets
from ..services.geo import local_to_gps
from ..services.position_service import ts_to_iso

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

    while True:
        await asyncio.sleep(interval)
        if not manager.connections:
            continue

        now = time.monotonic()
        if now - last_discovery >= discovery_interval:
            discovered = await resolve_broadcast_targets(app.state.registry)
            targets = discovered or {sid: None for sid in seed_ids}
            last_discovery = now

        svc = app.state.position_service
        origin = app.state.floor_plan.gps_origin
        ids = list(targets)
        results = await asyncio.gather(
            *[svc.get_position(did, targets[did]) for did in ids],
            return_exceptions=True,
        )

        payload_items = []
        for did, res in zip(ids, results):
            if isinstance(res, Exception) or res is None:
                continue
            lat, lon = local_to_gps(res.primary.fused.x, res.primary.fused.z, origin)
            alt = None
            if res.primary.fused.y is not None:
                base = origin.altitude_m if origin and origin.altitude_m is not None else 0.0
                alt = round(base + res.primary.fused.y, 3)
            payload_items.append({
                "device_id": did,
                "latitude": lat,
                "longitude": lon,
                "accuracy_m": round(res.primary.fused.accuracy_m, 4),
                "altitude_m": alt,
                "timestamp": ts_to_iso(res.primary.fused.timestamp),
                "sources": res.primary.fused.sources,
                "strategy": res.primary.name,
            })
        payload = json.dumps(payload_items)

        dead: set[WebSocket] = set()
        for ws in list(manager.connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            manager.disconnect(ws)
