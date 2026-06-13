import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings
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
    device_ids = [d.strip() for d in settings.device_ids.split(",") if d.strip()]

    while True:
        await asyncio.sleep(interval)
        if not manager.connections:
            continue

        svc = app.state.position_service
        origin = app.state.floor_plan.gps_origin
        results = await asyncio.gather(
            *[svc.get_position(did) for did in device_ids],
            return_exceptions=True,
        )

        payload_items = []
        for did, res in zip(device_ids, results):
            if isinstance(res, Exception) or res is None:
                continue
            lat, lon = local_to_gps(res.primary.fused.x, res.primary.fused.z, origin)
            payload_items.append({
                "device_id": did,
                "latitude": lat,
                "longitude": lon,
                "accuracy_m": round(res.primary.fused.accuracy_m, 4),
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
