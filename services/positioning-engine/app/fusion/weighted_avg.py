import math
from typing import Optional

from ..adapters.base import Measurement
from ..models import FloorPlan
from .base import FusedPosition


class WeightedAvgFusion:
    """Baseline strategy: weighted mean with w = confidence / accuracy_m.

    Output accuracy is the inverse-RMS of input accuracies.
    Stateless; one instance per engine process.
    """

    name = "weighted_avg"

    def fuse(
        self,
        device_id: str,
        measurements: list[Measurement],
        floor_plan: FloorPlan,
    ) -> Optional[FusedPosition]:
        if not measurements:
            return None

        weights = [m.confidence / m.accuracy_m for m in measurements]
        total_w = sum(weights)
        if total_w <= 0:
            return None

        x = sum(w * m.x for w, m in zip(weights, measurements)) / total_w
        y = sum(w * m.y for w, m in zip(weights, measurements)) / total_w
        z = sum(w * m.z for w, m in zip(weights, measurements)) / total_w

        accuracy = 1.0 / math.sqrt(sum(1.0 / (m.accuracy_m ** 2) for m in measurements))
        sources = [m.source for m in measurements]
        times = [m.timestamp for m in measurements if m.timestamp is not None]
        timestamp = max(times) if times else None

        return FusedPosition(
            x=x, y=y, z=z,
            accuracy_m=accuracy,
            sources=sources,
            timestamp=timestamp,
        )
