from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..adapters.base import Measurement
from ..models import FloorPlan


@dataclass
class FusedPosition:
    """Output of a fusion strategy in the venue frame."""

    x: float
    y: float
    # Height above the venue floor, fused over the measurements that carry
    # one. None when no contributing source measured height.
    z: Optional[float]
    accuracy: float
    sources: list[str]
    timestamp: Optional[float] = None
    # One-sigma error of z. None when z is None or when a measurement that
    # contributed to z reported no vertical error.
    verticalAccuracy: Optional[float] = None
    # Latest moment the fused position is known to hold, epoch seconds: the
    # earliest established time among the contributions. Attached after
    # fusion from the sources' declared reporting models.
    establishedAt: Optional[float] = None
    # Every contribution is as recent as its source can provide.
    current: bool = False
    # Most recent last-communication across the fused sources, epoch seconds.
    # Attached after fusion (strategies do not compute it); drives liveness
    # downstream. None when no contributing source reported one.
    lastSeen: Optional[float] = None
    # Vendor fidelity carried from a single routed source (stream tier);
    # attached after fusion, not computed by strategies.
    diagnostics: dict = field(default_factory=dict)


class FusionStrategy(Protocol):
    """Combines N adapter measurements (all in the venue frame) into one position.

    Implementations may be stateless or hold per-device history (e.g. Kalman).
    """

    name: str

    def fuse(
        self,
        device_id: str,
        measurements: list[Measurement],
        floor_plan: FloorPlan,
    ) -> Optional[FusedPosition]: ...
