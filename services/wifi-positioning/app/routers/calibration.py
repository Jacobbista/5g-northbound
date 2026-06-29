"""HTTP surface for the WiFi calibration tool.

The guided UI in `placement-editor` drives the operator through:

  1. POST /calibration/capture        -> open a capture session at (x, y)
  2. GET  /calibration/capture/{id}    -> poll progress
  3. (capture closes automatically when N scans are recorded)
  4. GET  /calibration/state           -> all stored samples + flags
  5. DELETE /calibration/samples/{id}  -> remove an outlier point
  6. POST /calibration/derive          -> log-distance fit per AP
  7. POST /calibration/apply           -> write derived params into the
                                          bindings file + reload the
                                          adapter's live config

Raw scans are not pushed to this router; they flow through the regular
`/ingest/wifi-scan` endpoint and the WifiAdapter calls `store.on_ingest`
which buffers them into any open session.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ..calibration import CaptureSession
from ..models import CalibrationSample

log = logging.getLogger(__name__)
router = APIRouter(prefix="/calibration", tags=["calibration"])


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    x_m: float
    y_m: float
    target_scans: int = 10


class CaptureResponse(BaseModel):
    id: str
    x_m: float
    y_m: float
    target_scans: int
    collected: int
    done: bool


def _session_to_response(s: CaptureSession) -> CaptureResponse:
    return CaptureResponse(
        id=s.id,
        x_m=s.x_m,
        y_m=s.y_m,
        target_scans=s.target_scans,
        collected=len(s.scans),
        done=s.done,
    )


@router.post("/capture", response_model=CaptureResponse)
async def start_capture(body: CaptureRequest, request: Request) -> CaptureResponse:
    store = request.app.state.calibration
    session = store.start_capture(body.x_m, body.y_m, body.target_scans)
    return _session_to_response(session)


@router.get("/capture/{session_id}", response_model=CaptureResponse)
async def poll_capture(session_id: str, request: Request) -> CaptureResponse:
    store = request.app.state.calibration
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(404, "capture session not found")
    return _session_to_response(session)


@router.delete("/capture/{session_id}")
async def cancel_capture(session_id: str, request: Request) -> dict:
    store = request.app.state.calibration
    if not store.cancel_session(session_id):
        raise HTTPException(404, "capture session not found")
    return {"status": "cancelled", "id": session_id}


class StateResponse(BaseModel):
    samples: list[CalibrationSample]
    open_sessions: list[CaptureResponse]


@router.get("/state", response_model=StateResponse)
async def state(request: Request) -> StateResponse:
    store = request.app.state.calibration
    return StateResponse(
        samples=store.all_samples(),
        open_sessions=[_session_to_response(s) for s in store._sessions.values()],
    )


@router.delete("/samples/{sample_id}")
async def delete_sample(sample_id: str, request: Request) -> dict:
    store = request.app.state.calibration
    if not store.remove_sample(sample_id):
        raise HTTPException(404, "sample not found")
    return {"status": "ok", "id": sample_id}


@router.delete("/samples")
async def clear_samples(request: Request) -> dict:
    store = request.app.state.calibration
    store.clear_samples()
    return {"status": "ok"}


@router.post("/derive")
async def derive(request: Request) -> dict:
    """Compute per-AP `tx_power` and `path_loss_n` from the stored samples.
    Does NOT persist anything; the operator reviews the fit (and its R²)
    before pressing apply."""
    store = request.app.state.calibration
    cfg = request.app.state.wifi_config
    if cfg is None:
        raise HTTPException(503, "wifi config not loaded yet (blueprint still loading)")
    return {"per_anchor": store.derive_params(cfg)}


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    # When None, the server re-derives from the stored samples. When
    # supplied, the operator can hand-edit the values before applying.
    per_anchor: Optional[dict[str, dict]] = None


@router.post("/apply")
async def apply(body: ApplyRequest, request: Request) -> dict:
    """Write the derived `tx_power` and `path_loss_n` per binding back to
    the bindings file on disk and hot-reload the live config. The
    blueprint (positions) is not touched."""
    store = request.app.state.calibration
    cfg = request.app.state.wifi_config
    if cfg is None:
        raise HTTPException(503, "wifi config not loaded yet (blueprint still loading)")
    derived = body.per_anchor or store.derive_params(cfg)
    # Filter: only entries with non-null params are written. Anchors with
    # too few samples are simply skipped so the previous calibration (if
    # any) stays in effect.
    overrides: dict[str, dict] = {}
    for anchor_id, params in derived.items():
        if params.get("tx_power") is None or params.get("path_loss_n") is None:
            continue
        overrides[anchor_id] = {
            "tx_power": params["tx_power"],
            "path_loss_n": params["path_loss_n"],
        }

    persist = request.app.state.persist_calibration
    persist(overrides, store.all_samples())

    # Hot-reload the live wifi config so the next scan uses the new params
    # without a container restart.
    reload_cfg = request.app.state.reload_wifi_config
    new_cfg = reload_cfg()
    request.app.state.wifi_config = new_cfg
    request.app.state.adapter.reload(new_cfg)

    return {"status": "ok", "applied": overrides, "samples": len(store.all_samples())}


@router.get("/params")
async def calibration_params(request: Request):
    """Per-AP RF model params the engine actually uses: the calibration-derived
    tx_power reference + path-loss n when /derive + /apply have run, else the
    global fallback. BSSIDs are NEVER included (sensitive). Keyed by anchor id
    so a UI can show real RF instead of the blueprint's nominal placeholders."""
    cfg = request.app.state.wifi_config
    if cfg is None:
        return {"params": {}}
    out = {}
    for r in cfg.routers:
        calibrated = r.tx_power is not None
        out[r.id] = {
            "tx_power_ref_dbm": r.tx_power if calibrated else cfg.tx_power,
            "path_loss_n": r.path_loss_n if calibrated else cfg.path_loss_n,
            "calibrated": calibrated,
        }
    return {"params": out}
