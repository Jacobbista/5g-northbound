from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The editor is a blueprint write-client. It reads and writes the canonical
    # blueprint over HTTP from the positioning-engine (the blueprint authority),
    # so there is no shared blueprint PVC. See docs/blueprint-vs-bindings.md.
    positioning_engine_url: str = "http://positioning-engine:8080"

    # Base URL of the wifi-adapter adapter. The placement-editor proxies
    # calibration requests through to it (so the browser does not need CORS
    # to talk to the adapter directly). Default points at the in-cluster
    # service name; docker compose overrides this via env.
    wifi_adapter_url: str = "http://wifi-adapter:8080"

    # Upstream for the vendor discovery proxy (browser -> placement-editor
    # -> vendor-adapter). Lets the editor's sync panel list devices from
    # whichever vendor the vendor-adapter has loaded as its current schema.
    # Multi-vendor setups would deploy one vendor-adapter per vendor and
    # expose them as N URLs; not modelled here yet.
    vendor_adapter_url: str = "http://vendor-adapter:8080"

    # Base URL of the camara-gateway, the Asset Identity Map authority. The
    # editor proxies GET/PUT /assets so an onboarding client (the KELT
    # dashboard) can read + merge the registry over the editor's single
    # backend. Asset onboarding UI itself is KELT's, not the editor's.
    camara_gateway_url: str = "http://camara-gateway:8080"


@lru_cache
def get_settings() -> Settings:
    return Settings()
