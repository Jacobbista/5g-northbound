import pytest

from app.adapters.base import Measurement
from app.fusion.registry import get_strategy, STRATEGIES


def _m(source: str, x: float, z: float, accuracy: float, confidence: float = 1.0) -> Measurement:
    return Measurement(source=source, x=x, y=z, accuracy=accuracy, confidence=confidence, frame="venue")


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
    assert out.x == 5.0 and out.y == 10.0
    assert out.sources == ["wifi"]


def test_weighted_avg_two_consistent_improves_accuracy(floor_plan):
    strat = get_strategy("weighted_avg")
    a = _m("wifi", x=5.0, z=10.0, accuracy=2.0)
    b = _m("uwb",  x=5.0, z=10.0, accuracy=2.0)
    out = strat.fuse("dev", [a, b], floor_plan)
    assert out is not None
    assert out.x == 5.0 and out.y == 10.0
    # inverse-RMS: 1/sqrt(2 * 1/4) = sqrt(2) ≈ 1.414 - strictly better than 2.0
    assert out.accuracy < 2.0


def test_weighted_avg_high_confidence_dominates(floor_plan):
    strat = get_strategy("weighted_avg")
    cheap = _m("wifi", x=0.0, z=0.0, accuracy=5.0, confidence=0.5)
    good = _m("uwb",  x=10.0, z=10.0, accuracy=0.3, confidence=0.95)
    out = strat.fuse("dev", [cheap, good], floor_plan)
    assert out is not None
    # weighted result must lie much closer to the UWB measurement
    assert out.x > 9.0 and out.y > 9.0


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
    assert out.x == 5.0 and out.y == 10.0
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


def test_weighted_avg_fuses_height_only_over_measurements_that_carry_it(floor_plan):
    strat = get_strategy("weighted_avg")
    with_height = Measurement(source="a", x=0.0, y=0.0, z=2.0, accuracy=1.0, confidence=1.0, frame="venue")
    flat = Measurement(source="b", x=0.0, y=0.0, z=None, accuracy=1.0, confidence=1.0, frame="venue")
    out = strat.fuse("d", [with_height, flat], floor_plan)
    assert out.z == 2.0


def test_weighted_avg_height_is_absent_when_no_measurement_carries_it(floor_plan):
    strat = get_strategy("weighted_avg")
    flat = Measurement(source="a", x=0.0, y=0.0, z=None, accuracy=1.0, confidence=1.0, frame="venue")
    assert strat.fuse("d", [flat], floor_plan).z is None


def test_weighted_avg_vertical_accuracy_is_the_error_of_the_weighted_height(floor_plan):
    strat = get_strategy("weighted_avg")
    alone = Measurement(source="a", x=0.0, y=0.0, z=2.0, verticalAccuracy=0.4,
                        accuracy=1.0, confidence=1.0, frame="venue")
    assert strat.fuse("d", [alone], floor_plan).verticalAccuracy == pytest.approx(0.4)
    # Equal weights: sqrt(0.3^2 + 0.4^2) / 2.
    a = Measurement(source="a", x=0.0, y=0.0, z=2.0, verticalAccuracy=0.3,
                    accuracy=1.0, confidence=1.0, frame="venue")
    b = Measurement(source="b", x=0.0, y=0.0, z=2.2, verticalAccuracy=0.4,
                    accuracy=1.0, confidence=1.0, frame="venue")
    assert strat.fuse("d", [a, b], floor_plan).verticalAccuracy == pytest.approx(0.25)


def test_weighted_avg_vertical_accuracy_is_absent_when_a_height_has_none(floor_plan):
    strat = get_strategy("weighted_avg")
    known = Measurement(source="a", x=0.0, y=0.0, z=2.0, verticalAccuracy=0.3,
                        accuracy=1.0, confidence=1.0, frame="venue")
    unknown = Measurement(source="b", x=0.0, y=0.0, z=2.2, accuracy=1.0, confidence=1.0, frame="venue")
    flat = Measurement(source="c", x=0.0, y=0.0, accuracy=1.0, confidence=1.0, frame="venue")
    assert strat.fuse("d", [known, unknown], floor_plan).verticalAccuracy is None
    # A source without height does not take part in the height or its error.
    assert strat.fuse("d", [known, flat], floor_plan).verticalAccuracy == pytest.approx(0.3)


def test_weighted_avg_weights_a_source_without_confidence_by_accuracy(floor_plan):
    strat = get_strategy("weighted_avg")
    alone = Measurement(source="a", x=4.0, y=6.0, accuracy=2.0, confidence=None, frame="venue")
    assert (strat.fuse("d", [alone], floor_plan).x, strat.fuse("d", [alone], floor_plan).y) == (4.0, 6.0)
    near = Measurement(source="a", x=0.0, y=0.0, accuracy=1.0, confidence=None, frame="venue")
    far = Measurement(source="b", x=10.0, y=0.0, accuracy=1.0, confidence=1.0, frame="venue")
    assert strat.fuse("d", [near, far], floor_plan).x == 5.0


def test_weighted_avg_weights_by_inverse_variance(floor_plan):
    strat = get_strategy("weighted_avg")
    sharp = Measurement(source="a", x=0.0, y=0.0, accuracy=1.0, confidence=None, frame="venue")
    coarse = Measurement(source="b", x=10.0, y=0.0, accuracy=3.0, confidence=None, frame="venue")
    out = strat.fuse("d", [sharp, coarse], floor_plan)
    # Weights 1 and 1/9: the mean sits at 10 * (1/9) / (10/9) = 1 m.
    assert out.x == pytest.approx(1.0)
    # With equal confidences the error of the mean is the inverse-variance one.
    assert out.accuracy == pytest.approx(1.0 / (1.0 + 1.0 / 9.0) ** 0.5)


def test_weighted_avg_accuracy_is_the_error_of_the_mean_it_computed(floor_plan):
    strat = get_strategy("weighted_avg")
    a = Measurement(source="a", x=0.0, y=0.0, accuracy=1.0, confidence=1.0, frame="venue")
    b = Measurement(source="b", x=0.0, y=0.0, accuracy=1.0, confidence=0.25, frame="venue")
    # Weights 1 and 0.25 on two 1 m errors: sqrt(1 + 0.0625) / 1.25.
    assert strat.fuse("d", [a, b], floor_plan).accuracy == pytest.approx(1.0625 ** 0.5 / 1.25)
