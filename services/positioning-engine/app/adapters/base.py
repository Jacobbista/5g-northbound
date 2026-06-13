from abc import ABC, abstractmethod
from dataclasses import dataclass
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
    accuracy_m: float
    confidence: float
    frame: Literal["local", "wgs84"] = "local"
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    latitude: float = 0.0
    longitude: float = 0.0
    timestamp: Optional[float] = None


class Adapter(ABC):
    @abstractmethod
    async def get_measurement(self, device_id: str) -> Optional[Measurement]:
        """Return latest measurement or None if adapter unavailable."""
