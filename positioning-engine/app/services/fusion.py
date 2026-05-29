import math

from ..adapters.base import Measurement


def fuse(measurements: list[Measurement]) -> tuple[float, float, float, float, list[str], float | None]:
    if not measurements:
        raise ValueError("cannot fuse empty measurement list")

    weights = [m.confidence / m.accuracy_m for m in measurements]
    total_w = sum(weights)

    x = sum(w * m.x for w, m in zip(weights, measurements)) / total_w
    y = sum(w * m.y for w, m in zip(weights, measurements)) / total_w
    z = sum(w * m.z for w, m in zip(weights, measurements)) / total_w

    accuracy = 1.0 / math.sqrt(sum(1.0 / (m.accuracy_m ** 2) for m in measurements))
    sources = [m.source for m in measurements]
    # freshest measurement time across fused sources (None if none carry one)
    times = [m.timestamp for m in measurements if m.timestamp is not None]
    timestamp = max(times) if times else None

    return x, y, z, accuracy, sources, timestamp
