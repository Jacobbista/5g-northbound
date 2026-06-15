import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import register
from .config import settings
from .routers import health, measurement
from .walker import build_walker

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.walker = build_walker(settings)
    log.info(
        "mock-positioning: source=%s bounds=%.1fx%.1fx%.1f speed=%.2fm/s",
        settings.source, settings.width_m, settings.depth_m, settings.height_m, settings.speed_mps,
    )
    # Announce ourselves to the engine's adapter registry + heartbeat.
    reg_task = asyncio.create_task(register.heartbeat_loop())
    yield
    reg_task.cancel()
    await register.deregister()


app = FastAPI(title="Mock Positioning", lifespan=lifespan)
app.include_router(health.router)
app.include_router(measurement.router)
