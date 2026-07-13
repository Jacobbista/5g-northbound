"""HTTP surface for the per-venue bindings file as a config resource.

The bindings file (`wifi-config.json`: BSSIDs + RF tunables + calibration
samples) is the portable calibration artefact. An operator calibrates on one
cluster (e.g. the demo), exports the file, and imports it on the testbed.

  GET  /bindings   -> the current file, full fidelity (BSSIDs included)
  PUT  /bindings   -> replace the file wholesale + hot-reload

Replace-semantics, mirroring the engine's PUT /blueprint and rest-adapter's
PUT /schema: the uploaded document is authoritative.

BSSIDs are sensitive (real network MACs). This surface is the OPERATOR plane
only - reached through the placement-editor behind `placement-admin`. It is
never proxied to the demo / gateway; the bssid-free `/calibration/params` and
the gateway's `/anchors/calibration` stay the read paths for untrusted clients.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from ..assemble import bindings_from_dict, load_bindings, write_bindings
from ..models import WifiBindings

log = logging.getLogger(__name__)
router = APIRouter(tags=["bindings"])


@router.get("/bindings", response_model=WifiBindings)
async def get_bindings(request: Request) -> WifiBindings:
    """Export the live per-venue bindings, BSSIDs included. Empty document
    when nothing is seeded yet."""
    return load_bindings(request.app.state.bindings_path)


@router.put("/bindings")
async def put_bindings(request: Request) -> dict:
    """Replace the per-venue bindings file and hot-reload the live config.
    Accepts the current `bindings[]` shape or a legacy `routers[]` config. When
    the adapter is still loading the blueprint the new bindings are persisted
    and picked up on the next successful config load."""
    raw = await request.body()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "body must be a JSON object")
    try:
        bindings = bindings_from_dict(data)
    except ValidationError as exc:
        raise HTTPException(422, f"not a valid bindings document: {exc}") from exc

    write_bindings(request.app.state.bindings_path, bindings)

    # The imported document carries its own samples; swap them into the store
    # without re-persisting (the file we just wrote already has them).
    store = getattr(request.app.state, "calibration", None)
    if store is not None:
        store.replace_samples(bindings.calibration_samples)

    # Hot-reload only when the adapter is up; otherwise the self-heal loop
    # picks the new bindings up once the blueprint loads.
    reloaded = False
    reload_cfg = getattr(request.app.state, "reload_wifi_config", None)
    adapter = getattr(request.app.state, "adapter", None)
    if reload_cfg is not None and adapter is not None:
        new_cfg = reload_cfg()
        request.app.state.wifi_config = new_cfg
        adapter.reload(new_cfg)
        reloaded = True

    return {
        "status": "ok",
        "bindings": len(bindings.bindings),
        "samples": len(bindings.calibration_samples),
        "reloaded": reloaded,
    }
