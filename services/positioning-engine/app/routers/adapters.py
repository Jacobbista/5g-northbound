"""Adapter registry HTTP surface.

GET    /adapters        - health + membership snapshot (cooldown x heartbeat).
POST   /adapters        - self-registration / heartbeat (idempotent upsert).
DELETE /adapters/{name} - best-effort deregister on adapter shutdown.

No auth: the engine is ClusterIP and never externally exposed, consistent with
its existing internal-trust model. See docs/adapter-registry.md.
"""

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from ..registry import SELF, _safe_aclose

log = logging.getLogger(__name__)
router = APIRouter(tags=["adapters"])


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    base_url: str
    kind: str = "adapter"


@router.get("/adapters")
async def list_adapters(request: Request):
    """Snapshot of every registered adapter: membership (heartbeat / TTL) and
    reachability (poll cooldown), with a derived `state` the demo renders."""
    registry = request.app.state.registry
    return {"adapters": registry.status_list()}


@router.post("/adapters")
async def register_adapter(req: RegisterRequest, request: Request):
    """Register or heartbeat a self-registering adapter. Idempotent: same
    name+base_url just refreshes last_seen."""
    registry = request.app.state.registry
    orphan = registry.upsert(req.name, req.base_url, req.kind, SELF)
    registry.persist()
    if orphan is not None:
        await _safe_aclose(orphan)
    return {"status": "ok", "name": req.name, "adapters": len(registry.adapters)}


@router.delete("/adapters/{name}")
async def deregister_adapter(name: str, request: Request):
    """Deregister on adapter shutdown. 404 when the name is unknown."""
    registry = request.app.state.registry
    orphan = registry.remove(name)
    registry.persist()
    if orphan is not None:
        await _safe_aclose(orphan)
    return {"status": "ok" if orphan is not None else "absent", "name": name}
