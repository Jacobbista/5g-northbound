import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import Request

from ..adapters.base import Adapter, Measurement
from ..fusion.base import FusedPosition, FusionStrategy
from ..models import FloorPlan
from .geo import gps_to_local

log = logging.getLogger(__name__)

# Nominal per-fix accuracy (metres), used ONLY when a source reports no
# per-fix accuracy at all (Measurement.accuracy is None) - never when it
# reports a real, if degenerate, number such as 0.0. Keyed by the
# `accuracy_class` each adapter self-declares in its adapter.contract.yaml
# (coarse | metre | sub-metre), so the fallback reflects what the technology
# class claims rather than a number invented once per vendor schema. A
# nominal value is never mistaken for a measurement downstream: `source` /
# `sourceClass` travels on the same response so a consumer can tell them
# apart (6GHYPE paper Sec. IV - accuracy alone collapses precision and
# provenance into one signal; source is how the two stay separable).
_NOMINAL_ACCURACY_M = {"sub-metre": 0.5, "metre": 2.0, "coarse": 5.0}


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
        capabilities_for: Callable[[str], dict] = lambda name: {},
    ):
        self._adapters = adapters
        self._floor_plan = floor_plan
        self._device_map = device_map
        self._primary = primary_strategy
        self._compare = compare_strategies
        # Live lookup (registry.capabilities_for), not a snapshot: a source's
        # advertised accuracy_class can change on any heartbeat.
        self._capabilities_for = capabilities_for

    def set_floor_plan(self, floor_plan: FloorPlan) -> None:
        """Swap the active floor plan at runtime. Called after a PUT /blueprint
        so the new georef takes effect without restarting the engine."""
        self._floor_plan = floor_plan

    def _select_adapters(self, device_id: str, source: Optional[str] = None) -> list[Adapter]:
        """Pick which adapters to poll for a device. Priority:
          1. `source` hint (the gateway knows the asset's source/adapter) -
             route straight to that adapter. Capability-style routing, no
             manual map.
          2. legacy DEVICE_MAP entry, if configured.
          3. fan out to all adapters - safe because each adapter 404s for
             devices it does not serve.
        """
        if source:
            adapter = self._adapters.get(source)
            if adapter is not None:
                return [adapter]
            log.warning("source '%s' has no registered adapter; falling back", source)
        target = self._device_map.get(device_id)
        if target is not None:
            adapter = self._adapters.get(target)
            if adapter is not None:
                return [adapter]
            log.warning(
                "device_map routes %s to unknown adapter '%s'; falling back to all",
                device_id, target,
            )
        return list(self._adapters.values())

    def _fill_nominal_accuracy(self, m: Measurement) -> Optional[Measurement]:
        """A measurement with no per-fix accuracy gets the nominal value for
        its source's declared accuracy_class, so fusion always has a real
        number to weight by. Returns None (drop the measurement, with a
        warning) when the source has advertised no accuracy_class either -
        there is nothing honest left to fuse with."""
        if m.accuracy is not None:
            return m
        accuracy_class = self._capabilities_for(m.source).get("accuracy_class")
        nominal = _NOMINAL_ACCURACY_M.get(accuracy_class)
        if nominal is None:
            log.warning(
                "measurement from '%s' has no accuracy and no known accuracy_class; dropping",
                m.source,
            )
            return None
        return Measurement(
            source=m.source,
            accuracy=nominal,
            confidence=m.confidence,
            frame=m.frame,
            x=m.x, y=m.y, z=m.z,
            latitude=m.latitude, longitude=m.longitude,
            timestamp=m.timestamp,
            lastSeen=m.lastSeen,
            diagnostics=m.diagnostics,
        )

    def _normalise(self, m: Measurement) -> Measurement:
        if m.frame == "local":
            return m
        x, z = gps_to_local(m.latitude, m.longitude, self._floor_plan.gps_origin)
        return Measurement(
            source=m.source,
            accuracy=m.accuracy,
            confidence=m.confidence,
            frame="local",
            x=x, y=m.y, z=z,
            timestamp=m.timestamp,
            lastSeen=m.lastSeen,
            diagnostics=m.diagnostics,
        )

    async def get_position(self, device_id: str, source: Optional[str] = None) -> Optional[PositionResult]:
        adapters = self._select_adapters(device_id, source)
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
            filled = self._fill_nominal_accuracy(self._normalise(r))
            if filled is not None:
                measurements.append(filled)

        if not measurements:
            return None

        primary = self._primary.fuse(device_id, measurements, self._floor_plan)
        if primary is None:
            return None
        # Attach vendor fidelity from a single routed source (the broadcast
        # path routes one adapter). Fusion strategies do not compute it.
        if len(measurements) == 1:
            primary.diagnostics = measurements[0].diagnostics
        # The device is as live as its liveliest contributing source, so carry
        # the most recent last-communication across the fused measurements.
        seen = [m.lastSeen for m in measurements if m.lastSeen is not None]
        if seen:
            primary.lastSeen = max(seen)
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
