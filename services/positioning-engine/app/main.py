import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .blueprint import DEFAULT_FLOOR_PLAN, floor_plan_from_blueprint, load_blueprint
from .config import settings
from .fusion.registry import get_strategy
from .registry import SEED, AdapterRegistry, _safe_aclose
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

    # Adapter registry: the engine is the authority. Restore persisted
    # seed/manual entries; if the registry is still empty (true cold start),
    # apply ADAPTER_URLS as a one-time seed. A re-applied ADAPTER_URLS never
    # clobbers a live/persisted registry. Self-registered entries are not
    # persisted - they repopulate via heartbeat.
    registry = AdapterRegistry(
        ttl_s=settings.adapter_ttl_s,
        heartbeat_s=settings.adapter_heartbeat_s,
        persist_path=settings.adapter_registry_path,
    )
    registry.load_persisted()
    if registry.is_empty():
        for name, url in settings.adapter_url_list:
            registry.upsert(name, url, "adapter", SEED)
        if not registry.is_empty():
            registry.persist()
            log.info("engine: seeded registry from ADAPTER_URLS: %s",
                     ", ".join(registry.adapters))
    else:
        log.info("engine: registry restored with %d declared adapter(s)", len(registry.adapters))
    app.state.registry = registry
    # Back-compat alias: some call sites read app.state.adapters directly.
    app.state.adapters = registry.adapters

    primary = get_strategy(settings.fusion_strategy)
    compare = [get_strategy(n) for n in settings.fusion_compare_list if n != settings.fusion_strategy]
    app.state.primary_strategy_name = primary.name
    log.info(
        "engine: fusion primary=%s, compare=[%s]",
        primary.name, ", ".join(s.name for s in compare),
    )

    app.state.position_service = PositionService(
        adapters=registry.adapters,  # live dict, mutated in place by the registry
        floor_plan=app.state.floor_plan,
        device_map=settings.device_map_dict,
        primary_strategy=primary,
        compare_strategies=compare,
    )

    broadcast_task = asyncio.create_task(websocket.broadcast_loop(app))
    evict_task = asyncio.create_task(_evict_loop(app))
    yield
    broadcast_task.cancel()
    evict_task.cancel()
    await registry.aclose()


async def _evict_loop(app: FastAPI):
    """Periodically drop self-registered adapters that stopped heartbeating."""
    registry = app.state.registry
    interval = max(5.0, settings.adapter_heartbeat_s)
    try:
        while True:
            await asyncio.sleep(interval)
            orphans = registry.evict_expired()
            if orphans:
                registry.persist()
                for a in orphans:
                    await _safe_aclose(a)
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Positioning Engine", lifespan=lifespan)
app.include_router(health.router)
app.include_router(contract.router)
app.include_router(blueprint_router.router)
app.include_router(position.router)
app.include_router(websocket.router)
app.include_router(adapters_router.router)
