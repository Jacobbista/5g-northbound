"""Serves this service's environment contract as JSON.

The contract has two halves. The variables the binary itself reads come from
the baked ``env.contract.yaml`` (schema only: names, descriptions,
sensitivity, ``kind``, ``external_origin``). The variables the VENDOR needs are
named by the active schema, not by this image, and are derived from it at
request time - this service is generic and is bound to one vendor by the
document an operator loads. Neither half returns runtime values or secrets.

No auth and no dependency on business configuration, so a pod that is
misconfigured (and therefore failing readiness) still answers here. That is
what lets a deploy dashboard read the contract from a live-but-unconfigured
pod and drive a setup wizard, instead of needing a separate copy of the
contract checked out somewhere.
"""

import os
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request

from ..client import IMPLEMENTED_TRANSPORTS
from ..envcontract import discover_mapping_coverage, mapping_coverage, vendor_env
from ..schema import Schema

router = APIRouter(tags=["contract"])

# First existing path wins. The image bakes the file at /app/env.contract.yaml;
# CONTRACT_PATH overrides; the repo-relative path keeps local tests working.
_CANDIDATES = [
    os.environ.get("CONTRACT_PATH"),
    "/app/env.contract.yaml",
    str(Path(__file__).resolve().parents[2] / "env.contract.yaml"),
]


def _load() -> dict:
    for candidate in _CANDIDATES:
        if candidate and Path(candidate).is_file():
            return yaml.safe_load(Path(candidate).read_text()) or {}
    raise HTTPException(status_code=500, detail="env.contract.yaml not found")


def _sanitize(entries: list) -> list:
    """Strip value-bearing fields (default, example) from sensitive entries.
    The contract is schema only: a deploy dashboard must never receive a value
    for a secret field, not even a committed placeholder default."""
    out = []
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("sensitive"):
            entry = {k: v for k, v in entry.items() if k not in ("default", "example")}
        out.append(entry)
    return out


@router.get("/contract")
def contract(request: Request) -> dict:
    raw = _load()
    # Defensive: /contract answers on a pod that is failing readiness, which
    # includes one whose lifespan has not populated the store.
    store = getattr(request.app.state, "store", None)
    schema = getattr(store, "schema", None)
    body = {
        "service": raw.get("service"),
        "kind": raw.get("kind"),
        "external_origin": raw.get("external_origin"),
        "description": raw.get("description"),
        # The binding. This image is generic; it announces a vendor's variables
        # once an operator has given it that vendor's schema.
        "configured": schema is not None,
        "vendor": schema.vendor if schema is not None else None,
        # How the adapter reaches the SOURCE, which is a different axis from
        # the `streaming` capability (whether the ENGINE is pushed to or polls
        # this adapter; it polls, always). `transports` is what the image can
        # drive, so a dashboard states it as a fact and offers a choice only
        # when there is more than one; `transport` is the one the active schema
        # picked. The full set the grammar accepts is on GET /contract/schema.
        "transports": list(IMPLEMENTED_TRANSPORTS),
        "transport": schema.transport if schema is not None else None,
        "schema_source": getattr(store, "schema_source", "none"),
        "schema": "/contract/schema",
        "mapping": mapping_coverage(schema) if schema is not None else None,
        "env": {
            "required": _sanitize(raw.get("required")) + vendor_env(schema),
            "recommended": _sanitize(raw.get("recommended")),
            "optional": _sanitize(raw.get("optional")),
        },
    }
    discover = discover_mapping_coverage(schema) if schema is not None else None
    if discover is not None:
        body["discover_mapping"] = discover
    return body


@router.get("/contract/schema")
def schema_contract() -> dict:
    return Schema.model_json_schema()
