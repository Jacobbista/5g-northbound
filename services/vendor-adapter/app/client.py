"""Outbound HTTP client: builds auth, substitutes path vars, calls vendor."""

import logging
import os
from typing import Optional

import httpx

from .obs import corr_headers
from .schema import AuthBasic, AuthBearer, AuthHeader, AuthNone, Schema

log = logging.getLogger(__name__)


def _resolve_env(name: str) -> Optional[str]:
    val = os.environ.get(name)
    if val is None or val == "":
        return None
    return val


def base_url(schema: Schema) -> Optional[str]:
    """The vendor API root, from the environment variable the schema names.

    No fallback: the schema document carries the NAME of the variable, never a
    vendor URL, so an unset variable is a misconfiguration like a missing path
    var and the callers turn it into a 503.
    """
    val = _resolve_env(schema.baseUrl.env)
    if val is None:
        log.warning("missing required env var %s for baseUrl", schema.baseUrl.env)
        return None
    return val.rstrip("/")


def _substitute_path_vars(schema: Schema, device_id: str) -> Optional[str]:
    """Render `path` by substituting {device_id} plus any pathVars from env.

    Returns None if a required env var is unset - the caller maps this to a
    503 so the operator sees that the pod is misconfigured.
    """
    path = schema.path
    values: dict[str, str] = {"device_id": device_id}
    for name, ref in schema.pathVars.items():
        val = _resolve_env(ref.env)
        if val is None:
            log.warning("missing required env var %s for pathVars.%s", ref.env, name)
            return None
        values[name] = val
    try:
        return path.format(**values)
    except KeyError as exc:
        log.warning("path references unknown variable %s", exc)
        return None


def build_auth_headers(schema: Schema) -> Optional[dict[str, str]]:
    """Build outbound auth headers from the schema and the current env.

    Returns None if a referenced env var is missing - the caller treats that
    as a configuration error rather than silently sending an unauthenticated
    request.
    """
    auth = schema.auth
    if isinstance(auth, AuthNone):
        return {}
    if isinstance(auth, AuthBasic):
        user = _resolve_env(auth.username.env)
        pwd = _resolve_env(auth.password.env)
        if user is None or pwd is None:
            log.warning("basic auth requires %s and %s", auth.username.env, auth.password.env)
            return None
        import base64
        token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
        return {"Authorization": f"Basic {token}"}
    if isinstance(auth, AuthBearer):
        tok = _resolve_env(auth.token.env)
        if tok is None:
            log.warning("bearer auth requires %s", auth.token.env)
            return None
        return {"Authorization": f"Bearer {tok}"}
    if isinstance(auth, AuthHeader):
        val = _resolve_env(auth.value.env)
        if val is None:
            log.warning("header auth requires %s", auth.value.env)
            return None
        return {auth.header: val}
    return None


# Source-side transports this binary can actually drive, as opposed to the ones
# the schema grammar accepts (`Schema.transport`, which also names `mqtt` and
# `webhook` as extension points). Served on GET /contract so a deploy dashboard
# reads the implemented set from the image instead of assuming it, and declared
# here, next to the code that would have to branch, so the two cannot drift.
IMPLEMENTED_TRANSPORTS = ("rest",)


async def fetch(schema: Schema, device_id: str) -> Optional[dict]:
    """One GET against the vendor for one device.

    Returns the parsed JSON body on 200, or None on 404 / 401 / 5xx / network
    error / misconfiguration. Logs noisily for non-404 failures so the
    operator sees what went wrong without a debugger.
    """
    if schema.transport not in IMPLEMENTED_TRANSPORTS:
        log.warning(
            "vendor %s uses transport '%s'; this image implements %s",
            schema.vendor, schema.transport, ", ".join(IMPLEMENTED_TRANSPORTS),
        )
        return None
    path = _substitute_path_vars(schema, device_id)
    if path is None:
        return None
    headers = build_auth_headers(schema)
    if headers is None:
        return None
    root = base_url(schema)
    if root is None:
        return None
    headers.update(corr_headers())
    url = f"{root}{path}"
    try:
        async with httpx.AsyncClient(timeout=schema.requestTimeout) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("vendor %s unreachable: %s", schema.vendor, exc)
        return None
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        log.warning("vendor %s -> %d (%s)", schema.vendor, resp.status_code, resp.text[:200])
        return None
    try:
        return resp.json()
    except ValueError as exc:
        log.warning("vendor %s returned non-JSON: %s", schema.vendor, exc)
        return None


async def fetch_path(schema: Schema, device_id: str, override_path: str, pathVars: dict) -> Optional[dict]:
    """GET an arbitrary vendor path (with {device_id} + the given pathVars)
    using the schema's base URL and auth. Reused by the on-demand diagnostics
    fetches. Returns parsed JSON on 200, or None on any error."""
    values: dict[str, str] = {"device_id": device_id}
    for name, ref in pathVars.items():
        val = _resolve_env(ref.env)
        if val is None:
            log.warning("missing env %s for diagnostics path var %s", ref.env, name)
            return None
        values[name] = val
    try:
        rendered = override_path.format(**values)
    except KeyError as exc:
        log.warning("diagnostics path references unknown variable %s", exc)
        return None
    headers = build_auth_headers(schema)
    if headers is None:
        return None
    root = base_url(schema)
    if root is None:
        return None
    headers.update(corr_headers())
    url = f"{root}{rendered}"
    try:
        async with httpx.AsyncClient(timeout=schema.requestTimeout) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("vendor %s diagnostics unreachable: %s", schema.vendor, exc)
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def _substitute_discover_path_vars(schema: Schema) -> Optional[str]:
    """Render the discover endpoint path from the schema + env vars. No
    {device_id} substitution here (it is a list endpoint, not per-device).
    Returns None if a required env var is missing."""
    if schema.discover is None:
        return None
    path = schema.discover.path
    values: dict[str, str] = {}
    for name, ref in schema.discover.pathVars.items():
        val = _resolve_env(ref.env)
        if val is None:
            log.warning("missing required env var %s for discover.pathVars.%s", ref.env, name)
            return None
        values[name] = val
    try:
        return path.format(**values)
    except KeyError as exc:
        log.warning("discover.path references unknown variable %s", exc)
        return None


async def fetch_discover_page(
    schema: Schema, page: Optional[int] = None
) -> Optional[dict]:
    """One GET against the vendor's list endpoint. Returns the parsed
    JSON body on success, or None on auth / network / misconfig errors.

    When pagination is enabled, `page` selects the 1-indexed page; the
    caller is responsible for walking pages until the accumulated list
    reaches the declared total. Pagination type "none" ignores `page`.

    Set VENDOR_ADAPTER_DEBUG=1 in the pod to log full URLs + truncated
    response bodies; useful when debugging a new vendor schema or
    chasing why a real cloud is returning fewer devices than expected.
    """
    if schema.discover is None:
        return None
    path = _substitute_discover_path_vars(schema)
    if path is None:
        return None
    headers = build_auth_headers(schema)
    if headers is None:
        return None
    root = base_url(schema)
    if root is None:
        return None
    params: dict[str, str] = {}
    pag = schema.discover.pagination
    if pag.type == "page" and page is not None:
        params[pag.pageParam] = str(page)
        params[pag.sizeParam] = str(pag.pageSize)
    url = f"{root}{path}"
    debug = os.environ.get("VENDOR_ADAPTER_DEBUG", "0") not in ("", "0", "false", "False")
    if debug:
        log.info("discover: GET %s params=%s", url, params)
    try:
        async with httpx.AsyncClient(timeout=schema.requestTimeout) as client:
            resp = await client.get(url, headers=headers, params=params or None)
    except httpx.HTTPError as exc:
        log.warning("vendor %s discover unreachable: %s", schema.vendor, exc)
        return None
    if resp.status_code != 200:
        log.warning(
            "vendor %s discover -> %d (%s)",
            schema.vendor, resp.status_code, resp.text[:500],
        )
        return None
    try:
        body = resp.json()
    except ValueError as exc:
        log.warning("vendor %s discover non-JSON: %s", schema.vendor, exc)
        return None
    if debug:
        # Dump first 800 chars of the response so the operator can see
        # whether the array key matches `listPath`, what fields each
        # entry carries, and whether positions are populated for offline
        # devices.
        import json as _json
        preview = _json.dumps(body)[:800]
        log.info("discover: %s response preview: %s", schema.vendor, preview)
    return body
