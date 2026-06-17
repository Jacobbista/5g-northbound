"""Vendor extension: real per-anchor calibration for the demo's AP panel.

The blueprint carries nominal/placeholder RF on WiFi anchors (band/channel/
nominal tx power). The MEASURED RF model lives in the wifi-positioning
bindings (tx_power reference + path-loss n, fitted by the calibration DERIVE).
The demo talks only to the gateway, so the gateway proxies wifi-positioning's
`GET /calibration/params` here. Read-only; BSSIDs are never exposed.
"""

from typing import Any

from fastapi import APIRouter, Depends

from ..auth import require_location_role
from ..position import get_wifi_calibration

router = APIRouter(prefix="/anchors", tags=["Anchors (vendor extension)"])


@router.get("/calibration")
async def anchors_calibration(_claims: dict = Depends(require_location_role)) -> dict[str, Any]:
    """Per-anchor measured RF params, keyed by anchor id. Empty when
    wifi-positioning is not wired or has no calibration yet."""
    return {"params": await get_wifi_calibration() or {}}
