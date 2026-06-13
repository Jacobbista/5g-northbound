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

    # Optional path to the placement-editor blueprint (rooms + anchors).
    # When set, AP positions are taken from `rooms[0].anchors` where
    # `technology == "wifi"`, joined to BSSIDs by anchor `id`. This is
    # how the deployed cluster avoids duplicating positions between the
    # editor's blueprint and the WiFi adapter's config.
    layout_path: Optional[str] = None

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
