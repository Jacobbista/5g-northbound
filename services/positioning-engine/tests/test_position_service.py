"""Tests for the position service: adapter routing and frame normalisation."""

import pytest

from app.adapters.base import Adapter, Measurement
from app.fusion.registry import get_strategy
from app.services.position_service import PositionService


class _StaticAdapter(Adapter):
    def __init__(self, m: Measurement):
        self._m = m

    async def get_measurement(self, device_id: str):
        return self._m


@pytest.mark.asyncio
async def test_device_map_routes_to_named_adapter(floor_plan):
    a = _StaticAdapter(Measurement(source="a", x=1.0, y=0.0, z=1.0, accuracy=1.0, confidence=1.0, frame="local"))
    b = _StaticAdapter(Measurement(source="b", x=9.0, y=0.0, z=9.0, accuracy=1.0, confidence=1.0, frame="local"))
    svc = PositionService(
        adapters={"a": a, "b": b},
        floor_plan=floor_plan,
        device_map={"dev1": "a"},
        primary_strategy=get_strategy("weighted_avg"),
        compare_strategies=[],
    )
    result = await svc.get_position("dev1")
    assert result is not None
    # only adapter "a" should have been consulted
    assert result.primary.fused.sources == ["a"]
    assert result.primary.fused.x == 1.0


@pytest.mark.asyncio
async def test_source_hint_routes_to_matching_adapter(floor_plan):
    """Capability routing: a `source` hint (from the gateway, which knows the
    asset's source) routes straight to that adapter - no DEVICE_MAP needed."""
    a = _StaticAdapter(Measurement(source="a", x=1.0, y=0.0, z=1.0, accuracy=1.0, confidence=1.0, frame="local"))
    b = _StaticAdapter(Measurement(source="b", x=9.0, y=0.0, z=9.0, accuracy=1.0, confidence=1.0, frame="local"))
    svc = PositionService(
        adapters={"a": a, "b": b}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
    )
    result = await svc.get_position("dev1", source="b")
    assert result is not None
    assert result.primary.fused.sources == ["b"]
    assert result.primary.fused.x == 9.0


@pytest.mark.asyncio
async def test_unknown_source_falls_back_to_fan_out(floor_plan):
    a = _StaticAdapter(Measurement(source="a", x=2.0, y=0.0, z=2.0, accuracy=1.0, confidence=1.0, frame="local"))
    svc = PositionService(
        adapters={"a": a}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
    )
    result = await svc.get_position("dev1", source="nonesuch")
    assert result is not None
    assert result.primary.fused.sources == ["a"]


@pytest.mark.asyncio
async def test_device_without_map_uses_all_adapters(floor_plan):
    a = _StaticAdapter(Measurement(source="a", x=2.0, y=0.0, z=2.0, accuracy=1.0, confidence=1.0, frame="local"))
    b = _StaticAdapter(Measurement(source="b", x=4.0, y=0.0, z=4.0, accuracy=1.0, confidence=1.0, frame="local"))
    svc = PositionService(
        adapters={"a": a, "b": b}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
    )
    result = await svc.get_position("anything")
    assert result is not None
    assert set(result.primary.fused.sources) == {"a", "b"}
    assert result.primary.fused.x == 3.0  # midpoint


@pytest.mark.asyncio
async def test_wgs84_measurement_normalised_to_local(floor_plan):
    # measurement that, projected through gps_origin (45.064312, 7.659154), lands at (~0, ~0) local
    near_origin = Measurement(
        source="wittra", frame="wgs84",
        latitude=45.064312, longitude=7.659154,
        accuracy=0.3, confidence=0.95,
    )
    svc = PositionService(
        adapters={"wittra": _StaticAdapter(near_origin)},
        floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
    )
    result = await svc.get_position("dev1")
    assert result is not None
    assert abs(result.primary.fused.x) < 0.01
    assert abs(result.primary.fused.z) < 0.01


@pytest.mark.asyncio
async def test_no_measurements_returns_none(floor_plan):
    class _Null(Adapter):
        async def get_measurement(self, device_id):
            return None
    svc = PositionService(
        adapters={"a": _Null()}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
    )
    assert await svc.get_position("dev1") is None


@pytest.mark.asyncio
async def test_compare_strategies_populated(floor_plan):
    a = _StaticAdapter(Measurement(source="a", x=1.0, y=0.0, z=1.0, accuracy=1.0, confidence=1.0, frame="local"))
    svc = PositionService(
        adapters={"a": a}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"),
        compare_strategies=[get_strategy("weighted_avg")],  # only baseline available today
    )
    result = await svc.get_position("dev1")
    assert result is not None
    assert len(result.compare) == 1
    assert result.compare[0].name == "weighted_avg"


@pytest.mark.asyncio
async def test_last_seen_is_the_most_recent_across_fused_sources(floor_plan):
    # The device is as live as its liveliest source, so the fused result keeps
    # the most recent last-communication, not the first or the oldest.
    a = _StaticAdapter(Measurement(
        source="a", x=1.0, y=0.0, z=1.0, accuracy=1.0, confidence=1.0,
        frame="local", lastSeen=1000.0,
    ))
    b = _StaticAdapter(Measurement(
        source="b", x=1.0, y=0.0, z=1.0, accuracy=1.0, confidence=1.0,
        frame="local", lastSeen=5000.0,
    ))
    svc = PositionService(
        adapters={"a": a, "b": b}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
    )
    result = await svc.get_position("dev1")
    assert result.primary.fused.lastSeen == 5000.0


@pytest.mark.asyncio
async def test_last_seen_survives_wgs84_normalisation(floor_plan):
    # Normalising a wgs84 measurement rebuilds it; lastSeen must not be lost
    # on that path (it is the path every geographic vendor takes).
    a = _StaticAdapter(Measurement(
        source="a", latitude=59.4, longitude=17.9, accuracy=1.0, confidence=1.0,
        frame="wgs84", lastSeen=4242.0,
    ))
    svc = PositionService(
        adapters={"a": a}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
    )
    result = await svc.get_position("dev1")
    assert result.primary.fused.lastSeen == 4242.0


@pytest.mark.asyncio
async def test_last_seen_absent_when_no_source_reports_it(floor_plan):
    a = _StaticAdapter(Measurement(
        source="a", x=1.0, y=0.0, z=1.0, accuracy=1.0, confidence=1.0, frame="local",
    ))
    svc = PositionService(
        adapters={"a": a}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
    )
    result = await svc.get_position("dev1")
    assert result.primary.fused.lastSeen is None


@pytest.mark.asyncio
async def test_missing_accuracy_falls_back_to_the_declared_class_upper_bound(floor_plan):
    # A source reports no genuine per-fix accuracy (Measurement.accuracy is
    # None, not a suspect zero) and declares no nominalAccuracy of its own.
    # The band resolves to its upper bound: with only the class to go on, the
    # honest radius is the worst of the band, not a flattering midpoint.
    m = Measurement(source="uwb-src", x=5.0, y=0.0, z=5.0, accuracy=None, confidence=0.9, frame="local")
    a = _StaticAdapter(m)
    svc = PositionService(
        adapters={"uwb-src": a}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
        capabilities_for=lambda name: {"accuracy_class": "sub-metre"},
    )
    result = await svc.get_position("dev1")
    assert result is not None
    assert result.primary.fused.accuracy == 1.0


@pytest.mark.asyncio
async def test_a_declared_nominal_accuracy_wins_over_the_class_bound(floor_plan):
    # Only the deployment knows its own hardware, so an adapter that declares
    # nominalAccuracy overrides the generic band bound.
    m = Measurement(source="uwb-src", x=5.0, y=0.0, z=5.0, accuracy=None, confidence=0.9, frame="local")
    a = _StaticAdapter(m)
    svc = PositionService(
        adapters={"uwb-src": a}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
        capabilities_for=lambda name: {"accuracy_class": "sub-metre", "nominalAccuracy": 0.3},
    )
    result = await svc.get_position("dev1")
    assert result is not None
    assert result.primary.fused.accuracy == 0.3


@pytest.mark.asyncio
async def test_coarse_without_a_declared_nominal_drops_the_measurement(floor_plan):
    # `coarse` is open-ended upward, so it resolves to no value on its own. An
    # adapter declaring it without a nominalAccuracy has said nothing usable.
    m = Measurement(source="vague", x=5.0, y=0.0, z=5.0, accuracy=None, confidence=0.9, frame="local")
    a = _StaticAdapter(m)
    svc = PositionService(
        adapters={"vague": a}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
        capabilities_for=lambda name: {"accuracy_class": "coarse"},
    )
    assert await svc.get_position("dev1") is None


@pytest.mark.asyncio
async def test_a_real_zero_accuracy_is_never_replaced_by_the_nominal_value(floor_plan):
    # accuracy=0.0 is a reported value, not an absence: the nominal fallback
    # must not touch it (that is weighted_avg's own epsilon floor's job).
    m = Measurement(source="wittra", x=5.0, y=0.0, z=5.0, accuracy=0.0, confidence=0.9, frame="local")
    a = _StaticAdapter(m)
    svc = PositionService(
        adapters={"wittra": a}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
        capabilities_for=lambda name: {"accuracy_class": "coarse"},
    )
    result = await svc.get_position("dev1")
    assert result is not None
    assert result.primary.fused.accuracy < 5.0  # nowhere near the coarse nominal


@pytest.mark.asyncio
async def test_missing_accuracy_and_unknown_accuracy_class_drops_the_measurement(floor_plan):
    # No per-fix accuracy and no declared accuracy_class: nothing honest to
    # fuse with. The source is dropped, not defaulted to an arbitrary number.
    m = Measurement(source="mystery", x=5.0, y=0.0, z=5.0, accuracy=None, confidence=0.9, frame="local")
    a = _StaticAdapter(m)
    svc = PositionService(
        adapters={"mystery": a}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
        capabilities_for=lambda name: {},
    )
    result = await svc.get_position("dev1")
    assert result is None
