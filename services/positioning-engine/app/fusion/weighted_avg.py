import math
from typing import Optional

from ..adapters.base import Measurement
from ..models import FloorPlan
from .base import FusedPosition

# A reported accuracy of exactly 0.0 is a real value some vendors send (Wittra
# has been observed to send it, apparently while a fix is still converging),
# not a defect in this project's own data. Taken literally it drives the
# weight and the output accuracy to infinity, so floor it here rather than
# reject the measurement: the fix stays visible with a small (not fabricated
# perfect) accuracy instead of the request failing outright.
_MIN_ACCURACY_M = 0.01


class WeightedAvgFusion:
    """Baseline strategy: weighted mean with w = confidence / accuracy.

    Output accuracy is the inverse-RMS of input accuracies. Both use each
    measurement's accuracy floored at `_MIN_ACCURACY_M`.
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

        accuracies = [max(m.accuracy, _MIN_ACCURACY_M) for m in measurements]
        weights = [m.confidence / a for m, a in zip(measurements, accuracies)]
        total_w = sum(weights)
        if total_w <= 0:
            return None

        x = sum(w * m.x for w, m in zip(weights, measurements)) / total_w
        y = sum(w * m.y for w, m in zip(weights, measurements)) / total_w
        z = sum(w * m.z for w, m in zip(weights, measurements)) / total_w

        accuracy = 1.0 / math.sqrt(sum(1.0 / (a ** 2) for a in accuracies))
        sources = [m.source for m in measurements]
        times = [m.timestamp for m in measurements if m.timestamp is not None]
        timestamp = max(times) if times else None

        return FusedPosition(
            x=x, y=y, z=z,
            accuracy=accuracy,
            sources=sources,
            timestamp=timestamp,
        )
