import logging

import httpx
from fastapi import Request
from jose import JWTError, jwt

from .config import get_settings
from .errors import CamaraError

log = logging.getLogger(__name__)

_jwks_cache: dict = {}

_UNAUTHENTICATED = (
    "Request not authenticated due to missing, invalid, or expired credentials. "
    "A new authentication is required."
)
_PERMISSION_DENIED = "Client does not have sufficient permissions to perform this action."


def _certs_url() -> str:
    s = get_settings()
    return f"{s.keycloak_url}/realms/{s.keycloak_realm}/protocol/openid-connect/certs"


async def _fetch_jwks() -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(_certs_url(), timeout=5.0)
        resp.raise_for_status()
        return resp.json()


async def _get_jwks() -> dict:
    global _jwks_cache
    if not _jwks_cache:
        _jwks_cache = await _fetch_jwks()
    return _jwks_cache


async def _decode(token: str) -> dict:
    global _jwks_cache
    jwks = await _get_jwks()
    try:
        return jwt.decode(token, jwks, algorithms=["RS256"], options={"verify_aud": False})
    except JWTError:
        # signing keys may have rotated — refresh once then retry
        _jwks_cache = await _fetch_jwks()
        return jwt.decode(token, _jwks_cache, algorithms=["RS256"], options={"verify_aud": False})


async def require_location_role(request: Request) -> dict:
    s = get_settings()
    if s.skip_auth:
        return {}

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise CamaraError(401, "UNAUTHENTICATED", _UNAUTHENTICATED)

    token = header[len("Bearer ") :]
    try:
        claims = await _decode(token)
    except JWTError as exc:
        log.warning("JWT validation failed: %s", exc)
        raise CamaraError(401, "UNAUTHENTICATED", _UNAUTHENTICATED) from exc

    roles = claims.get("realm_access", {}).get("roles", [])
    if s.required_role not in roles:
        raise CamaraError(403, "PERMISSION_DENIED", _PERMISSION_DENIED)

    return claims
