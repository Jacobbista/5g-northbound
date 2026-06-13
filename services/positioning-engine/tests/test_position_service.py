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
    a = _StaticAdapter(Measurement(source="a", x=1.0, y=0.0, z=1.0, accuracy_m=1.0, confidence=1.0, frame="local"))
    b = _StaticAdapter(Measurement(source="b", x=9.0, y=0.0, z=9.0, accuracy_m=1.0, confidence=1.0, frame="local"))
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
async def test_device_without_map_uses_all_adapters(floor_plan):
    a = _StaticAdapter(Measurement(source="a", x=2.0, y=0.0, z=2.0, accuracy_m=1.0, confidence=1.0, frame="local"))
    b = _StaticAdapter(Measurement(source="b", x=4.0, y=0.0, z=4.0, accuracy_m=1.0, confidence=1.0, frame="local"))
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
        accuracy_m=0.3, confidence=0.95,
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
    a = _StaticAdapter(Measurement(source="a", x=1.0, y=0.0, z=1.0, accuracy_m=1.0, confidence=1.0, frame="local"))
    svc = PositionService(
        adapters={"a": a}, floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"),
        compare_strategies=[get_strategy("weighted_avg")],  # only baseline available today
    )
    result = await svc.get_position("dev1")
    assert result is not None
    assert len(result.compare) == 1
    assert result.compare[0].name == "weighted_avg"
