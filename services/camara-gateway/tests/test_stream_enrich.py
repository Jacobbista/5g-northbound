import json

from app.assets import Asset
from app.routers.positions_stream import _enrich


def _robot():
    return Asset(
        asset_id="robot-9", kind="forklift", org="acme",
        capabilities=[
            {"source": "wifi", "positioning_id": "wifi-9"},
            {"source": "wittra", "positioning_id": "uwb-9"},
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
    assert e["device_id"] == "wifi-9"  # primary capability id: the consumer's join key
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
    assert out[0]["device_id"] == "wifi-9"  # primary id, even when only UWB reported
    assert out[0]["latitude"] == 2.0


def test_enrich_drops_positioning_id_with_no_asset(monkeypatch):
    monkeypatch.setattr("app.routers.positions_stream.list_assets", lambda: [_robot()])
    raw = json.dumps([{"device_id": "stranger", "latitude": 5.0, "longitude": 5.0, "accuracy_m": 1.0}])
    assert json.loads(_enrich(raw)) == []
