import math

from app.wifi import WifiAdapter, compute_position


def test_compute_position_in_bounds(cfg):
    res = compute_position({"AA:AA:AA:AA:AA:01": -50, "BB:BB:BB:BB:BB:01": -70}, cfg)
    assert res is not None
    x, y, conf, acc = res
    assert 0 <= x <= cfg.room_w
    assert 0 <= y <= cfg.room_h
    assert 0 < conf <= 100
    assert acc >= 1.0


def test_trilateration_recovers_known_point(cfg3):
    tx, n = cfg3.tx_power, cfg3.path_loss_n
    target = (6.0, 8.0)
    scan = {}
    bssid_by_router = {"A": "AA:AA:AA:AA:AA:01", "B": "BB:BB:BB:BB:BB:01", "C": "CC:CC:CC:CC:CC:01"}
    for r in cfg3.routers:
        d = math.hypot(target[0] - r.x, target[1] - r.y)
        rssi = int(tx - 10 * n * math.log10(max(d, 0.1)))
        scan[bssid_by_router[r.id]] = rssi
    x, y, conf, acc = compute_position(scan, cfg3)
    assert abs(x - 6.0) < 1.5
    assert abs(y - 8.0) < 1.5


def test_compute_position_no_known_ap(cfg):
    assert compute_position({"FF:FF:FF:FF:FF:FF": -40}, cfg) is None


def test_compute_position_case_insensitive_bssid(cfg):
    assert compute_position({"aa:aa:aa:aa:aa:01": -45}, cfg) is not None


def test_compute_position_stronger_rssi_pulls_closer(cfg):
    near_a = compute_position({"AA:AA:AA:AA:AA:01": -40, "BB:BB:BB:BB:BB:01": -85}, cfg)
    near_b = compute_position({"AA:AA:AA:AA:AA:01": -85, "BB:BB:BB:BB:BB:01": -40}, cfg)
    assert near_a[1] < near_b[1]


def test_adapter_caches_last_fix_with_timestamp(cfg):
    adapter = WifiAdapter(cfg)
    assert adapter.ingest("dev1", {"AA:AA:AA:AA:AA:01": -50}, ts=1000.0) is True

    m = adapter.get_measurement("dev1")
    assert m is not None and m.source == "wifi"
    assert m.timestamp == 1000.0
    assert adapter.get_measurement("unknown-device") is None
    assert adapter.get_measurement("dev1") is not None


def test_adapter_rejects_scan_without_known_ap(cfg):
    adapter = WifiAdapter(cfg)
    assert adapter.ingest("dev1", {"FF:FF:FF:FF:FF:FF": -40}) is False
