"""One HTTP client per process, shared by every outbound call.

A client per call builds a TLS context, resolves the peer and opens a new
connection each time: several milliseconds on every request, inside the hop
being measured. One long-lived client keeps its connections to each peer open.
Timeouts are set per request. The client belongs to the event loop that first
uses it; a new loop, as in a test, gets its own.

Calls stay stateless as they were with a client per call: a cookie that one
peer sets is never sent back, to it or to another peer.
"""

import asyncio
import logging
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_client: Optional[httpx.AsyncClient] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


async def _without_cookies(request: httpx.Request) -> None:
    request.headers.pop("cookie", None)


# Idle connections are kept for reuse, up to 20. No ceiling on concurrent
# connections, as with a client per call.
_LIMITS = httpx.Limits(max_connections=None, max_keepalive_connections=20, keepalive_expiry=30.0)
_IDEMPOTENT = {"GET", "HEAD", "PUT", "DELETE"}


class _ReusingTransport(httpx.AsyncHTTPTransport):
    """A kept connection can be closed or reset by the peer, or a middlebox, as
    it is reused: their keep-alive ran out first. Such a request usually never
    reached the peer, so an idempotent one is sent once more, on a fresh
    connection, and the retry is logged so a slower call can be attributed. A
    request that did reach the peer runs twice, which an idempotent method
    allows."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            return await super().handle_async_request(request)
        except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError) as exc:
            if request.method not in _IDEMPOTENT:
                raise
            log.info("retrying %s %s on a new connection after %s", request.method, request.url, type(exc).__name__)
            return await super().handle_async_request(request)


def build(**kwargs) -> httpx.AsyncClient:
    kwargs.setdefault("transport", _ReusingTransport(limits=_LIMITS))
    return httpx.AsyncClient(event_hooks={"request": [_without_cookies]}, **kwargs)


def client() -> httpx.AsyncClient:
    global _client, _loop
    loop = asyncio.get_running_loop()
    if _client is None or _client.is_closed or _loop is not loop:
        _client = build()
        _loop = loop
    return _client


async def aclose() -> None:
    """Close the client at shutdown."""
    global _client, _loop
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client, _loop = None, None
