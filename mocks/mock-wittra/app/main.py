"""Toy Wittra cloud. Mimics enough of the real Wittra v4 REST shape so the
rest-adapter + placement editor's sync flow can be exercised on a fresh
clone without a Wittra account.

The shape is intentionally close to the real cloud:
  GET .../devices            -> raw array of device objects (NOT wrapped)
  GET .../devices/{id}/telemetry -> single object with `location.value.*`

Production deployments point the rest-adapter at the real Wittra API and
do not run this image.
"""

import base64
import os
import random
import time
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Header, HTTPException, Query

ORG_ID = os.environ.get("MOCK_WITTRA_ORG_ID", "demo-org")
API_KEY = os.environ.get("MOCK_WITTRA_API_KEY", "demo-key")
PROJECT_ID = os.environ.get("MOCK_WITTRA_PROJECT_ID", "demo-prj")
KNOWN_DEVICES = {
    "wittra-tag-01": {"label": "Tag 01", "height_m": 1.2},
    "wittra-tag-02": {"label": "Tag 02", "height_m": 2.7},
}

# Reference point near the lab + a per-device random-walk state.
_CENTER = (45.064312, 7.659154)
_state: dict[str, dict] = {}

app = FastAPI(
    title="mock-wittra",
    description="Demo only fake of the Wittra v4 REST API.",
    version="0.2.0",
)


@app.get("/health")
async def health():
    return {"status": "ok"}


def _check_basic_auth(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Basic "):
        raise HTTPException(401, detail="Missing Basic auth")
    raw = base64.b64decode(authorization[6:]).decode("utf-8", errors="replace")
    try:
        user, pwd = raw.split(":", 1)
    except ValueError:
        raise HTTPException(401, detail="Malformed Basic auth")
    if user != ORG_ID or pwd != API_KEY:
        raise HTTPException(401, detail="Invalid credentials")


def _step(device_id: str) -> tuple[float, float]:
    s = _state.get(device_id)
    if s is None:
        s = {"lat": _CENTER[0], "lon": _CENTER[1]}
        _state[device_id] = s
    s["lat"] += random.uniform(-0.000005, 0.000005)
    s["lon"] += random.uniform(-0.000005, 0.000005)
    return s["lat"], s["lon"]


def _telemetry_object(device_id: str) -> dict:
    """Build one v4-shaped telemetry record for the given device. The
    location block uses the {telemetryId, value, timestamp} envelope the
    real Wittra v4 telemetry endpoint exposes, so the rest-adapter's
    mapping (`location.value.latitude` etc.) works against both."""
    lat, lon = _step(device_id)
    meta = KNOWN_DEVICES[device_id]
    return {
        "deviceId": device_id,
        "dataType": "telemetry",
        "telemetryId": f"t-{int(time.time() * 1000)}",
        "source": "p",
        "location": {
            "telemetryId": f"loc-{int(time.time() * 1000)}",
            "value": {
                "latitude": lat,
                "longitude": lon,
                "height": meta["height_m"],
                "level": 0,
                "accuracy": round(0.6 + random.random() * 0.35, 2),
                "label": "Mock Lab",
                "motion": "stationary",
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


def _location_point(device_id: str, ts) -> dict:
    """One v4 `location` DeviceDataPoint, matching the real get-data shape:
    {dataType, deviceId, location: {timestamp, value: {latitude, ...}}}."""
    obj = _telemetry_object(device_id)
    return {
        "dataType": "location",
        "deviceId": device_id,
        "location": {
            "timestamp": ts.isoformat(sep=" "),
            "value": obj["location"]["value"],
        },
    }


@app.get("/v4/organizations/{org_id}/projects/{project_id}/data")
async def get_data(
    org_id: str,
    project_id: str,
    deviceId: str = Query(...),
    dataType: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    """Real Wittra v4 get-data endpoint: returns an array of DeviceDataPoint
    for one device, ascending by time (latest last). `?dataType=location`
    filters server-side, as the real cloud does."""
    _check_basic_auth(authorization)
    if org_id != ORG_ID or project_id != PROJECT_ID:
        raise HTTPException(404, detail="Unknown org/project")
    if deviceId not in KNOWN_DEVICES:
        raise HTTPException(404, detail="Unknown device")
    now = datetime.now(timezone.utc)
    # Three points, oldest first; the consumer takes the last (most recent).
    points = [
        _location_point(deviceId, now - timedelta(seconds=offset))
        for offset in (2, 1, 0)
    ]
    if dataType:
        points = [p for p in points if p["dataType"] == dataType]
    return points


@app.get("/v4/organizations/{org_id}/projects/{project_id}/devices/{device_id}/telemetry")
async def get_device_telemetry(
    org_id: str,
    project_id: str,
    device_id: str,
    authorization: str | None = Header(default=None),
):
    # Legacy single-object endpoint, kept for back-compat with older schemas.
    _check_basic_auth(authorization)
    if org_id != ORG_ID or project_id != PROJECT_ID:
        raise HTTPException(404, detail="Unknown org/project")
    if device_id not in KNOWN_DEVICES:
        raise HTTPException(404, detail="Unknown device")
    return _telemetry_object(device_id)


@app.get("/v4/organizations/{org_id}/projects/{project_id}/devices")
async def list_devices(
    org_id: str,
    project_id: str,
    authorization: str | None = Header(default=None),
):
    """v4 device list. Returns a raw JSON array (no envelope), one entry
    per registered device. Mirrors the real Wittra v4 shape: `deviceId`
    is the join key, `fixedLocation` is the operator-configured anchor
    position. `latest.data.location` would carry the live position if
    the device is moving, but for beacons the `fixedLocation` is what
    the editor's sync flow wants.
    """
    _check_basic_auth(authorization)
    if org_id != ORG_ID or project_id != PROJECT_ID:
        raise HTTPException(404, detail="Unknown org/project")
    out = []
    for device_id, meta in KNOWN_DEVICES.items():
        lat, lon = _step(device_id)
        out.append({
            "deviceId": device_id,
            "deviceType": "beacon",
            "name": f"{meta['label']} (Position Beacon)",
            "isPositioningActive": True,
            "fixedLocation": {
                "latitude": lat,
                "longitude": lon,
                "height": meta["height_m"],
                "level": 0,
            },
            "color": "#ff9800",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "lastSeen": None,
            "group": None,
        })
    # A meshrouter: fixed UWB relay infrastructure that carries NO fixedLocation,
    # so classification must key off deviceType (not "has a position") to label
    # it infrastructure rather than an onboardable asset.
    out.append({
        "deviceId": "D00124B00249MR01",
        "deviceType": "meshrouter",
        "name": "Mesh Router 01",
        "isPositioningActive": True,
        "fixedLocation": None,
        "color": "#ff9800",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "lastSeen": None,
        "group": None,
    })
    # One mobile tag (no fixedLocation) - the only onboardable asset. The editor
    # keeps anchors (fixedLocation), asset onboarding keeps tags.
    out.append({
        "deviceId": "D00124B00249TAG01",
        "deviceType": "tag",
        "name": "Asset Tag 01",
        "isPositioningActive": True,
        "fixedLocation": None,
        "color": "#5dffb0",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "lastSeen": None,
        "group": None,
    })
    return out
