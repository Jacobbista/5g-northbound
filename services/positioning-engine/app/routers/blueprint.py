"""Blueprint authority HTTP surface.

GET /blueprint  - read the canonical blueprint (raw layout.json shape). Always
                  answers; 404 when none has been authored yet, so read-clients
                  (adapters, demo via the gateway proxy) retry and boot degraded
                  rather than crashing.
PUT /blueprint  - replace the blueprint. Write control is the placement-editor's
                  front-door gate (oauth2-proxy / admin), NOT this endpoint: the
                  engine is ClusterIP and never externally exposed, so an
                  internal PUT is consistent with its existing no-auth internal
                  trust model. Documented in docs/blueprint-vs-bindings.md.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..blueprint import floor_plan_from_blueprint, save_blueprint, validate_blueprint
from ..config import settings

log = logging.getLogger(__name__)
router = APIRouter(tags=["blueprint"])


@router.get("/blueprint")
async def get_blueprint(request: Request) -> dict[str, Any]:
    raw = getattr(request.app.state, "blueprint", None)
    if raw is None:
        raise HTTPException(status_code=404, detail="no blueprint authored yet")
    return raw


@router.put("/blueprint")
async def put_blueprint(request: Request, raw: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_blueprint(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"blueprint schema violation: {exc}") from exc
    try:
        save_blueprint(settings.blueprint_path, raw)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"blueprint not persisted: {exc}") from exc
    request.app.state.blueprint = raw
    # Re-derive the georef and swap it into the live position service so the new
    # gps_origin takes effect without a restart.
    fp = floor_plan_from_blueprint(raw)
    request.app.state.floor_plan = fp
    svc = getattr(request.app.state, "position_service", None)
    if svc is not None:
        svc.set_floor_plan(fp)
    n_fp = len(raw.get("floor_plans") or [])
    n_rooms = len(raw.get("rooms") or [])
    log.info(
        "blueprint updated via PUT (floor_plans=%d rooms=%d gps_origin=%s)",
        n_fp, n_rooms, "set" if fp.gps_origin else "absent",
    )
    return {"status": "ok", "floor_plans": n_fp, "rooms": n_rooms,
            "gps_origin": "set" if fp.gps_origin else "absent"}
