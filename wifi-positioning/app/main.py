import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .config import settings
from .models import WifiConfig
from .routers import health, ingest, measurement
from .wifi import WifiAdapter

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    wifi_cfg = WifiConfig.model_validate_json(Path(settings.wifi_config_path).read_text())
    app.state.wifi_config = wifi_cfg
    app.state.adapter = WifiAdapter(wifi_cfg)
    log.info("wifi-positioning: %d routers, room %g x %g m, algo=%s",
             len(wifi_cfg.routers), wifi_cfg.room_w, wifi_cfg.room_h, wifi_cfg.algorithm)
    yield


app = FastAPI(title="WiFi Positioning Adapter", lifespan=lifespan)
app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(measurement.router)
