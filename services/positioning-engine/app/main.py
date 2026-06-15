import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .adapters.http import HttpAdapter
from .blueprint import DEFAULT_FLOOR_PLAN, floor_plan_from_blueprint, load_blueprint
from .config import adapter_options, settings
from .fusion.registry import get_strategy
from .routers import adapters as adapters_router
from .routers import blueprint as blueprint_router
from .routers import contract, health, position, websocket
from .services.position_service import PositionService

logging.basicConfig(level=logging.INFO)
# httpx logs every outbound request at INFO. Keep them at WARNING so adapter
# polls (1 per second per device) don't drown out real engine messages.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # The engine is the canonical blueprint authority: load the persisted
    # blueprint (raw layout.json shape) from its writable volume, seeding once
    # from an optional read-only mount on first boot. The raw blueprint is
    # served verbatim over GET /blueprint; the engine itself only derives
    # gps_origin from it for the WGS84 conversion. None -> degrade to the
    # default floor plan (lat/lon 0 with a warning).
    raw = load_blueprint(settings.blueprint_path, settings.blueprint_seed_path)
    app.state.blueprint = raw
    app.state.floor_plan = floor_plan_from_blueprint(raw) if raw else DEFAULT_FLOOR_PLAN
    log.info(
        "engine: blueprint %s (gps_origin=%s)",
        "loaded" if raw else "absent (default floor plan)",
        "set" if app.state.floor_plan.gps_origin else "absent",
    )

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
app.include_router(blueprint_router.router)
app.include_router(position.router)
app.include_router(websocket.router)
app.include_router(adapters_router.router)
