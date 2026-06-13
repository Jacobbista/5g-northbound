import pytest

from app.adapters.base import Measurement
from app.fusion.registry import get_strategy, STRATEGIES


def _m(source: str, x: float, z: float, accuracy_m: float, confidence: float = 1.0) -> Measurement:
    return Measurement(source=source, x=x, y=0.0, z=z, accuracy_m=accuracy_m, confidence=confidence, frame="local")


def test_registry_lists_baseline():
    assert "weighted_avg" in STRATEGIES


def test_unknown_strategy_raises():
    with pytest.raises(ValueError):
        get_strategy("does-not-exist")


def test_weighted_avg_single_measurement_passthrough(floor_plan):
    strat = get_strategy("weighted_avg")
    m = _m("wifi", x=5.0, z=10.0, accuracy_m=2.0)
    out = strat.fuse("dev", [m], floor_plan)
    assert out is not None
    assert out.x == 5.0 and out.z == 10.0
    assert out.sources == ["wifi"]


def test_weighted_avg_two_consistent_improves_accuracy(floor_plan):
    strat = get_strategy("weighted_avg")
    a = _m("wifi", x=5.0, z=10.0, accuracy_m=2.0)
    b = _m("uwb",  x=5.0, z=10.0, accuracy_m=2.0)
    out = strat.fuse("dev", [a, b], floor_plan)
    assert out is not None
    assert out.x == 5.0 and out.z == 10.0
    # inverse-RMS: 1/sqrt(2 * 1/4) = sqrt(2) ≈ 1.414 - strictly better than 2.0
    assert out.accuracy_m < 2.0


def test_weighted_avg_high_confidence_dominates(floor_plan):
    strat = get_strategy("weighted_avg")
    cheap = _m("wifi", x=0.0, z=0.0, accuracy_m=5.0, confidence=0.5)
    good = _m("uwb",  x=10.0, z=10.0, accuracy_m=0.3, confidence=0.95)
    out = strat.fuse("dev", [cheap, good], floor_plan)
    assert out is not None
    # weighted result must lie much closer to the UWB measurement
    assert out.x > 9.0 and out.z > 9.0


def test_weighted_avg_empty_returns_none(floor_plan):
    strat = get_strategy("weighted_avg")
    assert strat.fuse("dev", [], floor_plan) is None
