import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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
    from .position import get_position
    from ..services.position_service import PositionService
    from ..config import settings

    interval = settings.websocket_interval_ms / 1000.0
    device_ids = [d.strip() for d in settings.device_ids.split(",") if d.strip()]

    while True:
        await asyncio.sleep(interval)
        if not manager.connections:
            continue

        svc = PositionService(app.state.adapters)
        positions = await asyncio.gather(
            *[svc.get_position(did) for did in device_ids],
            return_exceptions=True,
        )
        payload = json.dumps(
            [p.model_dump() for p in positions if not isinstance(p, Exception)]
        )

        dead: set[WebSocket] = set()
        for ws in list(manager.connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            manager.disconnect(ws)
