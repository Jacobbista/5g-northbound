from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/ingest", tags=["ingest"])


class WifiScanIngest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    device_id: str
    scan: dict[str, int]  # BSSID -> RSSI (dBm)
    timestamp: Optional[float] = None  # epoch seconds; preserves buffered/backfilled scans


@router.post("/wifi-scan")
async def ingest_wifi_scan(body: WifiScanIngest, request: Request):
    adapter = request.app.state.adapter
    if not adapter.ingest(body.device_id, body.scan, body.timestamp):
        raise HTTPException(422, detail="no known access points in scan")
    return {"ok": True}
