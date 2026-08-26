from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..adapters.base import Measurement
from ..models import FloorPlan


@dataclass
class FusedPosition:
    """Output of a fusion strategy in the floor-plan-local frame."""

    x: float
    y: float
    z: float
    accuracy_m: float
    sources: list[str]
    timestamp: Optional[float] = None
    # Vendor fidelity carried from a single routed source (stream tier);
    # attached after fusion, not computed by strategies.
    diagnostics: dict = field(default_factory=dict)


class FusionStrategy(Protocol):
    """Combines N adapter measurements (all in the local frame) into one position.

    Implementations may be stateless or hold per-device history (e.g. Kalman).
    """

    name: str

    def fuse(
        self,
        device_id: str,
        measurements: list[Measurement],
        floor_plan: FloorPlan,
    ) -> Optional[FusedPosition]: ...
