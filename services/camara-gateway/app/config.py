from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # KEYCLOAK_URL already includes any path prefix (e.g. /auth) - never append it
    keycloak_url: str = "http://keycloak.iam.svc.cluster.local:8080/auth"
    keycloak_realm: str = "5g-testbed"
    # Gateway's own confidential-client secret. MVP does not call Keycloak itself; never log it.
    camara_client_secret: str = "changeme"
    smf_url: str = "http://smf.5g.svc.cluster.local:9090"
    # Empty -> resolve position with the built-in mock
    positioning_engine_url: str = ""

    required_role: str = "camara-location-read"
    # JSON map: CAMARA device identifier value -> internal device id (fallback used
    # when device_registry_file is empty or unreadable).
    device_registry: str = "{}"
    # Path to a JSON file describing the device registry. Preferred over
    # device_registry when set. Schema: {"devices": [{"phoneNumber","deviceId","label"}]}.
    device_registry_file: str = ""
    skip_auth: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
