"""Serves this service's environment contract as JSON.

Reads the baked ``env.contract.yaml`` (schema only: variable names,
descriptions, sensitivity, ``kind``, ``external_origin``) and returns it. It
never returns runtime values or secrets - the YAML it reads contains none.

No auth and no dependency on business configuration, so a pod that is
misconfigured (and therefore failing readiness) still answers here. That is
what lets a deploy dashboard read the contract from a live-but-unconfigured
pod and drive a setup wizard, instead of needing a separate copy of the
contract checked out somewhere.
"""

import os
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException

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
def contract() -> dict:
    raw = _load()
    return {
        "service": raw.get("service"),
        "kind": raw.get("kind"),
        "external_origin": raw.get("external_origin"),
        "description": raw.get("description"),
        "env": {
            "required": _sanitize(raw.get("required")),
            "recommended": _sanitize(raw.get("recommended")),
            "optional": _sanitize(raw.get("optional")),
        },
    }
