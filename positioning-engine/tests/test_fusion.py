import math

import pytest

from app.adapters.base import Measurement
from app.services.fusion import fuse


def make(source, x, y, z, accuracy_m, confidence):
    return Measurement(source=source, x=x, y=y, z=z, accuracy_m=accuracy_m, confidence=confidence)


def test_fuse_empty_raises():
    with pytest.raises(ValueError):
        fuse([])


def test_fuse_single_passthrough():
    m = make("uwb", 5.0, 1.0, 10.0, 0.3, 0.95)
    x, y, z, acc, sources, ts = fuse([m])
    assert x == pytest.approx(5.0)
    assert y == pytest.approx(1.0)
    assert z == pytest.approx(10.0)
    assert acc == pytest.approx(0.3)
    assert sources == ["uwb"]
    assert ts is None  # no measurement carried a timestamp


def test_fuse_returns_freshest_timestamp():
    m1 = Measurement("wifi", 0, 0, 0, 2.0, 0.7, timestamp=100.0)
    m2 = Measurement("uwb", 0, 0, 0, 0.3, 0.95, timestamp=150.0)
    *_, ts = fuse([m1, m2])
    assert ts == 150.0


def test_fuse_weighted_centroid():
    # Two measurements with known weights: w = confidence / accuracy_m
    # m1: w = 0.95 / 0.3 ≈ 3.167,  x=0
    # m2: w = 0.6  / 3.0 = 0.2,    x=30
    # expected x = (3.167*0 + 0.2*30) / (3.167 + 0.2) ≈ 6 / 3.367 ≈ 1.783
    m1 = make("uwb",   x=0.0,  y=1.0, z=5.0, accuracy_m=0.3, confidence=0.95)
    m2 = make("fiveg", x=30.0, y=1.0, z=5.0, accuracy_m=3.0, confidence=0.6)
    x, y, z, acc, sources, _ = fuse([m1, m2])

    w1 = 0.95 / 0.3
    w2 = 0.6 / 3.0
    expected_x = (w1 * 0.0 + w2 * 30.0) / (w1 + w2)
    assert x == pytest.approx(expected_x, rel=1e-5)
    assert set(sources) == {"uwb", "fiveg"}


def test_fuse_accuracy_improves_with_more_sources():
    m1 = make("uwb",  x=5.0, y=1.0, z=5.0, accuracy_m=0.3, confidence=0.95)
    m2 = make("wifi", x=5.0, y=1.0, z=5.0, accuracy_m=2.0, confidence=0.7)
    _, _, _, acc_both, _, _ = fuse([m1, m2])
    _, _, _, acc_single, _, _ = fuse([m1])
    assert acc_both < acc_single
