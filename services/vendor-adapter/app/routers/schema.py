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
from ..vocabulary import is_core

log = logging.getLogger(__name__)

router = APIRouter(prefix="/schema", tags=["schema"])


def _x_vendor_keys(schema: Schema) -> list[str]:
    """Diagnostics mapping keys that route to `x_vendor` (not a core field, and
    not the derivation-only `speed`). A typo of a core name shows up here."""
    diag = schema.diagnostics
    if diag is None:
        return []
    keys: set[str] = {k for k in diag.stream if not is_core(k) and k != "speed"}
    for fetch in diag.on_demand:
        keys |= {k for k in fetch.mapping if not is_core(k) and k != "speed"}
    return sorted(keys)


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
    # Apply live FIRST: the hot-reload always works, even when the schema volume
    # is read-only (ConfigMap/subPath). Persistence is best-effort so a
    # read-only mount does not turn a valid PUT into a 500.
    request.app.state.store.schema = schema
    request.app.state.store.cache_clear()
    persisted = save_schema(get_settings().schema_file, schema)
    log.info("schema replaced; vendor=%s persisted=%s", schema.vendor, persisted)
    resp = {
        "status": "ok",
        "vendor": schema.vendor,
        "persisted": persisted,
        "x_vendor_keys": _x_vendor_keys(schema),
    }
    if not persisted:
        resp["warning"] = (
            "schema applied live but NOT persisted: its volume is read-only "
            "(ConfigMap/subPath). Edit the ConfigMap and restart to make it "
            "durable, or mount the schema on a writable volume."
        )
    return resp
