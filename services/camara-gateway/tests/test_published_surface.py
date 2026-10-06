"""The gateway serves what the profile publishes, and nothing it does not.

Every route is declared in one of the published documents, and every stream
message conforms to the AsyncAPI. A route or a field added without its
declaration fails here.
"""

import copy
import importlib
import json
import pkgutil
import re
from pathlib import Path

import pytest
import yaml
from fastapi import APIRouter
from jsonschema import Draft7Validator
from starlette.routing import Mount, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app as app_package
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
    """HTTP operations from the app's own OpenAPI document. WebSocket routes
    from every router the gateway's modules define, and from the app itself:
    a router's own `routes` hold its declarations with the prefix applied,
    while `app.routes` wraps included routers differently across FastAPI
    versions. A router that is defined but never included counts as served,
    so an unpublished declaration fails here even before it is mounted."""
    ops = {(m.upper(), _norm(p))
           for p, item in app.openapi()["paths"].items() for m in item if m in _METHODS}
    routers = [app.router]
    for info in pkgutil.walk_packages(app_package.__path__, app_package.__name__ + "."):
        module = importlib.import_module(info.name)
        routers += [v for v in vars(module).values() if isinstance(v, APIRouter)]
    for router in routers:
        ops |= {("WS", _norm(r.path)) for r in router.routes if isinstance(r, WebSocketRoute)}
    return ops


def test_the_published_stream_rejects_a_connection_without_a_token(settings_env):
    """The declaration found above is live: the stream answers, and without
    a token closes with the profile's authentication code."""
    stream = yaml.safe_load((PROFILE / "asyncapi-stream.yaml").read_text())
    for channel in stream["channels"].values():
        with TestClient(app) as client, pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect(channel["address"]) as ws:
                ws.receive_text()
        assert closed.value.code == 4401, channel["address"]


def test_the_gateway_mounts_no_sub_application():
    """A mounted application serves routes that neither the OpenAPI document
    nor the routers above list, so the surface check could not see them."""
    assert not [r for r in app.routes if isinstance(r, Mount)]


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
