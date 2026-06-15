import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .adapters.http import HttpAdapter
from .config import adapter_options, settings
from .fusion.registry import get_strategy
from .models import Floor, FloorPlan, GpsOrigin
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


def _floor_plan_from_blueprint(raw: dict) -> FloorPlan:
    """Build the engine's FloorPlan from the placement-editor blueprint
    (layout.json). The engine only needs gps_origin for the northbound WGS84
    conversion; the blueprint authors exactly that as floor_plans[0].georef
    (with a legacy top-level gps_origin as fallback). A single Floor is
    synthesised from the floor-plan extent (or the first room) so the
    FloorPlan stays valid and bounds are the real venue, not the generic box.
    """
    fps = raw.get("floor_plans") or []
    georef = (fps[0].get("georef") if fps else None) or raw.get("gps_origin") or {}
    gps = None
    if georef.get("latitude") is not None and georef.get("longitude") is not None:
        gps = GpsOrigin(
            latitude=float(georef["latitude"]),
            longitude=float(georef["longitude"]),
            azimuth_deg=float(georef.get("azimuth_deg") or 0.0),
            altitude_m=georef.get("altitude_m"),
        )
    w = h = None
    if fps:
        g = fps[0].get("georef") or {}
        w, h = g.get("width_m"), g.get("height_m")
    rooms = raw.get("rooms") or []
    if (not w or not h) and rooms:
        w, h = rooms[0].get("width_m"), rooms[0].get("height_m")
    floor = Floor(
        id=0,
        label=(fps[0].get("label") if fps else None) or "Floor",
        width_m=float(w or 20.0),
        depth_m=float(h or 30.0),
        height_m=3.0,
    )
    return FloorPlan(version=2, gps_origin=gps, floors=[floor])


def _load_floor_plan() -> FloorPlan:
    # Prefer the shared blueprint when LAYOUT_PATH is set (same file the
    # editor writes and the demo / wifi-positioning read), so the authored
    # georef reaches the engine instead of the generic floor-plan.json.
    # Falls back to the legacy floor-plan.json, then a built-in default.
    # Never raises: a bad blueprint degrades to the next source.
    if settings.layout_path:
        try:
            raw = json.loads(Path(settings.layout_path).read_text())
            fp = _floor_plan_from_blueprint(raw)
            log.info(
                "engine: blueprint loaded from LAYOUT_PATH=%s (gps_origin=%s)",
                settings.layout_path, "set" if fp.gps_origin else "absent",
            )
            return fp
        except Exception as exc:
            log.warning(
                "engine: LAYOUT_PATH=%s unreadable (%s); falling back to floor-plan",
                settings.layout_path, exc,
            )
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
