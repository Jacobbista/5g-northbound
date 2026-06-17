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
        # signing keys may have rotated - refresh once then retry
        _jwks_cache = await _fetch_jwks()
        return jwt.decode(token, _jwks_cache, algorithms=["RS256"], options={"verify_aud": False})


async def validate_token(token: str) -> dict | None:
    """Decode a bearer token and verify the required role.

    Returns the claims dict on success. Returns None when authentication
    fails (bad signature, missing token, missing role). Honours SKIP_AUTH
    by returning an empty dict. Used by both the REST `require_location_role`
    dependency and the WebSocket positions stream, since the latter has
    no Request object to pull headers from.
    """
    s = get_settings()
    if s.skip_auth:
        return {}
    if not token:
        return None
    try:
        claims = await _decode(token)
    except JWTError as exc:
        log.warning("JWT validation failed: %s", exc)
        return None
    roles = claims.get("realm_access", {}).get("roles", [])
    if s.required_role not in roles:
        return None
    return claims


def consumer_org(claims: dict | None) -> str | None:
    """Tenant of the calling consumer, from the token `org` claim (2-legged
    enterprise auth). None when absent - dev SKIP_AUTH ({}), or an untenanted
    token - which the callers treat as 'see everything'. Production issues one
    per-consumer Keycloak client carrying its `org`."""
    return (claims or {}).get("org")


async def require_location_role(request: Request) -> dict:
    s = get_settings()
    if s.skip_auth:
        return {}

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise CamaraError(401, "UNAUTHENTICATED", _UNAUTHENTICATED)

    token = header[len("Bearer ") :]
    claims = await validate_token(token)
    if claims is None:
        # validate_token already discriminated between bad signature and
        # missing role, but the CAMARA envelope only carries the binary
        # outcome here. Try decoding again to surface the right status.
        try:
            decoded = await _decode(token)
        except JWTError as exc:
            raise CamaraError(401, "UNAUTHENTICATED", _UNAUTHENTICATED) from exc
        roles = decoded.get("realm_access", {}).get("roles", [])
        if s.required_role not in roles:
            raise CamaraError(403, "PERMISSION_DENIED", _PERMISSION_DENIED)
        raise CamaraError(401, "UNAUTHENTICATED", _UNAUTHENTICATED)
    return claims
