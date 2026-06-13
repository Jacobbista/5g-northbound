from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Schema persistence path. Mount a PVC here in K8s so operator changes via
    # PUT /schema survive pod restarts. In docker compose this is a bind-mount.
    schema_file: str = "/app/data/schema.json"

    class Config:
        env_file = ".env"
        # The .env in this directory may carry vendor-specific vars
        # (WITTRA_*, etc.) that the schema reads via os.environ at request
        # time. Ignore them at Settings parse time so they do not break
        # validation; the schema-driven client still picks them up.
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
