"""GET /devices - aggregate discoverable devices across live adapters.

Each adapter that advertises the `devices` capability exposes its own
GET /devices (observed ids for wifi, vendor inventory for the vendor-adapter).
The engine polls them, tags each device with its `source` (the adapter name
the position router routes on) and the adapter's `origin`, and returns one
flat list. The gateway then subtracts already-onboarded ids for KELT.

Best-effort: an adapter that is slow, unreachable, or lacks the endpoint is
skipped, not fatal - the aggregate returns whatever the reachable sources give.
"""

import asyncio
import logging

from fastapi import APIRouter, Request

log = logging.getLogger(__name__)
router = APIRouter(tags=["devices"])

_COPY_FIELDS = ("label", "last_seen", "position", "device_type", "role", "source_class")


@router.get("/devices")
async def devices(request: Request) -> dict:
    registry = request.app.state.registry
    pairs = registry.device_adapters()
    if not pairs:
        return {"devices": []}
    results = await asyncio.gather(
        *[adapter.get_devices() for _, adapter in pairs],
        return_exceptions=True,
    )
    out = []
    for (name, _), res in zip(pairs, results):
        if isinstance(res, Exception) or not isinstance(res, dict):
            continue
        origin = res.get("origin")
        for d in res.get("devices") or []:
            device_id = d.get("id")
            if not device_id:
                continue
            entry = {"id": device_id, "source": name}
            if origin:
                entry["origin"] = origin
            for k in _COPY_FIELDS:
                if d.get(k) is not None:
                    entry[k] = d[k]
            out.append(entry)
    return {"devices": out}
