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
from .routers import health, retrieval, verification

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Device Location Gateway",
    description="CAMARA Device Location — Retrieval (v0.5) and Verification (v3).",
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
app.include_router(retrieval.router)
app.include_router(verification.router)
