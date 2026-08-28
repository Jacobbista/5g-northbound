import math

from app.fusion import fuse_fixes


def test_none_when_no_usable_fix():
    assert fuse_fixes([]) is None
    assert fuse_fixes([{"latitude": None, "longitude": None, "accuracy_m": 1.0}]) is None


def test_single_fix_passes_through_with_sources():
    out = fuse_fixes([{"latitude": 59.4, "longitude": 17.9, "accuracy_m": 0.5, "source": "wittra"}])
    assert out["latitude"] == 59.4
    assert out["sources"] == ["wittra"]


def test_sharper_source_dominates_and_radius_shrinks():
    fixes = [
        {"latitude": 0.0, "longitude": 0.0, "accuracy_m": 3.0, "sources": ["wifi"]},
        {"latitude": 1.0, "longitude": 1.0, "accuracy_m": 0.5, "sources": ["wittra"]},
    ]
    out = fuse_fixes(fixes)
    # inverse-variance: UWB (0.5m) weight 1/0.25=4 vs WiFi (3m) weight 1/9~0.11
    # -> fused sits very close to the UWB fix
    assert out["latitude"] > 0.97 and out["longitude"] > 0.97
    # fused radius is smaller than the best single input
    assert out["accuracy_m"] < 0.5
    assert set(out["sources"]) == {"wifi", "wittra"}


def test_missing_source_drops_out_continuity():
    # Only one capability has a fix this tick -> the asset stays located on it.
    fixes = [
        {"latitude": None, "longitude": None, "accuracy_m": 3.0, "sources": ["wifi"]},
        {"latitude": 2.0, "longitude": 2.0, "accuracy_m": 0.5, "sources": ["wittra"]},
    ]
    out = fuse_fixes(fixes)
    assert out["latitude"] == 2.0
    assert out["sources"] == ["wittra"]


def test_latest_timestamp_and_union_altitude_from_sharpest():
    fixes = [
        {"latitude": 0.0, "longitude": 0.0, "accuracy_m": 3.0, "timestamp": "2026-01-01T00:00:00Z",
         "altitude": 99.0, "sources": ["wifi"]},
        {"latitude": 0.0, "longitude": 0.0, "accuracy_m": 0.5, "timestamp": "2026-01-01T00:00:05Z",
         "altitude": 1.2, "sources": ["wittra"]},
    ]
    out = fuse_fixes(fixes)
    assert out["timestamp"] == "2026-01-01T00:00:05Z"  # freshest
    assert out["altitude"] == 1.2  # from the sharpest fix
