from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    floor_plan_path: str = "/app/config/floor-plan.json"
    websocket_interval_ms: int = 500
    device_ids: str = "uwb-tag-001"
    # Comma-separated HTTP adapter base URLs (each speaks GET /measurement/{id}).
    # Empty -> built-in mock adapters (dev convenience only).
    adapter_urls: str = ""

    class Config:
        env_file = ".env"

    @property
    def adapter_url_list(self) -> list[str]:
        return [u.strip() for u in self.adapter_urls.split(",") if u.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
