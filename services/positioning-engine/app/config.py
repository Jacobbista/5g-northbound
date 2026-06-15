import os
from functools import lru_cache

from pydantic_settings import BaseSettings


DEFAULT_ADAPTER_TIMEOUT_S = 1.0
DEFAULT_API_KEY_HEADER = "X-API-Key"


def adapter_options(name: str) -> dict:
    """Per-adapter runtime options read from environment.

    Lookup uses the adapter name uppercased with non-alphanumerics replaced by
    underscores, so an adapter named "wittra" reads ADAPTER_WITTRA_*.

    Recognised variables:
      ADAPTER_<NAME>_API_KEY         -- token value; mount from a K8s Secret
      ADAPTER_<NAME>_API_KEY_HEADER  -- header name, default X-API-Key
      ADAPTER_<NAME>_TIMEOUT         -- httpx timeout in seconds (float)

    Returns kwargs suitable for HttpAdapter(...).
    """
    key = "".join(c if c.isalnum() else "_" for c in name).upper()
    headers: dict[str, str] = {}
    api_key = os.environ.get(f"ADAPTER_{key}_API_KEY")
    if api_key:
        header_name = os.environ.get(f"ADAPTER_{key}_API_KEY_HEADER", DEFAULT_API_KEY_HEADER)
        headers[header_name] = api_key
    timeout_raw = os.environ.get(f"ADAPTER_{key}_TIMEOUT")
    timeout = DEFAULT_ADAPTER_TIMEOUT_S
    if timeout_raw:
        try:
            timeout = float(timeout_raw)
        except ValueError:
            pass
    return {"timeout": timeout, "headers": headers or None}


class Settings(BaseSettings):
    floor_plan_path: str = "/app/config/floor-plan.json"
    # Path to the authored blueprint (placement-editor layout.json), shared
    # with the demo and wifi-positioning. When set, the engine derives its
    # gps_origin from floor_plans[0].georef instead of the legacy
    # floor-plan.json. Empty -> use floor_plan_path. See docs/blueprint-vs-bindings.md.
    layout_path: str = ""
    websocket_interval_ms: int = 500
    device_ids: str = "uwb-tag-001"

    # Comma-separated named adapter base URLs. Two equivalent forms:
    #   ADAPTER_URLS="wifi=http://wifi-positioning:8080,uwb=http://wittra-uwb:8080"
    #   ADAPTER_URLS="http://wifi-positioning:8080"             # auto-named adapter-0
    # Each entry maps to one HttpAdapter polling GET /measurement/{device_id}.
    # Empty -> no adapters configured; the engine returns no measurements.
    adapter_urls: str = ""

    # Optional per-device routing: "device_id=adapter_name,..."
    # If a device appears here, only the named adapter is polled for it.
    # Devices not listed are polled against all configured adapters.
    device_map: str = ""

    # Primary fusion strategy applied to the measurements returned for a device.
    fusion_strategy: str = "weighted_avg"

    # Optional comparison strategies. When set, the engine also runs these on the
    # same measurements and surfaces their outputs under `fusions` for the demo
    # to render side-by-side. Off by default; this is a research/demo feature.
    fusion_compare: str = ""

    class Config:
        env_file = ".env"

    @property
    def adapter_url_list(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for i, raw in enumerate(self.adapter_urls.split(",")):
            item = raw.strip()
            if not item:
                continue
            if "=" in item:
                name, url = item.split("=", 1)
                out.append((name.strip(), url.strip()))
            else:
                out.append((f"adapter-{i}", item))
        return out

    @property
    def device_map_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for raw in self.device_map.split(","):
            item = raw.strip()
            if not item or "=" not in item:
                continue
            dev, adapter = item.split("=", 1)
            out[dev.strip()] = adapter.strip()
        return out

    @property
    def fusion_compare_list(self) -> list[str]:
        return [s.strip() for s in self.fusion_compare.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
