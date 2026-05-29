import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .adapters.http import HttpAdapter
from .adapters.mock_fiveg import FiveGAdapter
from .adapters.mock_uwb import UwbAdapter
from .adapters.mock_wifi import WifiAdapter as MockWifiAdapter
from .config import settings
from .models import Floor, FloorPlan
from .routers import health, position, websocket

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

DEFAULT_FLOOR_PLAN = FloorPlan(
    version=1,
    floors=[Floor(id=0, label="Default", width_m=20.0, depth_m=30.0, height_m=3.0)],
)


def _load_floor_plan() -> FloorPlan:
    try:
        return FloorPlan.model_validate_json(Path(settings.floor_plan_path).read_text())
    except FileNotFoundError:
        log.warning("floor-plan.json not found at %s, using default", settings.floor_plan_path)
        return DEFAULT_FLOOR_PLAN


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.floor_plan = _load_floor_plan()

    urls = settings.adapter_url_list
    if urls:
        # production / wired path: each URL is an independent adapter pod
        adapters = [HttpAdapter(u) for u in urls]
        log.info("engine: %d HTTP adapter(s) configured: %s", len(urls), ", ".join(urls))
    else:
        # dev fallback: built-in random-walk adapters; no external pods needed
        ground = app.state.floor_plan.floors[0]
        adapters = [FiveGAdapter(ground), MockWifiAdapter(ground), UwbAdapter(ground)]
        log.info("engine: ADAPTER_URLS empty, using built-in mock adapters")
    app.state.adapters = adapters

    broadcast_task = asyncio.create_task(websocket.broadcast_loop(app))
    yield
    broadcast_task.cancel()
    for a in adapters:
        if hasattr(a, "aclose"):
            await a.aclose()


app = FastAPI(title="Positioning Engine", lifespan=lifespan)
app.include_router(health.router)
app.include_router(position.router)
app.include_router(websocket.router)
