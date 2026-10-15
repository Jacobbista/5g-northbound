"""Adapter registry HTTP surface.

GET    /adapters        - health + membership snapshot (cooldown x heartbeat).
POST   /adapters        - self-registration / heartbeat (idempotent upsert).
DELETE /adapters/{name} - best-effort deregister on adapter shutdown; with
                          ?instance=, only that instance leaves.

No auth: the engine is ClusterIP and never externally exposed, consistent with
its existing internal-trust model. See docs/adapter-registry.md.
"""

import logging

from fastapi import APIRouter, Request
from ..registry import SELF, _safe_aclose
from ..wire import Announcement

log = logging.getLogger(__name__)
router = APIRouter(tags=["adapters"])


@router.get("/adapters")
async def list_adapters(request: Request):
    """Snapshot of every registered adapter: membership (heartbeat / TTL) and
    reachability (poll cooldown), with a derived `state` the demo renders."""
    registry = request.app.state.registry
    return {"adapters": registry.status_list()}


@router.post("/adapters")
async def register_adapter(req: Announcement, request: Request):
    """Register or heartbeat a self-registering adapter. Idempotent: same
    name+baseUrl just refreshes lastSeen."""
    registry = request.app.state.registry
    # Stored as declared: an omitted trait stays omitted.
    orphan = registry.upsert(
        req.name, req.baseUrl, req.kind, SELF, req.capabilities.model_dump(exclude_unset=True), req.instance,
    )
    registry.persist()
    if orphan is not None:
        await _safe_aclose(orphan)
    return {"status": "ok", "name": req.name, "adapters": len(registry.adapters)}


@router.delete("/adapters/{name}")
async def deregister_adapter(name: str, request: Request, instance: str | None = None):
    """Deregister on adapter shutdown. An instance removes only itself: the
    adapter stays registered while another of its instances runs, as in a
    rolling update where the new pod registers before the old one stops."""
    registry = request.app.state.registry
    removed, orphan = registry.remove(name, instance)
    registry.persist()
    if orphan is not None:
        await _safe_aclose(orphan)
    registered = name in registry.adapters
    status = "ok" if removed else ("kept" if registered else "absent")
    return {"status": status, "name": name, "registered": registered}
