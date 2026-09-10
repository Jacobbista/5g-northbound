import json

from app.assets import Asset
from app.routers.positions_stream import _enrich, _ws_token


def test_ws_token_read_from_subprotocol_carrier():
    token, proto = _ws_token("bearer.jwt, ey.abc.def")
    assert token == "ey.abc.def"
    assert proto == "bearer.jwt"


def test_ws_token_absent_carrier_fails():
    token, proto = _ws_token("")
    assert token == ""
    assert proto is None


def test_ws_token_ignores_unrelated_subprotocol():
    token, proto = _ws_token("chat, superchat")
    assert token == ""
    assert proto is None


def _robot():
    return Asset(
        assetId="robot-9", kind="forklift", org="acme",
        capabilities=[
            {"source": "wifi", "positioningId": "wifi-9"},
            {"source": "wittra", "positioningId": "uwb-9"},
        ],
    )


def test_enrich_fuses_multi_capability_into_one_entry(monkeypatch):
    monkeypatch.setattr("app.routers.positions_stream.list_assets", lambda: [_robot()])
    raw = json.dumps([
        {"device_id": "wifi-9", "latitude": 0.0, "longitude": 0.0, "accuracy_m": 3.0, "sources": ["wifi"]},
        {"device_id": "uwb-9", "latitude": 1.0, "longitude": 1.0, "accuracy_m": 0.5, "sources": ["wittra"]},
    ])
    out = json.loads(_enrich(raw))
    assert len(out) == 1  # two positioning ids, one asset entry
    e = out[0]
    assert e["assetId"] == "robot-9"
    assert e["positioningId"] == "wifi-9"  # primary capability id: the consumer's join key
    assert e["latitude"] > 0.9  # fused toward the sharp UWB fix
    assert set(e["sources"]) == {"wifi", "wittra"}


def test_enrich_one_capability_present_stays_located(monkeypatch):
    monkeypatch.setattr("app.routers.positions_stream.list_assets", lambda: [_robot()])
    # Only the UWB capability reports this tick.
    raw = json.dumps([
        {"device_id": "uwb-9", "latitude": 2.0, "longitude": 2.0, "accuracy_m": 0.5, "sources": ["wittra"]},
    ])
    out = json.loads(_enrich(raw))
    assert len(out) == 1
    assert out[0]["assetId"] == "robot-9"
    assert out[0]["positioningId"] == "wifi-9"  # primary id, even when only UWB reported
    assert out[0]["latitude"] == 2.0


def test_enrich_drops_positioning_id_with_no_asset(monkeypatch):
    monkeypatch.setattr("app.routers.positions_stream.list_assets", lambda: [_robot()])
    raw = json.dumps([{"device_id": "stranger", "latitude": 5.0, "longitude": 5.0, "accuracy_m": 1.0}])
    assert json.loads(_enrich(raw)) == []


def test_fused_item_takes_the_most_recent_last_seen_across_sources(monkeypatch):
    # The AsyncAPI promises "the most recent across the fused sources". The
    # fused branch copied the most ACCURATE entry's value instead, so a quiet
    # high-accuracy source hid a recent report from a coarser one.
    monkeypatch.setattr("app.routers.positions_stream.list_assets", lambda: [_robot()])
    raw = json.dumps([
        {"device_id": "wifi-9", "latitude": 0.0, "longitude": 0.0, "accuracy_m": 3.0,
         "sources": ["wifi"], "last_seen": "2026-01-01T00:10:00Z"},
        {"device_id": "uwb-9", "latitude": 1.0, "longitude": 1.0, "accuracy_m": 0.5,
         "sources": ["wittra"], "last_seen": "2026-01-01T00:01:00Z"},
    ])
    out = json.loads(_enrich(raw))
    assert out[0]["lastCommunicationTime"] == "2026-01-01T00:10:00Z"


def test_a_single_capability_entry_keeps_its_own_last_seen(monkeypatch):
    monkeypatch.setattr("app.routers.positions_stream.list_assets", lambda: [_robot()])
    raw = json.dumps([
        {"device_id": "wifi-9", "latitude": 0.0, "longitude": 0.0, "accuracy_m": 3.0,
         "sources": ["wifi"], "last_seen": "2026-01-01T00:10:00Z"},
    ])
    out = json.loads(_enrich(raw))
    assert out[0]["lastCommunicationTime"] == "2026-01-01T00:10:00Z"
