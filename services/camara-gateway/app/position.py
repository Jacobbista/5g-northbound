import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .assets import Asset, asset_by_id
from .config import get_settings
from .errors import CamaraError
from .models import Device

log = logging.getLogger(__name__)

# Fixed reference point for the mock; jittered per call so the demo shows motion.
_MOCK_CENTER = (45.064312, 7.659154)
_MOCK_RADIUS_M = 50.0

# Engine call resilience. A 5xx or network error on the engine call gets one
# retry after a short backoff - most engine restarts and brief blips clear
# within a few hundred milliseconds. We do NOT retry 404 (legitimate "no fix").
_RETRY_BACKOFF_S = 0.2
_RETRY_ATTEMPTS = 2  # initial attempt + 1 retry
_ENGINE_REQUEST_TIMEOUT_S = 5.0
_ADAPTERS_REQUEST_TIMEOUT_S = 2.0


@dataclass
class Position:
    latitude: float
    longitude: float
    radius_m: float
    last_location_time: datetime
    altitude_m: float | None = None
    vertical_accuracy_m: float | None = None


# Position cache: the last fix seen per (positioning_id, source). Freshness is
# judged by the fix's own last_location_time, not by insert time, so a single
# age metric drives both cache reuse and the CAMARA maxAge contract.
_cache: dict[tuple[str, str | None], "Position"] = {}


def reset_cache() -> None:
    _cache.clear()


@dataclass
class PositionDetails:
    """Richer payload for the /devices/{id}/details vendor endpoint.

    Surfaces fields the engine produces but the CAMARA Location response hides
    (strategy, sources, confidence). Consumed only by the demo UI.
    """

    latitude: float
    longitude: float
    radius_m: float
    last_location_time: datetime
    strategy: str
    sources: list[str]
    altitude_m: float | None = None


def _asset_id_from_nai(nai: str) -> str | None:
    """Parse the asset-alias NAI scheme `<asset_id>@<org>.assets`.

    Returns the asset_id when the suffix matches, else None (so a stray NAI
    doesn't accidentally resolve). The scheme is the optional CAMARA-stock
    carrier; `device.assetId` is the first-class path.
    """
    local, sep, domain = nai.partition("@")
    if sep and domain.endswith(".assets") and local:
        return local
    return None


def resolve_asset(device: Device) -> Asset:
    """Resolve a CAMARA device identifier to an asset. No subscriber lookup.

    `assetId` is first-class; `networkAccessIdentifier` is accepted only via
    the `<asset_id>@<org>.assets` alias scheme. Public-network identifiers are
    rejected with UNSUPPORTED_IDENTIFIER (they are the assumption this profile
    drops); an unknown asset is a 404 - there is no "fall back to the raw
    value" path.
    """
    if device.has_public_identifier():
        raise CamaraError(
            422, "UNSUPPORTED_IDENTIFIER",
            "Public-network identifiers are not supported; identify the asset by assetId.",
        )
    asset_id = device.assetId
    if not asset_id and device.networkAccessIdentifier:
        asset_id = _asset_id_from_nai(device.networkAccessIdentifier)
    if not asset_id:
        raise CamaraError(422, "MISSING_IDENTIFIER", "The asset cannot be identified.")
    asset = asset_by_id(asset_id)
    if asset is None:
        raise CamaraError(404, "IDENTIFIER_NOT_FOUND", "Asset not found.")
    return asset


def authorize_asset(asset: Asset, claims: dict | None) -> None:
    """Tenant gate (gap 3, 2-legged): when the token carries an `org` claim it
    must match the asset's org. No claim (dev SKIP_AUTH / untenanted token)
    passes - production issues per-consumer tokens scoped with `org`. A
    cross-tenant asset is reported as not-found, not forbidden, so a consumer
    cannot probe the existence of other tenants' assets."""
    org = (claims or {}).get("org")
    if org and asset.org != org:
        raise CamaraError(404, "IDENTIFIER_NOT_FOUND", "Asset not found.")


async def _engine_get(path: str, *, timeout: float = _ENGINE_REQUEST_TIMEOUT_S) -> dict:
    """One GET against the engine with a short retry on transient failure.

    Retries once on network errors and 5xx responses; never retries on 4xx
    (404 = "no fix", 401/403 = misconfiguration - both should surface fast).
    Raises the final httpx exception so the caller can map it to a CAMARA error.
    """
    base = get_settings().positioning_engine_url
    last_exc: Exception | None = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            async with httpx.AsyncClient(base_url=base) as client:
                resp = await client.get(path, timeout=timeout)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            if 500 <= exc.response.status_code < 600 and attempt + 1 < _RETRY_ATTEMPTS:
                last_exc = exc
                log.info(
                    "engine %s -> %d, retrying once after %.2fs",
                    path, exc.response.status_code, _RETRY_BACKOFF_S,
                )
                await asyncio.sleep(_RETRY_BACKOFF_S)
                continue
            raise
        except httpx.HTTPError as exc:
            if attempt + 1 < _RETRY_ATTEMPTS:
                last_exc = exc
                log.info("engine %s network error %s, retrying once after %.2fs",
                         path, exc, _RETRY_BACKOFF_S)
                await asyncio.sleep(_RETRY_BACKOFF_S)
                continue
            raise
    # Unreachable in practice - the loop either returns or re-raises.
    assert last_exc is not None
    raise last_exc


def _position_path(device_id: str, source: str | None) -> str:
    # Pass the asset's source so the engine routes straight to that adapter
    # (capability routing) instead of fanning out to every adapter.
    return f"/position/{device_id}" + (f"?source={source}" if source else "")


def _age_s(pos: Position, now: datetime) -> float:
    t = pos.last_location_time
    # Engine timestamps are tz-aware; guard a naive one so subtracting it from
    # an aware `now` cannot raise.
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds()


async def _fetch_position(device_id: str, source: str | None, error_ns: str) -> Position:
    """Fetch one fix from the engine, or the dev mock when no engine is set.

    Maps engine outcomes to CAMARA errors: a 404 ("no measurements") becomes a
    422 {ns}.UNABLE_TO_LOCATE; a persistent 5xx becomes 502 BAD_GATEWAY; an
    unreachable engine becomes 503 UNAVAILABLE. Transient 5xx and network errors
    are retried once inside _engine_get before surfacing here.
    """
    url = get_settings().positioning_engine_url
    if not url:
        return _mock_position()
    try:
        d = await _engine_get(_position_path(device_id, source))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise CamaraError(
                422, f"{error_ns}.UNABLE_TO_LOCATE",
                "No location could be determined for this asset.",
            ) from exc
        log.warning("engine HTTP error %s for %s", exc.response.status_code, device_id)
        raise CamaraError(502, "BAD_GATEWAY", "Position source returned an error.") from exc
    except httpx.HTTPError as exc:
        log.warning("engine unreachable: %s", exc)
        raise CamaraError(503, "UNAVAILABLE", "Position source unreachable.") from exc
    return Position(
        latitude=d["latitude"],
        longitude=d["longitude"],
        radius_m=d.get("accuracy_m", _MOCK_RADIUS_M),
        last_location_time=datetime.fromisoformat(d["timestamp"]),
        altitude_m=d.get("altitude_m"),
        vertical_accuracy_m=d.get("vertical_accuracy_m"),
    )


async def get_position(
    device_id: str,
    source: str | None = None,
    max_age: int | None = None,
    error_ns: str = "LOCATION_RETRIEVAL",
) -> Position:
    """Single seam between the gateway and the position source, honouring the
    CAMARA maxAge freshness contract.

    maxAge semantics (spec): absent means "any age" is acceptable; 0 requests a
    fresh calculation, so the cache is bypassed; N accepts a fix no older than N
    seconds. A cached fix is reused only while it still satisfies that bound.
    When even a freshly fetched fix is older than maxAge, the request cannot be
    fulfilled -> 422 {ns}.UNABLE_TO_FULFILL_MAX_AGE. `error_ns` namespaces the
    API-specific codes (LOCATION_RETRIEVAL / LOCATION_VERIFICATION).
    """
    now = datetime.now(timezone.utc)
    key = (device_id, source)
    if max_age != 0:
        bound = max_age if max_age is not None else get_settings().location_cache_ttl_s
        cached = _cache.get(key)
        if cached is not None and _age_s(cached, now) <= bound:
            return cached
    pos = await _fetch_position(device_id, source, error_ns)
    _cache[key] = pos
    if max_age is not None and max_age > 0 and _age_s(pos, now) > max_age:
        raise CamaraError(
            422, f"{error_ns}.UNABLE_TO_FULFILL_MAX_AGE",
            "Unable to provide a location fresh enough for the requested maxAge.",
        )
    return pos


async def get_position_details(device_id: str, source: str | None = None) -> PositionDetails | None:
    """Vendor extension: full engine payload for the side-panel UI.

    Returns None when the engine has no fix (or is unreachable). The demo
    treats None as "no data yet" rather than an error.
    """
    url = get_settings().positioning_engine_url
    if not url:
        return None
    try:
        d = await _engine_get(_position_path(device_id, source))
    except Exception as exc:
        log.warning("engine details unreachable (%s)", exc)
        return None
    return PositionDetails(
        latitude=d["latitude"],
        longitude=d["longitude"],
        radius_m=d.get("accuracy_m", _MOCK_RADIUS_M),
        last_location_time=datetime.fromisoformat(d["timestamp"]),
        strategy=d.get("strategy", "weighted_avg"),
        sources=d.get("sources", []),
        altitude_m=d.get("altitude_m"),
    )


async def get_adapter_status() -> list[dict] | None:
    """Vendor extension: proxy the engine's GET /adapters health snapshot.

    Returns the list of adapters with cooldown state, or None when the engine
    is not configured or unreachable. The gateway intentionally swallows engine
    failures here - the demo treats None as "no diagnostics available" rather
    than an error.
    """
    url = get_settings().positioning_engine_url
    if not url:
        return None
    try:
        d = await _engine_get("/adapters", timeout=_ADAPTERS_REQUEST_TIMEOUT_S)
        return d.get("adapters", [])
    except Exception as exc:
        log.warning("engine /adapters unreachable (%s)", exc)
        return None


async def get_engine_devices() -> list[dict] | None:
    """Vendor extension: proxy the engine's GET /devices aggregate (discoverable
    devices across live sources) for the onboarding flow. Returns the list, or
    None when the engine is not configured / unreachable (caller degrades to an
    empty candidate set rather than erroring)."""
    url = get_settings().positioning_engine_url
    if not url:
        return None
    try:
        d = await _engine_get("/devices", timeout=_ADAPTERS_REQUEST_TIMEOUT_S)
        return d.get("devices", [])
    except Exception as exc:
        log.warning("engine /devices unreachable (%s)", exc)
        return None


async def get_blueprint() -> dict | None:
    """Vendor extension: proxy the engine's GET /blueprint so the demo (which
    talks only to the gateway, per the MEC constraint in AGENTS.md) can read
    the venue blueprint without reaching the engine directly.

    Returns the raw blueprint dict, or None when the engine is not configured,
    is unreachable, or has no blueprint authored yet (engine 404). The caller
    maps None to a 404 so the demo degrades gracefully.
    """
    url = get_settings().positioning_engine_url
    if not url:
        return None
    try:
        return await _engine_get("/blueprint", timeout=_ADAPTERS_REQUEST_TIMEOUT_S)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        log.warning("engine /blueprint -> %d", exc.response.status_code)
        return None
    except Exception as exc:
        log.warning("engine /blueprint unreachable (%s)", exc)
        return None


async def get_wifi_calibration() -> dict | None:
    """Vendor extension: proxy wifi-positioning's per-AP calibration params
    (real tx_power ref + path-loss n) so the demo's anchor panel shows measured
    RF instead of nominal placeholders. Returns the {id: {...}} map, or None
    when wifi-positioning is not configured / unreachable (demo degrades)."""
    url = get_settings().wifi_positioning_url.rstrip("/")
    if not url:
        return None
    try:
        async with httpx.AsyncClient(base_url=url) as client:
            resp = await client.get("/calibration/params", timeout=_ADAPTERS_REQUEST_TIMEOUT_S)
            resp.raise_for_status()
            return resp.json().get("params", {})
    except Exception as exc:
        log.warning("wifi calibration unreachable (%s)", exc)
        return None


def _mock_position() -> Position:
    # ~0.00005 deg ≈ 5 m, so a consumer converting back to a small indoor floor
    # plan keeps the device on the plan.
    lat = _MOCK_CENTER[0] + random.uniform(-0.00005, 0.00005)
    lon = _MOCK_CENTER[1] + random.uniform(-0.00005, 0.00005)
    return Position(lat, lon, _MOCK_RADIUS_M, datetime.now(timezone.utc))
