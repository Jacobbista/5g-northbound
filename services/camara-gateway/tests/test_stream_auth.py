"""The stream refuses a client after the handshake, with the close codes the
AsyncAPI publishes. A close before the handshake reaches a real client as an
HTTP 403, and the close code is lost."""

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app

STREAM = "/positions/stream"


def _closed_after_handshake(subprotocols: list[str]) -> tuple[str | None, int]:
    with TestClient(app) as client:
        with client.websocket_connect(STREAM, subprotocols=subprotocols) as ws:
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_text()
            return ws.accepted_subprotocol, closed.value.code


def test_an_invalid_token_closes_with_4401_after_echoing_the_scheme(settings_env, monkeypatch):
    async def invalid(token):
        return None

    monkeypatch.setattr("app.routers.positions_stream.validate_token", invalid)
    assert _closed_after_handshake(["bearer.jwt", "not-a-jwt"]) == ("bearer.jwt", 4401)


def test_a_gateway_without_an_engine_closes_with_1011(settings_env, monkeypatch):
    async def valid(token):
        return {"realm_access": {"roles": ["camara-location-read"]}}

    monkeypatch.setattr("app.routers.positions_stream.validate_token", valid)
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "positioning_engine_url", "")
    assert _closed_after_handshake(["bearer.jwt", "token"]) == ("bearer.jwt", 1011)
