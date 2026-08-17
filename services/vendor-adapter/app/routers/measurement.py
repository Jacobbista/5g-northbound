"""Engine-facing endpoint: GET /measurement/{device_id} -> Measurement.

This is the contract the engine speaks. The adapter answers from cache when
possible, falls back to a live vendor call otherwise.
"""

import logging

from fastapi import APIRouter, HTTPException, Request

from .. import client as vendor_client
from ..mapper import to_measurement

log = logging.getLogger(__name__)

router = APIRouter(tags=["measurement"])


@router.get("/measurement/{device_id}")
async def get_measurement(device_id: str, request: Request):
    state = request.app.state.store
    schema = state.schema
    if schema is None:
        # Adapter is not configured yet - looks like 'no fix' to the engine,
        # which is the right semantic: the engine simply skips this source on
        # this cycle without entering cooldown.
        raise HTTPException(404, detail="no schema loaded")

    cached = state.cache_get(device_id)
    if cached is not None:
        return cached

    payload = await vendor_client.fetch(schema, device_id)
    if payload is None:
        raise HTTPException(404, detail="no measurement")

    measurement = to_measurement(schema.mapping, payload, schema.vendor)
    state.cache_put(device_id, measurement, schema.cache_ttl_s)
    return measurement
