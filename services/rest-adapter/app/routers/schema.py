"""Operator endpoint for schema get/replace.

Authentication is intentionally not enforced here - the testbed fronts the
service with a Keycloak-protected ingress (realm role `vendor-admin`, planned).
On a cluster network this endpoint is internal; in dev it is open.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from ..config import get_settings
from ..schema import Schema
from ..store import save_schema

log = logging.getLogger(__name__)

router = APIRouter(prefix="/schema", tags=["schema"])


@router.get("")
async def get_schema(request: Request):
    state = request.app.state.store
    if state.schema is None:
        raise HTTPException(404, detail="no schema loaded")
    return state.schema.model_dump(mode="json")


@router.put("")
async def put_schema(payload: dict, request: Request):
    try:
        schema = Schema.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(400, detail=exc.errors()) from exc
    save_schema(get_settings().schema_file, schema)
    request.app.state.store.schema = schema
    request.app.state.store.cache_clear()
    log.info("schema replaced; vendor=%s", schema.vendor)
    return {"status": "ok", "vendor": schema.vendor}
