from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Path to the WiFi adapter's tunables + per-AP BSSID bindings. When
    # LAYOUT_PATH is set, this file should only carry tunables + bindings
    # (id → bssids list) - positions are joined from the blueprint.
    # When LAYOUT_PATH is unset, this file must also carry router x/y
    # (legacy mode, kept for tests and standalone runs).
    wifi_config_path: str = "/app/config/wifi-config.json"

    # The blueprint (AP positions) is fetched over HTTP from the engine, the
    # blueprint authority. Positions are taken from `rooms[0].anchors` where
    # `technology == "wifi"`, joined to BSSIDs by anchor `id`. The adapter
    # tolerates the engine not being ready yet (retry + degraded boot).
    positioning_engine_url: str = "http://positioning-engine:8080"
    blueprint_fetch_attempts: int = 5
    blueprint_fetch_backoff_s: float = 1.0

    # Optional local blueprint file, used only as an offline fallback when the
    # engine cannot be reached (dev / standalone). Unset in the cluster.
    layout_path: Optional[str] = None

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
