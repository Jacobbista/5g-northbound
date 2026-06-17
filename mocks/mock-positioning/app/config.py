from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Reported source tag on every measurement.
    source: str = "mock"
    # Device ids this mock serves (CSV). The walker can synthesise a position
    # for ANY id, so without this it would answer for every device and pollute
    # fusion when the engine fans out (no DEVICE_MAP). Empty = serve all (legacy
    # / standalone). Set it so the mock 404s for devices it does not own, making
    # capability-style fan-out routing safe.
    device_ids: str = ""
    # Floor bounds (metres); positions are clamped inside the box. If a
    # layout file is configured, its room bounds override these at startup.
    width_m: float = 20.0
    depth_m: float = 30.0
    height_m: float = 3.0
    # Legacy random-walk step per poll (metres). Kept so old tests / configs
    # still parse cleanly; the waypoint walker does not use it.
    step_m: float = 0.3
    # Walking speed for the waypoint walker (metres per second). 1.0 m/s
    # matches a person ambling through a room - slower than purposeful
    # walking (~1.4 m/s) so the demo reads as "indoor mobility".
    speed_mps: float = 1.0
    # Optional path to a placement-editor layout JSON. When set + readable,
    # the walker loads inner walls + openings and constrains movement to
    # the room geometry. When unset, the walker just rectangles inside the
    # AABB defined by width_m × depth_m.
    layout_path: str | None = None
    # Fixed reported accuracy and confidence for the synthetic measurement.
    accuracy_m: float = 1.5
    confidence: float = 0.6
    # Seed for reproducible trajectories; 0 = non-deterministic.
    rng_seed: int = 0

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
