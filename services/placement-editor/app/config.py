from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Path the editor reads from and writes to. Mounted as a volume in compose,
    # mounted from a ConfigMap-backed PVC in Kubernetes.
    layout_file: str = "/app/data/layout.json"

    # Base URL of the wifi-positioning adapter. The placement-editor proxies
    # calibration requests through to it (so the browser does not need CORS
    # to talk to the adapter directly). Default points at the in-cluster
    # service name; docker compose overrides this via env.
    wifi_positioning_url: str = "http://wifi-positioning:8080"

    # Upstream for the vendor discovery proxy (browser -> placement-editor
    # -> rest-adapter). Lets the editor's sync panel list devices from
    # whichever vendor the rest-adapter has loaded as its current schema.
    # Multi-vendor setups would deploy one rest-adapter per vendor and
    # expose them as N URLs; not modelled here yet.
    rest_adapter_url: str = "http://rest-adapter:8080"


@lru_cache
def get_settings() -> Settings:
    return Settings()
