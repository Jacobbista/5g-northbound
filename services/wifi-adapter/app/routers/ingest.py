"""Scan intake from edge devices.

The client is the scanner running on edge hardware, outside the images this
repository builds, so it does not move within a deploy window. The body accepts
the current field name and the one it replaced, and an ingest that uses the old
one is told so in the response and in the log, once per device.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, model_validator

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])

_SUPERSEDED = "device_id"
_DEPRECATION = (
    "the field is now `positioningId`; `device_id` still works and will be "
    "removed in a later release"
)


class WifiScanIngest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    positioningId: Optional[str] = None
    # Superseded by `positioningId`. Kept so a scanner deployed before the
    # rename keeps reporting while its operator updates it.
    device_id: Optional[str] = None
    scan: dict[str, int]  # BSSID -> RSSI (dBm)
    timestamp: Optional[float] = None  # epoch seconds; preserves buffered scans

    @model_validator(mode="after")
    def _one_identifier(self):
        if not self.positioningId and not self.device_id:
            raise ValueError("give positioningId (or the superseded device_id)")
        return self

    @property
    def identifier(self) -> str:
        return self.positioningId or self.device_id  # type: ignore[return-value]

    @property
    def used_superseded_name(self) -> bool:
        return not self.positioningId and bool(self.device_id)


@router.post("/wifi-scan")
async def ingest_wifi_scan(body: WifiScanIngest, request: Request):
    """Take a scan. A scan that hears no bound access point is a valid report
    the site cannot place, not a malformed request: it is accepted with
    `located: false`, and the device is listed on /devices without a position,
    so an operator sees the scanner and the bindings it lacks."""
    adapter = getattr(request.app.state, "adapter", None)
    if adapter is None:
        # Degraded boot: the blueprint is still loading, so no anchor has a
        # position yet. The scan is not taken; the scanner buffers and resends.
        raise HTTPException(503, detail="the blueprint is not loaded yet")
    device = body.identifier
    located = adapter.ingest(device, body.scan, body.timestamp)

    response: dict = {"ok": True, "located": located}
    if body.used_superseded_name:
        response["warning"] = _DEPRECATION
        # The adapter carries the fact per device, so GET /devices reports which
        # scanners still have to move. One log line per device, not per scan.
        if adapter.note_superseded_ingest(device, _SUPERSEDED):
            log.warning("ingest from %s uses the superseded `%s`: %s", device, _SUPERSEDED, _DEPRECATION)
    return response
