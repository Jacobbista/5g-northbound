"""The gateway serves what the profile publishes, and nothing it does not.

Every route is declared in one of the published documents, and every stream
message conforms to the AsyncAPI. A route or a field added without its
declaration fails here.
"""

import copy
import json
import re
from pathlib import Path

import yaml
from jsonschema import Draft7Validator

from app.assets import Asset
from app.main import app
from app.routers.positions_stream import _enrich

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "spec" / "private-profile"
BASE = Path(__file__).resolve().parents[1] / "spec"

# Service plumbing, not profile surface: liveness and the self-description.
_INFRA = {("GET", p) for p in ("/health", "/contract", "/contracts", "/contracts/{}")}
_METHODS = {"get", "put", "post", "delete", "patch"}


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _openapi_operations(doc: Path) -> set[tuple[str, str]]:
    spec = yaml.safe_load(doc.read_text())
    prefix = ""
    servers = spec.get("servers") or []
    if servers and "{apiRoot}" in servers[0]["url"]:
        prefix = servers[0]["url"].replace("{apiRoot}", "")
    return {(m.upper(), _norm(prefix + p))
            for p, item in spec["paths"].items() for m in item if m in _METHODS}


def _published() -> set[tuple[str, str]]:
    ops = set()
    for doc in (BASE / "location-retrieval.yaml", BASE / "location-verification.yaml",
                PROFILE / "extensions.yaml", PROFILE / "device-diagnostics.yaml"):
        ops |= _openapi_operations(doc)
    stream = yaml.safe_load((PROFILE / "asyncapi-stream.yaml").read_text())
    ops |= {("WS", _norm(c["address"])) for c in stream["channels"].values()}
    return ops


def _served() -> set[tuple[str, str]]:
    ops = set()
    for r in app.routes:
        if not getattr(r, "include_in_schema", True):
            continue
        methods = getattr(r, "methods", None) or {"WS"}
        ops |= {(m, _norm(r.path)) for m in methods if m != "HEAD"}
    return ops


def test_every_gateway_route_is_published():
    undeclared = _served() - _published() - _INFRA
    assert not undeclared, f"routes absent from the published specs: {sorted(undeclared)}"


def test_every_published_route_is_served():
    missing = _published() - _served()
    assert not missing, sorted(missing)


def _json_schema(node):
    """OpenAPI `nullable` as JSON Schema, which has no such keyword."""
    if isinstance(node, dict):
        out = {k: _json_schema(v) for k, v in node.items() if k != "nullable"}
        if node.get("nullable") and "type" in out:
            out["type"] = [out["type"], "null"]
        return out
    if isinstance(node, list):
        return [_json_schema(v) for v in node]
    return node


def _event_validator() -> Draft7Validator:
    spec = yaml.safe_load((PROFILE / "asyncapi-stream.yaml").read_text())
    event = copy.deepcopy(spec["components"]["schemas"]["PositionEvent"])
    event["additionalProperties"] = False
    return Draft7Validator(_json_schema(event))


def test_stream_messages_conform_to_the_asyncapi(monkeypatch):
    asset = Asset(assetId="robot-9", kind="forklift", org="acme",
                  capabilities=[{"source": "wifi", "positioningId": "wifi-9"},
                                {"source": "wittra", "positioningId": "uwb-9"}])
    monkeypatch.setattr("app.routers.positions_stream.list_assets", lambda: [asset])
    engine_item = {
        "positioningId": "uwb-9", "latitude": 59.4, "longitude": 17.9,
        "accuracy": 0.5, "altitude": None, "timestamp": "2026-09-27T10:00:00Z",
        "observedAt": "2026-09-27T10:00:01Z", "lastCommunicationTime": "2026-09-27T10:00:00Z",
        "sources": ["wittra"], "strategy": "weighted_avg", "diagnostics": {"moving": False},
    }
    validator = _event_validator()
    for batch in ([engine_item], [engine_item, {**engine_item, "positioningId": "wifi-9", "accuracy": 3.0}]):
        for event in json.loads(_enrich(json.dumps(batch))):
            errors = [e.message for e in validator.iter_errors(event)]
            assert not errors, errors
