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
import json
import logging
from urllib.parse import urlparse

import websockets
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosed

from ..assets import list_assets
from ..auth import consumer_org, validate_token
from ..config import get_settings

log = logging.getLogger(__name__)
router = APIRouter(tags=["positions-stream"])

_CONNECT_TIMEOUT_S = 5.0


def _enrich(raw: str, org: str | None = None) -> str:
    """Turn the engine's positioning_id-keyed broadcast into the profile's
    asset-shaped stream. Each broadcast item is keyed by a positioning id; an
    asset may own several (one per capability), so items are grouped by asset
    and a multi-capability asset's fixes are fused into one entry (same
    inverse-variance model as the pull path). Items with no registered asset are
    dropped - the private-asset surface never exposes a raw positioning id with
    no asset behind it. When `org` is set (tenant-scoped token), assets outside
    that org are dropped. `device_id` is kept so existing consumers that key on
    it still work. Non-JSON / unexpected shapes pass through unchanged."""
    from ..fusion import fuse_fixes

    try:
        items = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(items, list):
        return raw
    by_pid = {cap.positioning_id: a for a in list_assets() for cap in a.capabilities}
    groups: dict[str, dict] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        asset = by_pid.get(it.get("device_id"))
        if asset is None or (org and asset.org != org):
            continue
        groups.setdefault(asset.asset_id, {"asset": asset, "items": []})["items"].append(it)

    out = []
    for group in groups.values():
        asset = group["asset"]
        entries = group["items"]
        if len(entries) == 1:
            base = dict(entries[0])
        else:
            fused = fuse_fixes([{**it, "altitude": it.get("altitude_m")} for it in entries])
            if fused is None:
                continue
            base = dict(min(entries, key=lambda it: it.get("accuracy_m") or float("inf")))
            base["latitude"] = fused["latitude"]
            base["longitude"] = fused["longitude"]
            base["accuracy_m"] = fused["accuracy_m"]
            base["sources"] = fused["sources"]
            if fused.get("altitude") is not None:
                base["altitude_m"] = fused["altitude"]
            if fused.get("timestamp") is not None:
                base["timestamp"] = fused["timestamp"]
            if fused.get("observed_at") is not None:
                base["observed_at"] = fused["observed_at"]
        base.update({
            # One stable key per asset: its primary capability's positioning id,
            # the same id a consumer joins the asset by. A fused entry keeps it
            # even though several capabilities contributed.
            "device_id": asset.primary.positioning_id,
            "assetId": asset.asset_id,
            "source": asset.source,
            "kind": asset.kind,
            "org": asset.org,
        })
        out.append(base)
    return json.dumps(out)


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
    org = consumer_org(claims)
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
                        # Enrich engine positioning_id payloads into asset-shaped
                        # events (assetId + source/kind/org), dropping unregistered
                        # ids and anything outside the consumer's tenant.
                        await websocket.send_text(_enrich(message, org))

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
