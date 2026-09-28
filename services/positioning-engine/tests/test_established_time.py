"""Established time and currency, from each source's declared reporting model."""

import pytest
from pydantic import ValidationError

from app.adapters.base import Adapter, Measurement
from app.fusion.registry import get_strategy
from app.services.position_service import PositionService, established_at, is_current
from app.wire import AdapterCapabilities

NOW = 1_000_000.0


def _m(source="a", ts=NOW - 100, last_seen=None):
    return Measurement(source=source, x=1.0, y=1.0, accuracy=1.0, frame="venue",
                       timestamp=ts, lastSeen=last_seen)


def test_on_motion_is_established_by_the_last_communication():
    caps = {"reporting": "on_motion", "reportingInterval": 60}
    assert established_at(_m(ts=NOW - 3 * 86400, last_seen=NOW - 10), caps) == NOW - 10


@pytest.mark.parametrize("caps", [{}, {"reporting": "periodic", "reportingInterval": 60},
                                  {"reporting": "on_request"}])
def test_other_models_are_established_by_the_fix_alone(caps):
    assert established_at(_m(ts=NOW - 100, last_seen=NOW - 10), caps) == NOW - 100


def test_on_motion_without_last_seen_falls_back_to_the_fix_time():
    caps = {"reporting": "on_motion", "reportingInterval": 60}
    assert established_at(_m(ts=NOW - 100), caps) == NOW - 100


def test_on_request_is_current_by_construction():
    assert is_current(NOW - 3600, {"reporting": "on_request"}, NOW)


@pytest.mark.parametrize("reporting", ["periodic", "on_motion"])
def test_interval_bounds_currency(reporting):
    caps = {"reporting": reporting, "reportingInterval": 60}
    assert is_current(NOW - 60, caps, NOW)
    assert not is_current(NOW - 61, caps, NOW)


def test_an_undeclared_source_is_never_current():
    assert not is_current(NOW, {}, NOW)


@pytest.mark.parametrize("reporting", ["periodic", "on_motion"])
def test_a_declaration_without_interval_is_refused(reporting):
    with pytest.raises(ValidationError):
        AdapterCapabilities(reporting=reporting)


class _Static(Adapter):
    def __init__(self, m):
        self._m = m

    async def get_measurement(self, device_id):
        return self._m


@pytest.mark.asyncio
async def test_fused_position_holds_as_of_its_least_recent_contribution(floor_plan):
    caps = {
        "a": {"reporting": "on_request"},
        "b": {"reporting": "on_motion", "reportingInterval": 60},
    }
    svc = PositionService(
        adapters={"a": _Static(_m("a", ts=NOW - 1)), "b": _Static(_m("b", ts=NOW - 500, last_seen=NOW - 30))},
        floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
        capabilities_for=lambda name: caps.get(name, {}), clock=lambda: NOW,
    )
    fused = (await svc.get_position("d")).primary.fused
    assert fused.establishedAt == NOW - 30
    assert fused.current is True


@pytest.mark.asyncio
async def test_one_stale_contribution_makes_the_fusion_not_current(floor_plan):
    caps = {
        "a": {"reporting": "on_request"},
        "b": {"reporting": "on_motion", "reportingInterval": 60},
    }
    svc = PositionService(
        adapters={"a": _Static(_m("a", ts=NOW - 1)), "b": _Static(_m("b", ts=NOW - 500, last_seen=NOW - 120))},
        floor_plan=floor_plan, device_map={},
        primary_strategy=get_strategy("weighted_avg"), compare_strategies=[],
        capabilities_for=lambda name: caps.get(name, {}), clock=lambda: NOW,
    )
    fused = (await svc.get_position("d")).primary.fused
    assert fused.establishedAt == NOW - 120
    assert fused.current is False
