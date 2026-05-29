from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    wifi_config_path: str = "/app/config/wifi-config.json"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
