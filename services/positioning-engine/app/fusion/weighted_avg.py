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
    """Baseline strategy: weighted mean with w = confidence / accuracy, and
    w = 1 / accuracy for a source that reports no confidence.

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
        weights = [
            (1.0 if m.confidence is None else m.confidence) / a
            for m, a in zip(measurements, accuracies)
        ]
        total_w = sum(weights)
        if total_w <= 0:
            return None

        x = sum(w * m.x for w, m in zip(weights, measurements)) / total_w
        y = sum(w * m.y for w, m in zip(weights, measurements)) / total_w
        # Height is averaged over the measurements that carry it, with the
        # same weights: a source without height contributes nothing to it.
        with_height = [(w, m) for w, m in zip(weights, measurements) if m.z is not None]
        height_w = sum(w for w, _ in with_height)
        z = sum(w * m.z for w, m in with_height) / height_w if height_w > 0 else None
        # The error of that weighted mean, for independent errors:
        # sqrt(sum(w_i^2 * s_i^2)) / sum(w_i). Unknown as soon as one height
        # in the mean carries no error.
        vertical_accuracy = None
        if z is not None and all(m.verticalAccuracy is not None for _, m in with_height):
            vertical_accuracy = math.sqrt(
                sum((w * max(m.verticalAccuracy, _MIN_ACCURACY_M)) ** 2 for w, m in with_height)
            ) / height_w

        accuracy = 1.0 / math.sqrt(sum(1.0 / (a ** 2) for a in accuracies))
        sources = [m.source for m in measurements]
        # A fused position is no newer than its oldest contribution.
        times = [m.timestamp for m in measurements if m.timestamp is not None]
        timestamp = min(times) if times else None

        return FusedPosition(
            x=x, y=y, z=z,
            accuracy=accuracy,
            verticalAccuracy=vertical_accuracy,
            sources=sources,
            timestamp=timestamp,
        )
