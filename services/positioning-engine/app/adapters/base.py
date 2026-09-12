from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class Measurement:
    """A position estimate from a single adapter.

    `frame` declares which coordinate fields are valid:
      - "local": x, y, z are metres in the floor-plan-local frame.
      - "wgs84": latitude, longitude are absolute; y (height) may still be set.

    The engine converts every measurement to the local frame before fusion,
    using the floor plan's gps_origin. Strategies always see local measurements.
    """

    source: str
    # metres; x-unit on the wire schema. None when the source has no genuine
    # per-fix accuracy to report (PositionService fills a nominal value from
    # the source's accuracy_class before fusion; fusion itself never sees
    # None - see position_service.py).
    accuracy: Optional[float] = None
    confidence: float = 0.0
    frame: Literal["local", "wgs84"] = "local"
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    latitude: float = 0.0
    longitude: float = 0.0
    timestamp: Optional[float] = None
    # When the device last communicated with its source, epoch seconds. Distinct
    # from `timestamp` (the fix time, which freezes for a still asset that keeps
    # reporting): this is what liveness is derived from. None when the source
    # exposes no such signal.
    lastSeen: Optional[float] = None
    # Optional vendor fidelity (stream tier, e.g. {"motion": ...}); passthrough.
    diagnostics: dict = field(default_factory=dict)


class Adapter(ABC):
    @abstractmethod
    async def get_measurement(self, device_id: str) -> Optional[Measurement]:
        """Return latest measurement or None if adapter unavailable."""
