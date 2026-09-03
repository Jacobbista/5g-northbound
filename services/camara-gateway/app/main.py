import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from .obs import install_hop_logging
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
    contracts,
    diagnostics,
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
    expose_headers=["x-correlator"],
)


# Mint/echo the x-correlator (CAMARA Commonalities) and log one hop line per
# request. The gateway is the entry point, so it mints when the client sends none.
install_hop_logging(app, "camara-gateway", mint=True)

app.add_exception_handler(CamaraError, camara_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(health.router)
app.include_router(contract.router)
app.include_router(contracts.router)
app.include_router(retrieval.router)
app.include_router(verification.router)
app.include_router(assets.router)
app.include_router(capabilities.router)
app.include_router(anchors.router)
app.include_router(adapters.router)
app.include_router(blueprint.router)
app.include_router(diagnostics.router)
app.include_router(positions_stream.router)
