from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # KEYCLOAK_URL already includes any path prefix (e.g. /auth) - never append it
    keycloak_url: str = "http://keycloak.iam.svc.cluster.local:8080/auth"
    keycloak_realm: str = "5g-testbed"
    # Gateway's own confidential-client secret. MVP does not call Keycloak itself; never log it.
    camara_client_secret: str = "changeme"
    # Empty -> resolve position with the built-in mock
    positioning_engine_url: str = ""
    # Optional: the wifi-positioning adapter, proxied for the demo's anchor
    # panel to read real calibration params (tx_power ref + path-loss n). Empty
    # -> the /anchors/calibration extension returns nothing (degrades).
    wifi_positioning_url: str = ""

    # Freshness cap for the position cache when the request carries no maxAge
    # ("any age" per CAMARA). A request's maxAge, when present, overrides it.
    location_cache_ttl_s: float = 5.0

    required_role: str = "camara-location-read"
    # Asset Identity Map. The gateway is the network authority for assets,
    # exactly as the engine is for the blueprint: it persists the map on a
    # writable store (PVC) and serves GET/PUT /assets. On first boot the store
    # is empty, so it seeds once from a committed, read-only seed file.
    # Conforms to schema/asset.schema.json. No mounted-file-at-runtime path -
    # authoring is over the network (avoids the file-shadow class of bugs).
    asset_store_file: str = "/app/data/assets.json"
    asset_seed_file: str = "/app/config/assets.seed.json"
    skip_auth: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
