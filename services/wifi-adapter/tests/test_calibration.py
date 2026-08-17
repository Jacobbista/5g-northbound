import json
import math
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.assemble import persist_calibration
from app.calibration import CalibrationStore
from app.models import CalibrationSample, Router, WifiConfig


def _cfg(routers):
    return WifiConfig(
        room_w=20,
        room_h=10,
        tx_power=-42,
        path_loss_n=2.7,
        routers=routers,
    )


def test_capture_session_aggregates_after_target_scans():
    store = CalibrationStore()
    sess = store.start_capture(x_m=5.0, y_m=5.0, target_scans=3)
    store.on_ingest("d1", {"AA:BB:CC:00:01:01": -50}, 0.0)
    store.on_ingest("d1", {"AA:BB:CC:00:01:01": -52, "AA:BB:CC:00:02:01": -70}, 1.0)
    assert not sess.done
    store.on_ingest("d1", {"AA:BB:CC:00:01:01": -54, "AA:BB:CC:00:02:01": -72}, 2.0)
    assert sess.done
    samples = store.all_samples()
    assert len(samples) == 1
    s = samples[0]
    assert s.x_m == 5.0 and s.y_m == 5.0
    assert s.n_scans == 3
    assert pytest.approx(s.rssi_by_anchor["AA:BB:CC:00:01:01"], rel=1e-3) == -52.0
    # Only 2 of 3 scans contained AP02; average over the two it appeared in.
    assert pytest.approx(s.rssi_by_anchor["AA:BB:CC:00:02:01"], rel=1e-3) == -71.0


def test_cancel_session_drops_open_capture():
    store = CalibrationStore()
    sess = store.start_capture(0, 0, 5)
    assert store.cancel_session(sess.id)
    store.on_ingest("d1", {"X": -50}, 0.0)
    assert store.all_samples() == []


def test_derive_fits_log_distance_per_anchor():
    # AP01 at (0, 0). Synthesise 5 samples along x with the known model:
    # RSSI(d) = -35 - 10 * 3.5 * log10(d)
    bssid = "AA:BB:CC:00:01:01"
    routers = [Router(id="AP01", x=0.0, y=0.0, bssids=[bssid])]
    cfg = _cfg(routers)
    store = CalibrationStore()
    for d in (1.0, 2.0, 3.0, 5.0, 8.0):
        rssi = -35 - 10 * 3.5 * math.log10(d)
        store.add_sample(CalibrationSample(
            id=f"s{int(d)}",
            x_m=d,
            y_m=0.0,
            rssi_by_anchor={bssid: rssi},
            n_scans=1,
            ts=0.0,
        ))

    derived = store.derive_params(cfg)
    assert "AP01" in derived
    res = derived["AP01"]
    assert res["n_points"] == 5
    assert pytest.approx(res["tx_power"], abs=0.05) == -35.0
    assert pytest.approx(res["path_loss_n"], abs=0.05) == 3.5
    assert res["r2"] > 0.99


def test_derive_returns_null_params_when_too_few_samples():
    bssid = "AA:BB:CC:00:01:01"
    cfg = _cfg([Router(id="AP01", x=0.0, y=0.0, bssids=[bssid])])
    store = CalibrationStore()
    store.add_sample(CalibrationSample(
        id="s1", x_m=2.0, y_m=0.0, rssi_by_anchor={bssid: -50}, n_scans=1, ts=0.0,
    ))
    out = store.derive_params(cfg)["AP01"]
    assert out["tx_power"] is None
    assert out["path_loss_n"] is None
    assert out["n_points"] == 1


def test_derive_skips_near_field_points():
    # A sample inside the 0.5 m near-field exclusion should not appear in
    # the fit. With only 2 valid points left we expect a null fit.
    bssid = "AA:BB:CC:00:01:01"
    cfg = _cfg([Router(id="AP01", x=0.0, y=0.0, bssids=[bssid])])
    store = CalibrationStore()
    store.add_sample(CalibrationSample(
        id="s0", x_m=0.3, y_m=0.0, rssi_by_anchor={bssid: -30}, n_scans=1, ts=0.0,
    ))
    store.add_sample(CalibrationSample(
        id="s1", x_m=1.0, y_m=0.0, rssi_by_anchor={bssid: -35}, n_scans=1, ts=0.0,
    ))
    store.add_sample(CalibrationSample(
        id="s2", x_m=2.0, y_m=0.0, rssi_by_anchor={bssid: -40}, n_scans=1, ts=0.0,
    ))
    out = store.derive_params(cfg)["AP01"]
    # 2 valid points -> not enough for a fit.
    assert out["tx_power"] is None
    assert out["n_points"] == 2


def test_persist_calibration_writes_overrides_and_samples(tmp_path):
    bindings_path = tmp_path / "wifi-config.json"
    bindings_path.write_text(json.dumps({
        "tx_power": -42,
        "path_loss_n": 2.7,
        "bindings": [
            {"id": "AP01", "bssids": ["AA"]},
            {"id": "AP02", "bssids": ["BB"]},
        ],
    }))
    samples = [
        CalibrationSample(id="s1", x_m=1.0, y_m=0.0, rssi_by_anchor={"AA": -35},
                          n_scans=10, ts=1.0),
    ]
    persist_calibration(
        bindings_path,
        overrides={"AP01": {"tx_power": -34.0, "path_loss_n": 3.6}},
        samples=samples,
    )
    out = json.loads(bindings_path.read_text())
    ap01 = next(b for b in out["bindings"] if b["id"] == "AP01")
    ap02 = next(b for b in out["bindings"] if b["id"] == "AP02")
    assert ap01["tx_power"] == -34.0
    assert ap01["path_loss_n"] == 3.6
    # AP02 had no override -> no params written.
    assert "tx_power" not in ap02 or ap02.get("tx_power") is None
    # Samples are round-tripped.
    assert out["calibration_samples"][0]["x_m"] == 1.0


@pytest.mark.asyncio
async def test_http_capture_and_state_roundtrip(app_with_adapter):
    # Wire the calibration store + ingest hook the way main.py does at
    # startup, then drive it over HTTP.
    from app.calibration import CalibrationStore

    store = CalibrationStore()
    app_with_adapter.state.calibration = store
    app_with_adapter.state.adapter.on_ingest = store.on_ingest

    async with AsyncClient(transport=ASGITransport(app=app_with_adapter), base_url="http://test") as c:
        resp = await c.post("/calibration/capture", json={"x_m": 2.0, "y_m": 3.0, "target_scans": 2})
        assert resp.status_code == 200
        sid = resp.json()["id"]

        # Feed two scans through the regular ingest path; the calibration
        # hook should pull them into the open session. Use the BSSID the
        # `cfg` fixture knows about so /ingest/wifi-scan returns 200.
        bssid = "AA:AA:AA:AA:AA:01"
        await c.post("/ingest/wifi-scan", json={"device_id": "d1", "scan": {bssid: -50}})
        await c.post("/ingest/wifi-scan", json={"device_id": "d1", "scan": {bssid: -52}})

        poll = await c.get(f"/calibration/capture/{sid}")
        body = poll.json()
        assert body["collected"] == 2
        assert body["done"]

        state = (await c.get("/calibration/state")).json()
        assert len(state["samples"]) == 1
        assert state["samples"][0]["rssi_by_anchor"][bssid] == pytest.approx(-51)


@pytest.mark.asyncio
async def test_http_bindings_export_import_roundtrip(app_with_adapter, tmp_path):
    # GET /bindings exports the live file; PUT /bindings replaces it wholesale.
    from app.calibration import CalibrationStore

    bindings_path = tmp_path / "wifi-config.json"
    bindings_path.write_text(json.dumps({
        "tx_power": -42, "path_loss_n": 2.7,
        "bindings": [{"id": "AP01", "bssids": ["AA:AA:AA:AA:AA:01"], "tx_power": -39.0}],
        "calibration_samples": [],
    }))
    app_with_adapter.state.bindings_path = bindings_path
    app_with_adapter.state.calibration = CalibrationStore()
    # No live reload wired: PUT persists + returns reloaded=False (degraded path).
    app_with_adapter.state.reload_wifi_config = None

    async with AsyncClient(transport=ASGITransport(app=app_with_adapter), base_url="http://test") as c:
        exported = (await c.get("/bindings")).json()
        assert exported["bindings"][0]["id"] == "AP01"
        assert exported["bindings"][0]["bssids"] == ["AA:AA:AA:AA:AA:01"]

        # Import a whole new config: replaces bssids + seeds a sample.
        new_doc = {
            "tx_power": -40, "path_loss_n": 3.0,
            "bindings": [{"id": "AP07", "bssids": ["CC:CC:CC:CC:CC:07"]}],
            "calibration_samples": [{
                "id": "s1", "x_m": 1.0, "y_m": 2.0,
                "rssi_by_anchor": {"CC:CC:CC:CC:CC:07": -50.0}, "n_scans": 5, "ts": 1.0,
            }],
        }
        r = await c.put("/bindings", json=new_doc)
        assert r.status_code == 200
        assert r.json()["bindings"] == 1
        assert r.json()["samples"] == 1
        assert r.json()["reloaded"] is False

        on_disk = json.loads(bindings_path.read_text())
        assert [b["id"] for b in on_disk["bindings"]] == ["AP07"]
        # Store re-hydrated from the imported samples.
        assert len(app_with_adapter.state.calibration.all_samples()) == 1

        # Legacy routers shape is accepted and its per-AP params kept.
        r2 = await c.put("/bindings", json={
            "routers": [{"id": "AP09", "x": 1, "y": 2, "bssids": ["DD"],
                         "tx_power": -38.0, "path_loss_n": 2.2}],
        })
        assert r2.status_code == 200
        b = json.loads(bindings_path.read_text())["bindings"][0]
        assert b["id"] == "AP09" and b["bssids"] == ["DD"] and b["tx_power"] == -38.0

        # Garbage body -> 400, not a 500.
        assert (await c.put("/bindings", content=b"not json")).status_code == 400
