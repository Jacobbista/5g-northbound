# Writing a Positioning Adapter

A *positioning adapter* is any service that produces a position estimate for a device and exposes it over a small HTTP contract. The positioning engine fuses one or more adapters listed in `ADAPTER_URLS` (comma-separated, evaluated at startup); it never assumes anything else about a source. To add a new technology — UWB anchors, BLE beacons, a vendor RTLS, a GPS receiver — you implement this contract in a separate service and add its URL to the engine's configuration. No engine, gateway, or demo code changes.

The [`wifi-positioning/`](../wifi-positioning/) service in this repository is the reference implementation. It uses WiFi RSSI from a fleet of access points; the same shape works for any other source.

## HTTP contract

The adapter MUST expose two endpoints:

```
GET  /measurement/{device_id}
GET  /health
```

Optionally it MAY expose `POST /ingest/...` (or any other transport) for sources that push data into the adapter; the engine never calls them.

### `GET /measurement/{device_id}`

Returns the latest position estimate for the device, in the adapter's chosen local coordinate frame (metres).

**Response — 200 OK:**

```json
{
  "source":      "wifi",
  "x":           11.5,
  "y":           0.0,
  "z":           10.3,
  "accuracy_m":  6.6,
  "confidence":  0.85,
  "timestamp":   1700000000.0
}
```

| Field        | Type             | Notes |
|--------------|------------------|-------|
| `source`     | string           | Short tag identifying the technology (`wifi`, `uwb`, `fiveg`, …). Surfaces in the engine response under `sources[]` |
| `x`, `y`, `z`| float, metres    | Right-handed local frame: `x` = east, `y` = vertical (height), `z` = north. Origin is the floor-plan lower-left corner |
| `accuracy_m` | float, metres    | One-sigma error radius. Used as `1 / variance` weight in fusion (smaller is better) |
| `confidence` | float, 0.0–1.0   | Adapter's self-reported reliability. Used as a multiplicative weight in fusion |
| `timestamp`  | float, optional  | Unix epoch seconds when the underlying measurement was taken. Omit for "now". The engine uses this to decide staleness |

**Response — 404 Not Found:**

The adapter has no measurement for this device (yet, or any more). The engine silently ignores this source for this device on this fusion cycle; no retry, no error propagation.

**Response — anything else:**

Treated as a transient adapter failure. The engine logs it and ignores this source for this cycle. The adapter should not raise 5xx unless something is actually broken.

### `GET /health`

Returns `200 {"status": "ok"}` when the adapter is ready to serve measurements. Used as Kubernetes `readinessProbe` and `livenessProbe`. No authentication.

## Lifecycle

1. **Startup.** Adapter loads its configuration (AP map, anchor positions, vendor credentials, …) from environment variables and/or mounted files. It does *not* register with the engine — the engine pulls from a static URL list.
2. **Data ingestion.** Adapter receives raw observations through whatever mechanism is appropriate for the technology: HTTP push from edge devices, MQTT subscription, vendor SDK, polling. This is entirely the adapter's concern; the engine never sees raw observations.
3. **Position computation.** Adapter converts raw observations into a position estimate in its local frame. It may smooth, fuse multiple antennas, drop outliers — all internal.
4. **Caching.** Adapter keeps the latest position per device. `GET /measurement/{id}` is a cache lookup. The engine polls at its own cadence (default ~1 Hz); the adapter does not push.
5. **Staleness.** Adapter SHOULD return the last known position with its real `timestamp` regardless of age, and let the consumer decide what is too old. Returning 404 on a stale entry forces the engine to drop the source from fusion; usually the better behaviour is to return the old fix with its old timestamp so the engine can grey it out gradually.

## Engine wiring

The engine reads `ADAPTER_URLS` at startup:

```yaml
env:
  - name: ADAPTER_URLS
    value: "http://wifi-positioning:8080,http://uwb-adapter:8080"
```

Each URL becomes one [`HttpAdapter`](../positioning-engine/app/adapters/http.py) instance. On every position request the engine concurrently calls `GET /measurement/{device_id}` on each, fuses the responses with `weight = confidence / accuracy_m`, converts the local x/z to WGS84 using the floor-plan `gps_origin`, and returns the result on the northbound contract.

To add an adapter to a running cluster: deploy the new Service, append its URL to `ADAPTER_URLS`, restart the engine. An empty `ADAPTER_URLS` makes the engine fall back to in-process random-walk adapters (development convenience only — do not use in production).

## Coordinate frame

All adapters report positions in the same room-local frame as the floor plan:

- **Origin:** lower-left corner of the room, as defined in `dev/floor-plan.json` (or the production ConfigMap).
- **x:** east, metres (along `width_m`).
- **z:** north, metres (along `depth_m`).
- **y:** vertical, metres (height). Adapters that cannot estimate height SHOULD return `y = 0.0`.

The engine converts `(x, z)` to WGS84 latitude/longitude using the floor plan's `gps_origin` before exposing the position northbound. Adapters do not need GPS knowledge.

## Authentication

The engine talks to adapters over the internal Kubernetes ClusterIP network; adapters are not exposed externally and do not need to authenticate engine calls. If your deployment routes adapter traffic over an untrusted network, terminate TLS at an ingress and authenticate engine→adapter calls there; the contract itself is HTTP-only.

If an adapter accepts data pushes from devices on the public 5G data network (the wifi-positioning ingest path is one example), it MUST authenticate or rate-limit those calls itself — the engine cannot help.

## Packaging

| | |
|---|---|
| **Runtime** | any language or framework; the contract is HTTP+JSON |
| **Image** | published to a container registry the cluster can pull from (private registries need an `imagePullSecret`) |
| **Health** | `GET /health` returning `200 {"status": "ok"}` |
| **Port** | conventionally `8080` inside the container; the Service publishes whichever ClusterIP port the engine URL references |
| **Configuration** | environment variables and/or files mounted from a `ConfigMap` (raw data) plus a `Secret` (credentials) |
| **State** | per-device in-memory cache is fine; the engine tolerates restarts (a missing measurement is just a 404 for one cycle) |

## Reference implementation walk-through

[`wifi-positioning/`](../wifi-positioning/) is roughly 250 lines of Python + FastAPI:

- [`app/main.py`](../wifi-positioning/app/main.py) — loads `wifi-config.json` (AP map, room dimensions, RSSI calibration) into application state, mounts the routers.
- [`app/wifi.py`](../wifi-positioning/app/wifi.py) — `compute_position(scan, cfg)`: RSSI → distance via log-distance path loss, least-squares multilateration with weighted-centroid fallback. `WifiAdapter.ingest(...)` smooths through a per-device Kalman tracker and caches a `Measurement`.
- [`app/routers/ingest.py`](../wifi-positioning/app/routers/ingest.py) — `POST /ingest/wifi-scan` receives `{device_id, scan: {bssid: rssi_dbm}, timestamp?}` from edge clients (e.g. the Raspberry Pi in [`wifi-positioning/edge/scanner/`](../wifi-positioning/edge/scanner/)) over the 5G data network. Adapter-specific endpoint, not part of the engine contract.
- [`app/routers/measurement.py`](../wifi-positioning/app/routers/measurement.py) — implements `GET /measurement/{device_id}` against the cache.

Reading it end-to-end is the fastest way to understand the shape; replicate the structure in your own technology stack.

## Minimal Python skeleton

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

class Measurement(BaseModel):
    source: str = "my-source"
    x: float; y: float = 0.0; z: float
    accuracy_m: float
    confidence: float
    timestamp: Optional[float] = None

app = FastAPI()
_cache: dict[str, Measurement] = {}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/measurement/{device_id}", response_model=Measurement)
async def get_measurement(device_id: str):
    m = _cache.get(device_id)
    if m is None:
        raise HTTPException(404)
    return m

# … your own ingestion / polling logic populates `_cache`.
```

Ship it as a container, deploy a `Deployment` + `ClusterIP Service`, append the Service URL to the engine's `ADAPTER_URLS`, restart the engine. The new source is now part of every fused position.

## Configuration provisioning

Adapter configuration (AP maps, anchor positions, RSSI calibration, `gps_origin`) is per-deployment data: it differs between dev, CI, and each physical site, and the real values are often venue-sensitive (BSSIDs identify the actual access points). The committed reference adapter ships a placeholder; real values are kept out of the repository and provided at runtime.

| Environment           | Source of `wifi-config.json`                                                      | Where the values live                                       |
|-----------------------|-----------------------------------------------------------------------------------|-------------------------------------------------------------|
| Local docker compose  | [`dev/wifi-config.json`](../dev/wifi-config.json) (placeholder, committed)        | Override with `dev/wifi-config.local.json` (gitignored). Mount swap: `export WIFI_CONFIG=./dev/wifi-config.local.json && docker compose up` |
| CI / unit tests       | Inline fixtures in the test files; no JSON loaded                                 | n/a                                                          |
| Cluster runtime       | Kubernetes ConfigMap `wifi-positioning-config`, mounted at `WIFI_CONFIG_PATH`     | Created out-of-band by the operator (or by the testbed dashboard, when available). Not in any Git repository. |

The cluster ConfigMap is intentionally not produced by the testbed's Ansible phases — phase 11 ships only the engine backbone with `ADAPTER_URLS=""`. Adapters and their ConfigMaps are runtime artefacts, installed when an operator (or the dashboard catalog, planned) provisions a positioning source.

Manual ConfigMap creation, until the dashboard lands:

```bash
kubectl -n positioning create configmap wifi-positioning-config \
  --from-file=wifi-config.json=/path/to/your/real-wifi-config.json
```

The same pattern applies to any other adapter: ship a placeholder in the repository so the stack runs from a fresh clone; keep the real configuration on the operator's machine and inject it into the cluster as a ConfigMap (or Secret, if it contains credentials) at provisioning time.

## Vendor adapters and private images

Adapters that wrap a proprietary RTLS or contain vendor SDKs / NDA material belong in **separate, private repositories** and ship as private container images. They implement the same contract; deployment differs only in needing an `imagePullSecret`. The public engine and the public gateway never see vendor code or vendor secrets — the boundary is the HTTP contract documented above.
