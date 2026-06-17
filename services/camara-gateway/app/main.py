import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from .errors import (
    CamaraError,
    camara_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from .routers import (
    adapters,
    anchors,
    assets,
    blueprint,
    capabilities,
    contract,
    health,
    positions_stream,
    retrieval,
    verification,
)

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(
    title="Device Location Gateway",
    description="CAMARA Device Location - Retrieval (v0.5) and Verification (v3).",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(CamaraError, camara_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(health.router)
app.include_router(contract.router)
app.include_router(retrieval.router)
app.include_router(verification.router)
app.include_router(assets.router)
app.include_router(capabilities.router)
app.include_router(anchors.router)
app.include_router(adapters.router)
app.include_router(blueprint.router)
app.include_router(positions_stream.router)
