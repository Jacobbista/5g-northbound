"""Gateway side of the live positions WebSocket.

The browser demo cannot talk to the positioning engine directly (the demo
is a MEC application, the engine is an internal service). The gateway
opens a single upstream connection to the engine's broadcast WebSocket
and forwards every payload to authenticated browser clients.

Each browser client opens `ws[s]://<gateway>/positions/stream?token=<jwt>`.
Token is supplied as a query parameter because browsers cannot set
`Authorization` headers on WebSocket handshakes. The token is validated
against the same Keycloak realm + required role as the REST endpoints.
"""

import asyncio
import logging
from urllib.parse import urlparse

import websockets
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from ..auth import validate_token
from ..config import get_settings

log = logging.getLogger(__name__)
router = APIRouter(tags=["positions-stream"])

_CONNECT_TIMEOUT_S = 5.0


def _engine_ws_url() -> str:
    base = get_settings().positioning_engine_url.rstrip("/")
    if not base:
        return ""
    parsed = urlparse(base)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    netloc = parsed.netloc or parsed.path
    path = "" if parsed.netloc else ""
    return f"{scheme}://{netloc}{path}/ws/positions"


@router.websocket("/positions/stream")
async def positions_stream(websocket: WebSocket, token: str = Query(default="")):
    claims = await validate_token(token)
    if claims is None:
        # 4401 is a custom application-layer close code (4000-4999 range
        # is reserved for app use by the WS spec). Browser EventSource-
        # style clients see this as a clean close, not a network error.
        await websocket.close(code=4401, reason="unauthenticated")
        return

    engine_url = _engine_ws_url()
    if not engine_url:
        await websocket.close(code=1011, reason="positioning_engine_url not configured")
        return

    await websocket.accept()
    log.info("positions_stream: client connected, upstream=%s", engine_url)

    try:
        async with websockets.connect(engine_url, open_timeout=_CONNECT_TIMEOUT_S) as upstream:

            async def pump_upstream_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            forward_task = asyncio.create_task(pump_upstream_to_client())

            try:
                # The client doesn't need to send anything; we read just
                # to detect a disconnect (FastAPI raises WebSocketDisconnect
                # the moment the browser closes the socket).
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                log.info("positions_stream: client disconnected")
            finally:
                forward_task.cancel()
                try:
                    await forward_task
                except (asyncio.CancelledError, ConnectionClosed):
                    pass
    except (OSError, asyncio.TimeoutError, ConnectionClosed) as exc:
        log.warning("positions_stream: upstream connection failed: %s", exc)
        try:
            await websocket.close(code=1011, reason="upstream unavailable")
        except Exception:
            pass
