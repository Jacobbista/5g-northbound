"""Outbound calls share one long-lived client, so a request does not pay for
a TLS context and a new connection to its peer."""

from pathlib import Path

import httpx
import pytest

from app import outbound


async def test_the_client_is_shared_until_it_is_closed():
    first = outbound.client()
    assert outbound.client() is first
    await outbound.aclose()
    assert first.is_closed
    assert outbound.client() is not first
    await outbound.aclose()


def test_no_module_builds_its_own_client():
    app_dir = Path(outbound.__file__).parent
    builders = [
        str(p.relative_to(app_dir)) for p in app_dir.rglob("*.py")
        if p.name not in ("outbound.py", "register.py") and "httpx.AsyncClient(" in p.read_text()
    ]
    assert builders == []


async def test_a_cookie_set_by_a_peer_is_never_sent_back():
    def peer(request):
        return httpx.Response(200, headers={"set-cookie": "session=1; Path=/"},
                              json={"cookie": request.headers.get("cookie")})

    async with outbound.build(transport=httpx.MockTransport(peer)) as c:
        await c.get("http://engine/a")
        again = await c.get("http://engine/b")
        other = await c.get("http://keycloak/c")
    assert again.json() == {"cookie": None}
    assert other.json() == {"cookie": None}


@pytest.mark.parametrize("error", [httpx.RemoteProtocolError, httpx.ReadError])
async def test_a_connection_closed_by_the_peer_on_reuse_is_retried_once(monkeypatch, error):
    attempts = []

    async def flaky(self, request):
        attempts.append(request.method)
        if len(attempts) == 1:
            raise error("the peer closed the kept connection")
        return httpx.Response(200)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", flaky)
    async with outbound.build() as c:
        assert (await c.get("http://engine/position/a")).status_code == 200
    assert attempts == ["GET", "GET"]


async def test_a_non_idempotent_request_is_not_retried(monkeypatch):
    attempts = []

    async def closed(self, request):
        attempts.append(request.method)
        raise httpx.RemoteProtocolError("the peer closed the kept connection")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", closed)
    async with outbound.build() as c:
        with pytest.raises(httpx.RemoteProtocolError):
            await c.post("http://engine/adapters", json={})
    assert attempts == ["POST"]
