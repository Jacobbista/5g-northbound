import random
from typing import Optional

from ..models import Floor
from .base import Adapter, Measurement

_STEP = 0.3
_SOURCE = "wifi"
_CONFIDENCE = 0.7
_ACCURACY_M = 2.0


class WifiAdapter(Adapter):
    def __init__(self, floor: Floor):
        self._floor = floor
        self._state: dict[str, tuple[float, float, float]] = {}

    def _clamp(self, val: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, val))

    async def get_measurement(self, device_id: str) -> Optional[Measurement]:
        if device_id not in self._state:
            cx = self._floor.width_m / 2
            cy = self._floor.height_m / 2
            cz = self._floor.depth_m / 2
            self._state[device_id] = (cx, cy, cz)

        x, y, z = self._state[device_id]
        x = self._clamp(x + random.uniform(-_STEP, _STEP), 0, self._floor.width_m)
        y = self._clamp(y + random.uniform(-_STEP, _STEP), 0, self._floor.height_m)
        z = self._clamp(z + random.uniform(-_STEP, _STEP), 0, self._floor.depth_m)
        self._state[device_id] = (x, y, z)

        return Measurement(
            source=_SOURCE, x=x, y=y, z=z,
            accuracy_m=_ACCURACY_M, confidence=_CONFIDENCE,
        )
