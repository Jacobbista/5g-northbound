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


def install_hop_logging(app: FastAPI, service: str, *, mint: bool = False) -> None:
    """Log one `hop` line per request. `mint=True` (the gateway) generates a
    correlator when the client sends none and echoes it on the response."""

    @app.middleware("http")
    async def _hop(request: Request, call_next):
        cid = request.headers.get("x-correlator") or (str(uuid.uuid4()) if mint else "")
        correlator_var.set(cid)
        t_receive = time.time()
        response = await call_next(request)
        t_emit = time.time()
        if cid:
            _hop_log.info(json.dumps({
                "event": "hop",
                "service": service,
                "stage": f"{request.method} {request.url.path}",
                "correlator": cid,
                "status": response.status_code,
                "t_receive": round(t_receive, 6),
                "t_emit": round(t_emit, 6),
                "span_ms": round((t_emit - t_receive) * 1000, 3),
            }))
        if mint:
            response.headers["x-correlator"] = cid
        return response


def corr_headers() -> dict:
    """`x-correlator` header for an outbound internal call, propagating the
    correlator of the request currently being served. Empty when unset."""
    cid = correlator_var.get()
    return {"x-correlator": cid} if cid else {}
