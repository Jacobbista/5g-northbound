import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .adapters.http import HttpAdapter
from .config import adapter_options, settings
from .fusion.registry import get_strategy
from .models import Floor, FloorPlan
from .routers import adapters as adapters_router
from .routers import contract, health, position, websocket
from .services.position_service import PositionService

logging.basicConfig(level=logging.INFO)
# httpx logs every outbound request at INFO. Keep them at WARNING so adapter
# polls (1 per second per device) don't drown out real engine messages.
logging.getLogger("httpx").setLevel(logging.WARNING)
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

    named_urls = settings.adapter_url_list
    adapters: dict[str, HttpAdapter] = {}
    for name, url in named_urls:
        if name in adapters:
            log.warning("duplicate adapter name '%s' in ADAPTER_URLS; later URL wins", name)
        opts = adapter_options(name)
        adapters[name] = HttpAdapter(name=name, base_url=url, **opts)
        if opts.get("headers"):
            log.info("adapter %s: auth header configured", name)
    if adapters:
        log.info("engine: %d adapter(s) configured: %s", len(adapters), ", ".join(adapters))
    else:
        log.warning("engine: ADAPTER_URLS is empty; no measurements will be produced")
    app.state.adapters = adapters

    primary = get_strategy(settings.fusion_strategy)
    compare = [get_strategy(n) for n in settings.fusion_compare_list if n != settings.fusion_strategy]
    app.state.primary_strategy_name = primary.name
    log.info(
        "engine: fusion primary=%s, compare=[%s]",
        primary.name, ", ".join(s.name for s in compare),
    )

    app.state.position_service = PositionService(
        adapters=adapters,
        floor_plan=app.state.floor_plan,
        device_map=settings.device_map_dict,
        primary_strategy=primary,
        compare_strategies=compare,
    )

    broadcast_task = asyncio.create_task(websocket.broadcast_loop(app))
    yield
    broadcast_task.cancel()
    for a in adapters.values():
        if hasattr(a, "aclose"):
            await a.aclose()


app = FastAPI(title="Positioning Engine", lifespan=lifespan)
app.include_router(health.router)
app.include_router(contract.router)
app.include_router(position.router)
app.include_router(websocket.router)
app.include_router(adapters_router.router)
