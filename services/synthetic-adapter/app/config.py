from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Reported source tag on every measurement.
    source: str = "synthetic"
    # Positioning technology this synthetic source stands in for. An on-premise
    # RTLS substitute is typically UWB. Surfaced as `source_class` on /devices so
    # onboarding classification sees the same shape a real source declares.
    source_class: str = "uwb"
    # Device ids this mock serves (CSV). The walker can synthesise a position
    # for ANY id, so without this it would answer for every device and pollute
    # fusion when the engine fans out (no DEVICE_MAP). Empty = serve all (legacy
    # / standalone). Set it so the mock 404s for devices it does not own, making
    # capability-style fan-out routing safe.
    device_ids: str = ""
    # Fixed infrastructure ids (CSV): the anchors/relays a real on-premise RTLS
    # exposes alongside its tracked tags. Surfaced on /devices with
    # role=infrastructure so onboarding sees both classes (an anchor is never
    # onboarded as an asset). Not walked - infrastructure is fixed, not tracked -
    # so /measurement 404s for these.
    anchor_ids: str = ""
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
    # Reported accuracy and confidence are synthesised per fix, not frozen.
    # There is no measurement behind them: this adapter locates nothing. They
    # stand in for what a source of the declared accuracy_class would report,
    # so that everything downstream (fusion weighting, the rendered radius, the
    # demo's imprecise threshold) receives a realistic distribution instead of
    # one constant that exercises no branch.
    #
    # Indoor error is not symmetric. An obstructed path makes the first arrival
    # LONGER than the truth and never shorter, and inverting RSSI to a distance
    # turns the log-normal shadowing of the dB domain into a right-skewed
    # spread in metres. So the generator sits near the good end of the band and
    # excursions run toward the bad end, never past either edge: the band is
    # what accuracy_class declares, and a draw outside it would contradict the
    # declaration.
    accuracy_min_m: float = 1.5
    accuracy_max_m: float = 6.0
    confidence_min: float = 0.35
    confidence_max: float = 0.95
    # Quality is autocorrelated, not redrawn per tick: indoor degradation comes
    # in episodes (an obstruction between a tag and the anchors lasts seconds,
    # not milliseconds). Independent draws would give the right histogram and
    # the wrong texture, a radius that flickers like a rendering fault.
    degrade_probability: float = 0.015   # per second, chance an episode starts
    degrade_seconds: float = 8.0         # how long one lasts
    # Seed for reproducible trajectories; 0 = non-deterministic.
    rng_seed: int = 0

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
