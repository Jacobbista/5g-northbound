"""Per-hop latency instrumentation.

Every service on the position data path logs one structured `hop` line per
request, keyed by the `x-correlator` header, so the platform can join hops
across services into a per-stage latency breakdown. The gateway mints the
correlator (CAMARA Commonalities); internal calls propagate it with
`corr_headers()`. The log-line schema is the contract the aggregator joins on -
see docs/latency-instrumentation.md.
"""

import json
import logging
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request

# The correlator of the request currently being served, so an outbound internal
# call can propagate it without threading it through every function signature.
correlator_var: ContextVar[str] = ContextVar("x_correlator", default="")

_hop_log = logging.getLogger("hop")


def install_hop_logging(
    app: FastAPI, service: str, *, mint: bool = False, entry_paths: tuple[str, ...] = (),
) -> None:
    """Log one `hop` line per request. A request that enters the stack here
    from outside gets a correlator when it carries none, echoed on the
    response: every request with `mint=True` (the gateway), or one to a path in
    `entry_paths` (an adapter's intake from the edge)."""

    @app.middleware("http")
    async def _hop(request: Request, call_next):
        entry = mint or request.url.path in entry_paths
        cid = request.headers.get("x-correlator") or (str(uuid.uuid4()) if entry else "")
        correlator_var.set(cid)
        t_receive = time.time()
        # A request that raises is answered 500 by the server and still
        # leaves its line, so a crash is not mistaken for a missing hop.
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            t_emit = time.time()
            if cid:
                line = {
                    "event": "hop",
                    "service": service,
                    "stage": f"{request.method} {request.url.path}",
                    "correlator": cid,
                    "status": status,
                    "t_receive": round(t_receive, 6),
                    "t_emit": round(t_emit, 6),
                    "span_ms": round((t_emit - t_receive) * 1000, 3),
                }
                # Set by a route that answers from a cache or from the source
                # behind it (`hit` or `miss`), so a hit is told apart without a
                # downstream line to join on.
                cache = getattr(request.state, "cache", None)
                if cache is not None:
                    line["cache"] = cache
                _hop_log.info(json.dumps(line))
        if entry:
            response.headers["x-correlator"] = cid
        return response


def corr_headers() -> dict:
    """`x-correlator` header for an outbound internal call, propagating the
    correlator of the request currently being served. Empty when unset."""
    cid = correlator_var.get()
    return {"x-correlator": cid} if cid else {}
