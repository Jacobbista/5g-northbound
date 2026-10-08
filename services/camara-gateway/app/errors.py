import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .obs import correlator_var

log = logging.getLogger(__name__)


class CamaraError(Exception):
    """Error rendered as the CAMARA {status, code, message} envelope."""

    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def _envelope(status: int, code: str, message: str, request: Request) -> JSONResponse:
    # The correlator rides every error too. The hop middleware sets it on the
    # responses that return through it; an unhandled error is answered outside
    # it, so the header is set here.
    cid = correlator_var.get()
    return JSONResponse(
        status_code=status,
        content={"status": status, "code": code, "message": message},
        headers={"x-correlator": cid} if cid else None,
    )


async def camara_error_handler(request: Request, exc: CamaraError) -> JSONResponse:
    return _envelope(exc.status, exc.code, exc.message, request)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _envelope(
        400,
        "INVALID_ARGUMENT",
        "Client specified an invalid argument, request body or query param.",
        request,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return _envelope(500, "INTERNAL", "Internal server error.", request)
