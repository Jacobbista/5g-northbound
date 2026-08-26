"""On-demand vendor diagnostics: GET /diagnostics/{device_id}.

A private-profile extension surface, not CAMARA Device Location. Fetches the
schema's on_demand diagnostics sources and returns their merged mapping."""

from fastapi import APIRouter, HTTPException, Request

from .. import client as vendor_client
from ..mapper import map_fetch_diagnostics

router = APIRouter(tags=["diagnostics"])


@router.get("/diagnostics/{device_id}")
async def get_diagnostics(device_id: str, request: Request):
    schema = request.app.state.store.schema
    if schema is None or schema.diagnostics is None or not schema.diagnostics.on_demand:
        raise HTTPException(404, detail="no diagnostics configured")
    merged: dict = {}
    for fetch in schema.diagnostics.on_demand:
        payload = await vendor_client.fetch_path(schema, device_id, fetch.path, fetch.path_vars)
        if payload is None:
            continue
        merged.update(map_fetch_diagnostics(fetch, payload))
    if not merged:
        raise HTTPException(404, detail="no diagnostics available")
    return {"device_id": device_id, "diagnostics": merged}
