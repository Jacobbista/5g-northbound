import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .config import get_settings
from .errors import CamaraError
from .models import Device

log = logging.getLogger(__name__)

# Fixed reference point for the mock; jittered per call so the demo shows motion.
_MOCK_CENTER = (45.064312, 7.659154)
_MOCK_RADIUS_M = 50.0


@dataclass
class Position:
    latitude: float
    longitude: float
    radius_m: float
    last_location_time: datetime


def resolve_device_id(device: Device) -> str:
    """Map a CAMARA device identifier to an internal device id.

    The mapping is config-driven (DEVICE_REGISTRY). For MVP an unmapped
    identifier falls back to its own value so the mock still returns a position.
    """
    registry = json.loads(get_settings().device_registry)
    candidates = [
        device.phoneNumber,
        device.networkAccessIdentifier,
        device.ipv4Address.publicAddress if device.ipv4Address else None,
        device.ipv6Address,
    ]
    for key in candidates:
        if key and key in registry:
            return registry[key]
    for key in candidates:
        if key:
            return key
    raise CamaraError(404, "IDENTIFIER_NOT_FOUND", "Device identifier not found.")


async def get_position(device_id: str) -> Position:
    """Single seam between the gateway and the position source.

    Swapping the mock for the live positioning engine is a one-line change:
    set POSITIONING_ENGINE_URL.
    """
    url = get_settings().positioning_engine_url
    if url:
        try:
            return await _from_engine(url, device_id)
        except Exception as exc:  # fall back to mock when engine is unset/unreachable
            log.warning("positioning engine unreachable (%s), using mock", exc)
    return _mock_position()


async def _from_engine(base_url: str, device_id: str) -> Position:
    async with httpx.AsyncClient(base_url=base_url) as client:
        resp = await client.get(f"/position/{device_id}", timeout=5.0)
        resp.raise_for_status()
        d = resp.json()
    return Position(
        latitude=d["latitude"],
        longitude=d["longitude"],
        radius_m=d.get("accuracy_m", _MOCK_RADIUS_M),
        last_location_time=datetime.fromisoformat(d["timestamp"]),
    )


def _mock_position() -> Position:
    # ~0.00005 deg ≈ 5 m, so a consumer converting back to a small indoor floor
    # plan keeps the device on the plan.
    lat = _MOCK_CENTER[0] + random.uniform(-0.00005, 0.00005)
    lon = _MOCK_CENTER[1] + random.uniform(-0.00005, 0.00005)
    return Position(lat, lon, _MOCK_RADIUS_M, datetime.now(timezone.utc))
