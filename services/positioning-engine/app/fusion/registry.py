from .base import FusionStrategy
from .weighted_avg import WeightedAvgFusion

# Future entries: KalmanFusion, OutlierRejectFusion, GatedFusion (see docs/fusion-strategies.md)
STRATEGIES: dict[str, type[FusionStrategy]] = {
    "weighted_avg": WeightedAvgFusion,
}


def get_strategy(name: str) -> FusionStrategy:
    try:
        cls = STRATEGIES[name]
    except KeyError as exc:
        known = ", ".join(STRATEGIES)
        raise ValueError(f"unknown fusion strategy '{name}' (known: {known})") from exc
    return cls()
