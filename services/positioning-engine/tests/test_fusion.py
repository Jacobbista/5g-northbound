import pytest

from app.adapters.base import Measurement
from app.fusion.registry import get_strategy, STRATEGIES


def _m(source: str, x: float, z: float, accuracy: float, confidence: float = 1.0) -> Measurement:
    return Measurement(source=source, x=x, y=0.0, z=z, accuracy=accuracy, confidence=confidence, frame="local")


def test_registry_lists_baseline():
    assert "weighted_avg" in STRATEGIES


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        get_strategy("does-not-exist")


def test_weighted_avg_single_measurement_passthrough(floor_plan):
    strat = get_strategy("weighted_avg")
    m = _m("wifi", x=5.0, z=10.0, accuracy=2.0)
    out = strat.fuse("dev", [m], floor_plan)
    assert out is not None
    assert out.x == 5.0 and out.z == 10.0
    assert out.sources == ["wifi"]


def test_weighted_avg_two_consistent_improves_accuracy(floor_plan):
    strat = get_strategy("weighted_avg")
    a = _m("wifi", x=5.0, z=10.0, accuracy=2.0)
    b = _m("uwb",  x=5.0, z=10.0, accuracy=2.0)
    out = strat.fuse("dev", [a, b], floor_plan)
    assert out is not None
    assert out.x == 5.0 and out.z == 10.0
    # inverse-RMS: 1/sqrt(2 * 1/4) = sqrt(2) ≈ 1.414 - strictly better than 2.0
    assert out.accuracy < 2.0


def test_weighted_avg_high_confidence_dominates(floor_plan):
    strat = get_strategy("weighted_avg")
    cheap = _m("wifi", x=0.0, z=0.0, accuracy=5.0, confidence=0.5)
    good = _m("uwb",  x=10.0, z=10.0, accuracy=0.3, confidence=0.95)
    out = strat.fuse("dev", [cheap, good], floor_plan)
    assert out is not None
    # weighted result must lie much closer to the UWB measurement
    assert out.x > 9.0 and out.z > 9.0


def test_weighted_avg_empty_returns_none(floor_plan):
    strat = get_strategy("weighted_avg")
    assert strat.fuse("dev", [], floor_plan) is None


def test_weighted_avg_zero_accuracy_does_not_crash(floor_plan):
    # Reproduces the v0.16.1 outage: a live Wittra tag reported accuracy: 0.0
    # (diagnostics showed it still MOVING) and GET /position/{id} 500'd on a
    # ZeroDivisionError instead of returning a degraded fix.
    strat = get_strategy("weighted_avg")
    m = _m("wittra", x=5.0, z=10.0, accuracy=0.0)
    out = strat.fuse("dev", [m], floor_plan)
    assert out is not None
    assert out.x == 5.0 and out.z == 10.0
    assert out.accuracy > 0.0


def test_weighted_avg_zero_accuracy_does_not_drown_out_a_real_measurement(floor_plan):
    # A single zero-accuracy reading must not be trusted as literally perfect:
    # floored, not infinite weight, so a genuinely accurate second source still
    # pulls the fix toward itself rather than being ignored entirely.
    strat = get_strategy("weighted_avg")
    suspect = _m("wittra", x=0.0, z=0.0, accuracy=0.0)
    good = _m("uwb", x=10.0, z=10.0, accuracy=0.3, confidence=0.95)
    out = strat.fuse("dev", [suspect, good], floor_plan)
    assert out is not None
    assert 0.0 < out.x < 10.0
