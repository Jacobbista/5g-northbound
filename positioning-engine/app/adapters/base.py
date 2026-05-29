from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Measurement:
    source: str        # "fiveg" | "wifi" | "uwb"
    x: float
    y: float
    z: float
    accuracy_m: float  # estimated error radius in metres
    confidence: float  # 0.0–1.0; used by weighted fusion
    timestamp: Optional[float] = None  # epoch seconds when measured; None -> "now"


class Adapter(ABC):
    @abstractmethod
    async def get_measurement(self, device_id: str) -> Optional[Measurement]:
        """Return latest measurement or None if adapter unavailable."""
