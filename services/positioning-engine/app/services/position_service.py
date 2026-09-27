import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import Request

from ..accuracy_classes import nominal_for_class
from ..adapters.base import Adapter, Measurement
from ..fusion.base import FusedPosition, FusionStrategy
from ..models import FloorPlan
from .geo import gps_to_local, room_to_venue

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

    Measurements are normalised to the venue frame before fusion.
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
        """A measurement with no per-fix accuracy gets a nominal one, so fusion
        always has a real number to weight by.

        Two sources for it, in order. The adapter's own `nominalAccuracy` wins:
        it describes the deployed hardware, and only the deployment knows that.
        Otherwise the upper bound of its declared `accuracy_class`, which claims
        the worst of the band rather than a flattering midpoint. `coarse` is
        open-ended and resolves to nothing on its own, so an adapter declaring
        it without a `nominalAccuracy` has said nothing usable.

        Returns None (drop the measurement, with a warning) when neither is
        available. Dropping a source is recoverable and visible. Fusing it
        against an invented radius is neither.
        """
        if m.accuracy is not None:
            return m
        caps = self._capabilities_for(m.source)
        declared = caps.get("nominalAccuracy")
        nominal = float(declared) if declared is not None else nominal_for_class(
            caps.get("accuracy_class")
        )
        if nominal is None:
            log.warning(
                "measurement from '%s' has no accuracy, and its source declares "
                "neither nominalAccuracy nor a bounded accuracy_class; dropping",
                m.source,
            )
            return None
        return replace(m, accuracy=nominal)

    def _apply_height_declaration(self, m: Measurement) -> Measurement:
        """A height counts only from a source that declares `z: true`. A source
        that declares no height, or declares nothing, contributes a horizontal
        fix only."""
        if m.z is None or self._capabilities_for(m.source).get("z") is True:
            return m
        return replace(m, z=None)

    def _normalise(self, m: Measurement) -> Optional[Measurement]:
        """Express a measurement in the venue frame. A room measurement is
        placed through its room; one naming a room the blueprint does not hold
        cannot be placed and is dropped."""
        if m.frame == "venue":
            return m
        if m.frame == "room":
            room = self._floor_plan.rooms.get(m.room or "")
            if room is None:
                log.warning("measurement from '%s' names unknown room %r; dropping", m.source, m.room)
                return None
            x, y = room_to_venue(m.x, m.y, room)
        else:
            x, y = gps_to_local(m.latitude, m.longitude, self._floor_plan.gps_origin)
        return replace(m, frame="venue", room=None, x=x, y=y)

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
            placed = self._normalise(r)
            if placed is None:
                continue
            filled = self._fill_nominal_accuracy(self._apply_height_declaration(placed))
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
