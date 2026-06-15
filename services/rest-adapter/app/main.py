import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .routers import contract as contract_router
from .routers import discover as discover_router
from .routers import health, measurement
from .routers import schema as schema_router
from .store import State, load_schema

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Degraded boot: the store always exists. A missing schema is a normal
    # state (operators PUT one to /schema at runtime); a malformed mounted
    # schema is logged and skipped rather than crashing the process, so
    # /health and /contract keep answering.
    app.state.store = State()
    try:
        loaded = load_schema(settings.schema_file)
    except Exception as exc:
        loaded = None
        log.error("schema at %s failed to load: %s", settings.schema_file, exc)
    if loaded:
        app.state.store.schema = loaded
        log.info("loaded schema for vendor=%s from %s", loaded.vendor, settings.schema_file)
    else:
        log.warning(
            "no schema loaded; PUT one to /schema or mount it at %s",
            settings.schema_file,
        )
    yield


app = FastAPI(
    title="REST vendor adapter",
    description="Schema-driven adapter: translates one vendor's REST response into the engine's Measurement.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(health.router)
app.include_router(contract_router.router)
app.include_router(schema_router.router)
app.include_router(measurement.router)
app.include_router(discover_router.router)
