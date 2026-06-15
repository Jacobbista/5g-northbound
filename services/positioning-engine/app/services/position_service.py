import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import Request

from ..adapters.base import Adapter, Measurement
from ..fusion.base import FusedPosition, FusionStrategy
from ..models import FloorPlan
from .geo import gps_to_local

log = logging.getLogger(__name__)


@dataclass
class StrategyResult:
    name: str
    fused: FusedPosition


@dataclass
class PositionResult:
    primary: StrategyResult
    compare: list[StrategyResult]


class PositionService:
    """Polls configured adapters and runs the configured fusion strategies.

    Adapter selection per device:
      - If `device_map` lists the device, only the named adapter is polled.
      - Otherwise all adapters are polled.

    Measurements are normalised to the floor-plan-local frame before fusion.
    """

    def __init__(
        self,
        adapters: dict[str, Adapter],
        floor_plan: FloorPlan,
        device_map: dict[str, str],
        primary_strategy: FusionStrategy,
        compare_strategies: list[FusionStrategy],
    ):
        self._adapters = adapters
        self._floor_plan = floor_plan
        self._device_map = device_map
        self._primary = primary_strategy
        self._compare = compare_strategies

    def set_floor_plan(self, floor_plan: FloorPlan) -> None:
        """Swap the active floor plan at runtime. Called after a PUT /blueprint
        so the new georef takes effect without restarting the engine."""
        self._floor_plan = floor_plan

    def _select_adapters(self, device_id: str) -> list[Adapter]:
        target = self._device_map.get(device_id)
        if target is None:
            return list(self._adapters.values())
        adapter = self._adapters.get(target)
        if adapter is None:
            log.warning(
                "device_map routes %s to unknown adapter '%s'; falling back to all",
                device_id, target,
            )
            return list(self._adapters.values())
        return [adapter]

    def _normalise(self, m: Measurement) -> Measurement:
        if m.frame == "local":
            return m
        x, z = gps_to_local(m.latitude, m.longitude, self._floor_plan.gps_origin)
        return Measurement(
            source=m.source,
            accuracy_m=m.accuracy_m,
            confidence=m.confidence,
            frame="local",
            x=x, y=m.y, z=z,
            timestamp=m.timestamp,
        )

    async def get_position(self, device_id: str) -> Optional[PositionResult]:
        adapters = self._select_adapters(device_id)
        if not adapters:
            log.warning("no adapters configured for %s", device_id)
            return None

        results = await asyncio.gather(
            *[a.get_measurement(device_id) for a in adapters],
            return_exceptions=True,
        )
        measurements: list[Measurement] = []
        for r in results:
            if isinstance(r, Exception):
                log.warning("adapter error for %s: %s", device_id, r)
                continue
            if r is None:
                continue
            measurements.append(self._normalise(r))

        if not measurements:
            return None

        primary = self._primary.fuse(device_id, measurements, self._floor_plan)
        if primary is None:
            return None
        compare: list[StrategyResult] = []
        for strat in self._compare:
            out = strat.fuse(device_id, measurements, self._floor_plan)
            if out is not None:
                compare.append(StrategyResult(name=strat.name, fused=out))

        return PositionResult(
            primary=StrategyResult(name=self._primary.name, fused=primary),
            compare=compare,
        )


def get_position_service(request: Request) -> PositionService:
    return request.app.state.position_service


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ts_to_iso(ts: Optional[float]) -> str:
    if ts is None:
        return now_iso()
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()
