"""Engine-facing endpoint: GET /measurement/{device_id} -> Measurement.

This is the contract the engine speaks. The adapter answers from cache when
possible, falls back to a live vendor call otherwise.
"""

import logging

from fastapi import APIRouter, HTTPException, Request

from .. import client as vendor_client
from ..mapper import map_measurement, map_stream_diagnostics
from ..register import declared_capabilities

log = logging.getLogger(__name__)

router = APIRouter(tags=["measurement"])


@router.get("/measurement/{device_id}")
async def get_measurement(device_id: str, request: Request):
    state = request.app.state.store
    schema = state.schema
    if schema is None:
        # Not configured: nothing is known about the device. Unavailable, not
        # a missing fix; /ready says why.
        raise HTTPException(503, detail="no schema loaded")

    cached = state.cache_get(device_id)
    if cached is not None:
        request.state.hop = {"cache": "hit"}
        return cached

    # Filled by the call as it happens, so the line carries it even if the
    # call fails.
    request.state.hop = {"cache": "miss"}
    # A vendor that does not answer in time is a timeout, one that answers an
    # error is a bad gateway, and one that cannot be reached is unavailable.
    # Only a vendor without a record of the device is "no fix".
    try:
        payload = await vendor_client.fetch(schema, device_id, trace=request.state.hop)
    except vendor_client.VendorTimeout as exc:
        raise HTTPException(504, detail=str(exc)) from exc
    except vendor_client.VendorError as exc:
        raise HTTPException(502, detail=str(exc)) from exc
    except vendor_client.VendorUnavailable as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(404, detail="no measurement")

    measurement, reason = map_measurement(schema.mapping, payload, schema.vendor)
    if measurement is None:
        state.observed.record_no_fix(reason)
        # Vendor answered but the record is not a fix: no position, no fix time,
        # or a confidence outside 0..1. 404 = the adapter contract's "no fix" so the engine
        # drops it this cycle (no cooldown) and the gateway maps it to
        # LOCATION_RETRIEVAL.UNABLE_TO_LOCATE.
        raise HTTPException(404, detail="no position in vendor payload")
    # Stream-tier diagnostics (motion) ride the same current-fix record, no
    # extra fetch. Namespaced under `diagnostics`; the engine carries it through.
    if schema.diagnostics is not None:
        diag = map_stream_diagnostics(schema.diagnostics, payload)
        if diag:
            measurement["diagnostics"] = diag
    state.observed.record(device_id, schema.mapping, measurement, declared_capabilities())
    state.cache_put(device_id, measurement, schema.cacheTtl)
    return measurement
