import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


class CamaraError(Exception):
    """Error rendered as the CAMARA {status, code, message} envelope."""

    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def _envelope(status: int, code: str, message: str, request: Request) -> JSONResponse:
    # x-correlator is set uniformly (success and error) by the app middleware.
    return JSONResponse(
        status_code=status,
        content={"status": status, "code": code, "message": message},
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
