# Data Contracts

This document is the source of truth for the data contracts between the components in this repository and any external consumer.

- [CAMARA Device Location API](#camara-device-location-api): northbound, consumed by browsers and any third-party CAMARA client.
- [Vendor extensions on the gateway](#vendor-extensions-on-the-gateway): non-CAMARA endpoints used by the demo UI (`/devices`, `/devices/{phoneNumber}/details`, `/adapters`, `/positions/stream` WebSocket).
- [Engine northbound contract](#engine-northbound-contract): internal, between `camara-gateway` and `positioning-engine`.
- [Adapter contract](#adapter-contract): internal, between `positioning-engine` and adapter pods (see [`adapters.md`](adapters.md) for the full implementer's guide).
- [Device registry file](#device-registry-file): registered devices consumed by the gateway.
- [Floor plan](#floor-plan): loaded by the engine at startup.
- [Placement-editor API](#placement-editor-api): operator-facing service that owns the floor-plan / AP layout JSON.
- [SMF session info](#smf-session-info): consumed by the gateway for cross-technology identity resolution.

A compact endpoint-by-endpoint reference (one row per route) is available in [`api-reference.md`](api-reference.md). This document explains the *contracts*; the reference is the *index*.

## CAMARA Device Location API

The gateway implements two distinct CAMARA APIs, pinned to meta-release **r3.2** (commit `bc17ceeb4ee34929d5f65b8851d99d4dda4c5af1`). The pinned OpenAPI documents in [`camara-gateway/spec/`](../services/camara-gateway/spec/) are the source of truth, the examples below are illustrative.

### Device identifier

All requests carry a `device` object following the CAMARA Commonalities schema. At least one identifier MUST be present:

```json
{
  "phoneNumber":              "+390111234567",
  "networkAccessIdentifier":  "user@example.com",
  "ipv4Address": {
    "publicAddress": "203.0.113.1",
    "privateAddress": "10.0.0.1",
    "publicPort": 443
  },
  "ipv6Address":              "2001:db8::1"
}
```

The gateway maps the CAMARA identifier to an internal device id via the `DEVICE_REGISTRY` configuration (a JSON object). There is no `deviceId` field and no `extensions` block in the contract.

Errors use the CAMARA envelope `{status, code, message}`. Standard codes:

| HTTP | `code`                  | When                                              |
|------|-------------------------|---------------------------------------------------|
| 400  | `INVALID_ARGUMENT`      | Malformed identifier (e.g, phone fails E.164 regex) |
| 401  | `UNAUTHENTICATED`       | Missing or invalid JWT                            |
| 403  | `PERMISSION_DENIED`     | JWT lacks the `camara-location-read` realm role   |
| 404  | `IDENTIFIER_NOT_FOUND`  | Identifier not in the device registry             |
| 404  | `NOT_FOUND`             | Identifier exists but the engine has no fix       |
| 422  | `MISSING_IDENTIFIER`    | `device` body is absent                           |
| 502  | `BAD_GATEWAY`           | Engine reachable but returned 5xx                 |
| 503  | `SERVICE_UNAVAILABLE`   | Engine unreachable (network / DNS / timeout)      |

### Location Retrieval v0.5

`POST /location-retrieval/v0.5/retrieve`

Request:

```json
{ "device": { "phoneNumber": "+390111234567" }, "maxAge": 120 }
```

Response (`Location`):

```json
{
  "lastLocationTime": "2024-01-01T12:00:00Z",
  "area": {
    "areaType": "CIRCLE",
    "center":   { "latitude": 45.064312, "longitude": 7.659154 },
    "radius":   50.0
  }
}
```

`area` is either a `CIRCLE` (centre + radius ≥ 1 m) or, per spec, a `POLYGON`. `radius` is in metres. `device` is mandatory; absence yields `422 MISSING_IDENTIFIER`.

### Location Verification v3

`POST /location-verification/v3/verify`

Request:

```json
{
  "device": { "phoneNumber": "+390111234567" },
  "area":   { "areaType": "CIRCLE", "center": { "latitude": 45.064312, "longitude": 7.659154 }, "radius": 5000 },
  "maxAge": 120
}
```

Response (`VerifyLocationResponse`):

```json
{ "verificationResult": "TRUE", "lastLocationTime": "2024-01-01T12:00:00Z" }
```

`verificationResult` is `"TRUE"`, `"FALSE"`, or `"PARTIAL"` (not a boolean; no `UNKNOWN`). `matchRate` (1–99) is present only when the result is `PARTIAL`. The current single-point implementation returns only `TRUE` and `FALSE`.

### Authentication

The gateway validates `Authorization: Bearer <jwt>` against the JWKS at:

```
{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs
```

`KEYCLOAK_URL` is taken verbatim and already contains any path prefix (such as `/auth`). The token must carry the `camara-location-read` realm role in `realm_access.roles`. `GET /health` is exempt from authentication.

## Vendor extensions on the gateway

These endpoints live on the same gateway service but are **not part of CAMARA Device Location**. They exist to support the demo UI (and any other consumer that needs to enumerate or inspect devices). They share the same authentication: `Authorization: Bearer <jwt>` with the `camara-location-read` realm role. `GET /health` is exempt; everything else requires a valid token.

### Device discovery

`GET /devices` → list every registered device.

```json
{
  "devices": [
    { "phoneNumber": "+390111234567", "deviceId": "wifi-asset-01", "label": "WiFi asset 01", "simulated": false },
    { "phoneNumber": "+390117654321", "deviceId": "mock-demo-01",  "label": "Mock demo 01",  "simulated": true  }
  ]
}
```

The list is read from the [device registry file](#device-registry-file). Order matches the file. Empty list (`{"devices": []}`) is returned when the registry is empty, not a 404.

`simulated` is `true` when the device is wired to a synthetic data source (`mock-positioning`, `mock-wittra`, or any future demo fixture). The UI renders a `MOCK` badge so operators can tell at a glance which devices come from a fake. Real deployments simply omit the field (it defaults to `false`).

### Device details

`GET /devices/{phoneNumber}/details` → registry entry + engine telemetry.

```json
{
  "phoneNumber": "+390117654321",
  "deviceId":    "mock-demo-01",
  "label":       "Mock demo 01",
  "telemetry": {
    "latitude":         45.064547,
    "longitude":        7.659272,
    "accuracy_m":       1.5,
    "lastLocationTime": "2026-06-03T14:36:17Z",
    "strategy":         "weighted_avg",
    "sources":          ["mock"]
  }
}
```

- `phoneNumber` is URL-encoded (`%2B` for the leading `+`).
- `telemetry` is `null` when the engine has no fix for the device, the device is **registered but offline**, not an error.
- `phoneNumber` not in the registry → `404 IDENTIFIER_NOT_FOUND`.
- Surfaces engine fields (`strategy`, `sources`) intentionally hidden by the CAMARA `Location` response. Schema and field names match the engine's `EnginePosition` to make the boundary obvious.

### Adapter health

`GET /adapters` → operator diagnostic, proxied from the engine's [`/adapters`](#engine-adapter-status) snapshot. Lets the demo show "wittra: degraded" without bypassing the gateway (the demo is not allowed to talk to the engine directly).

```json
{
  "adapters": [
    {
      "name": "wifi",
      "base_url": "http://wifi-positioning:8080",
      "fail_count": 0,
      "in_cooldown": false,
      "cooldown_seconds_remaining": 0.0
    },
    {
      "name": "wittra",
      "base_url": "https://api.wittra.example.com",
      "fail_count": 5,
      "in_cooldown": true,
      "cooldown_seconds_remaining": 23.5
    }
  ]
}
```

- `fail_count` resets to 0 on the next successful adapter response.
- `in_cooldown=true` means the engine is **not** issuing HTTP requests to that adapter right now; `cooldown_seconds_remaining` is how long the cooldown still has to run. See [`adapters.md`](adapters.md#http-contract) for the cooldown policy.
- Empty list (`{"adapters": []}`) when the engine is unreachable or has no adapters configured, not a 502/503.

### Live positions WebSocket

`WS /positions/stream?token=<jwt>` streams the engine's broadcast to authenticated browser clients without bypassing the gateway. The browser opens:

```
ws://<gateway>/positions/stream?token=<jwt>
```

Token is supplied as a query parameter because browsers cannot set `Authorization` headers on a WebSocket handshake. The gateway validates the token against the same Keycloak realm and `camara-location-read` role as the REST endpoints, opens a single upstream connection to the engine's `/ws/positions`, and forwards every payload. Each payload is a JSON array, one object per device with at least a fix:

```json
[
  {
    "device_id":       "mock-demo-01",
    "latitude":        45.064547,
    "longitude":       7.659272,
    "accuracy_m":      1.5,
    "timestamp":       "2026-06-10T07:36:01Z",
    "sources":         ["mock"],
    "strategy":        "weighted_avg"
  }
]
```

Close codes:

| Code | Meaning                                                                 |
|------|-------------------------------------------------------------------------|
| 4401 | Authentication failed (missing or invalid token, missing required role) |
| 1011 | Upstream engine unavailable                                             |
| 1000 | Clean shutdown                                                          |

The cadence is set by the engine's `WEBSOCKET_INTERVAL_MS` (default 500 ms). The browser demo's `usePositionsStream` hook reconnects automatically with exponential backoff capped at 8 s.

## Engine northbound contract

The boundary between `camara-gateway` and any positioning engine is this REST contract. Any engine that honours it is a drop-in replacement; the gateway stays geometry-agnostic.

`GET /position/{device_id}` → `EnginePosition`:

```json
{
  "device_id":  "wifi-asset-01",
  "latitude":   45.064581,
  "longitude":  7.659408,
  "accuracy_m": 0.3,
  "timestamp":  "2024-01-01T12:00:00Z",
  "sources":    ["uwb", "wifi"],
  "strategy":   "weighted_avg",
  "fusions":    null
}
```

The engine owns its native coordinate frame and normalises to WGS84 at this boundary. The gateway passes `latitude`/`longitude` straight into the CAMARA `area.center`, with `radius = max(accuracy_m, 1)`.

Status codes the engine returns:

| HTTP | When                                                                                              |
|------|---------------------------------------------------------------------------------------------------|
| 200  | At least one adapter returned a measurement and fusion succeeded                                  |
| 404  | No adapter has a fix for this device (legitimate "offline", not an error)                         |
| 500  | Fusion or projection raised an unexpected exception                                               |

The gateway propagates these:

| Engine response          | Gateway response                                  |
|--------------------------|---------------------------------------------------|
| 200                      | 200 with CAMARA `Location`                         |
| 404                      | 404 `NOT_FOUND` (CAMARA envelope)                  |
| 5xx                      | 502 `BAD_GATEWAY` (after one short retry)          |
| network error / timeout  | 503 `SERVICE_UNAVAILABLE` (after one short retry)  |

Transient engine failures (`5xx`, connect errors, read timeouts) are retried once after a 200 ms backoff before the gateway gives up, most pod restarts and brief blips clear within that window. `404` is **not** retried (it's a legitimate "no fix", not a failure to reach the engine).

When `POSITIONING_ENGINE_URL` is **unset** the gateway falls back to a built-in mock position so the system degrades gracefully in dev. As soon as the env var points at a real engine, the engine is the only source of truth, no silent mock fallback.

#### Engine adapter status

`GET /adapters` on the engine returns the same shape proxied by the gateway above, the engine is the source of truth, the gateway forwards it as a vendor extension. Useful when debugging the engine directly:

```bash
curl http://localhost:8081/adapters
```

`strategy` names the primary fusion algorithm that produced the result; see [`fusion-strategies.md`](fusion-strategies.md). `fusions` is `null` unless the engine is configured with `FUSION_COMPARE`, in which case it maps each comparison strategy name to its own `{latitude, longitude, accuracy_m, sources}`: used by the demo to render multiple tracks side by side, ignored by the CAMARA gateway.

## Adapter contract

Adapter pods expose the following endpoint, consumed by the engine via [`HttpAdapter`](../services/positioning-engine/app/adapters/http.py):

```
GET /measurement/{device_id}  → 200 OK
{
  "source":     "wifi",
  "frame":      "local",
  "x":          11.5,
  "y":          0.0,
  "z":          10.3,
  "accuracy_m": 6.6,
  "confidence": 0.85,
  "timestamp":  1700000000.0
}
```

`404 Not Found` indicates no measurement for the device. `timestamp` is Unix epoch seconds; omit for "now". `frame` declares the coordinate system of the reply. `"local"` (default) means x/y/z are metres in the room-local frame defined by the floor plan (origin = lower-left corner, x = east, z = north, y = vertical), `"wgs84"` means the reply carries `latitude` and `longitude` instead and the engine projects them into the local frame using `gps_origin` before fusion. See [`adapters.md`](adapters.md) for the full specification and implementer's guide.

## Device registry file

Loaded by the gateway at startup from the path in `DEVICE_REGISTRY_FILE` (default unset; in compose `/app/config/devices.json` is mounted from [`dev/devices.json`](../dev/devices.json)). Edit + restart the gateway to register new devices.

```json
{
  "devices": [
    { "phoneNumber": "+390111234567", "deviceId": "wifi-asset-01", "label": "WiFi asset 01" },
    { "phoneNumber": "+390117654321", "deviceId": "mock-demo-01",  "label": "Mock demo 01", "simulated": true }
  ]
}
```

- `phoneNumber`: the CAMARA identifier consumers send in `device.phoneNumber`. Must be E.164-shaped (`+` followed by 8–15 digits).
- `deviceId`: the internal id the engine fuses on; matches the keys used by the engine's `DEVICE_MAP`.
- `label`: human-readable name surfaced by the demo's discovery endpoint. Optional; defaults to `deviceId`.
- `simulated`: optional boolean (default `false`). Set to `true` for devices wired to a fixture (`mock-positioning`, `mock-wittra`, …) so the UI can render a `MOCK` badge and a global "demo build" indicator. Real deployments leave it off.

When `DEVICE_REGISTRY_FILE` is unset (or unreadable), the gateway falls back to the legacy `DEVICE_REGISTRY` env (`{"+390...":"deviceId"}` flat JSON map), kept for back-compat with the original v0 layout. New deployments should use the file form so labels propagate through `/devices`.

## Blueprint vs bindings

Venue config splits into two files, geometry (portable, no secrets) and
per-venue bindings (BSSIDs / MACs / vendor IDs, never committed). The
wifi-positioning service joins them on anchor `id` at startup. The full
rationale, layout, and deployment flow live in
[`blueprint-vs-bindings.md`](./blueprint-vs-bindings.md); read that once,
then the rest of this document makes sense.

## Floor plan

Loaded at engine startup from `/app/config/floor-plan.json` (mounted in production from the `positioning-floor-plan` Kubernetes ConfigMap).

```json
{
  "version": 1,
  "gps_origin": {
    "latitude":    45.064312,
    "longitude":   7.659154,
    "azimuth_deg": 0.0,
    "altitude_m":  240.0
  },
  "floors": [
    {
      "id": 0,
      "label": "Ground Floor",
      "width_m": 20.0,
      "depth_m": 30.0,
      "height_m": 3.0,
      "walls":        [{ "x": 0, "z": 0, "w": 20.0, "d": 0.2, "h": 3.0 }],
      "uwb_anchors":  [{ "id": "anchor-00", "x": 0.5, "y": 2.4, "z": 0.5 }]
    }
  ]
}
```

`gps_origin` is the **single georeference** that links the local floor-plan frame (metres, lower-left origin, +x east-ish / +z north-ish) to WGS84. Survey it once for a venue; every anchor and device position is then carried in local metres and projected to lat/lon at the engine boundary. This bounds positioning error by *one* calibration instead of letting it accumulate per AP.

| Field         | Required | Notes                                                                       |
|---------------|----------|-----------------------------------------------------------------------------|
| `latitude`    | yes      | Latitude of the floor-plan origin (lower-left corner of the room)          |
| `longitude`   | yes      | Longitude of the floor-plan origin                                          |
| `azimuth_deg` | no (0)   | Bearing of the local +z axis (the SVG "up") clockwise from true north. 0 means the room is north-aligned; 30 means the room is rotated 30° east of north |
| `altitude_m`  | no       | Altitude of the origin above sea level. Carried for completeness, not used in the 2D projection |

`gps_origin` itself is optional. When absent, the engine returns `latitude: 0, longitude: 0` and logs a warning. The development fixture [`dev/floor-plan.json`](../dev/floor-plan.json) carries a placeholder origin so the local demo works; the production ConfigMap omits it until a real lab GPS reference is available.

## Placement-editor API

Standalone operator-facing service that owns the floor-plan / AP layout JSON. Lives in [`services/placement-editor/`](../services/placement-editor/) and ships as its own image. The demo and the engine both consume the same layout file the editor writes (today via shared volume; in Kubernetes via a ConfigMap or PVC mounted on both sides).

### `GET /health`

Liveness, no auth.

```json
{ "status": "ok" }
```

### `GET /api/layout`

Read the current layout.

The placement-editor writes layouts in v2 shape, with legacy v1 top-level keys preserved for backward compatibility (the positioning-demo still reads `layout.aps`, `layout.gps_origin`, etc.):

```json
{
  "version": 2,
  "floor_plans": [{
    "id":    "fp-01",
    "label": "Polito DAUIN. Floor 1",
    "image": { "data_url": "...", "opacity": 0.7, "filename": "fp01.png" },
    "georef": {
      "latitude":    45.064312,
      "longitude":   7.659154,
      "azimuth_deg": 0.0,
      "altitude_m":  240.0,
      "width_m":     13.0,
      "height_m":    32.0
    }
  }],
  "rooms": [{
    "id":            "room-01",
    "label":         "Lab",
    "floor_plan_id": "fp-01",
    "x_m":           0.0,
    "y_m":           0.0,
    "width_m":       13.0,
    "height_m":      32.0,
    "rotation_deg":  0.0,
    "anchors": [
      { "id": "AP07",  "technology": "wifi",   "x": 11.5, "y": 28, "height_m": 2.7, "coverage_m": 30, "band": "5GHz", "channel": 36, "tx_power_dbm": 20 },
      { "id": "UWB01", "technology": "wittra", "x": 1.5,  "y": 4,  "height_m": 3.0, "coverage_m": 15 }
    ],
    "walls": []
  }],

  /* Legacy v1 mirror, derived from floor_plans[0] + rooms[0]. */
  "room_w":     13.0,
  "room_h":     32.0,
  "gps_origin": { "latitude": 45.064312, "longitude": 7.659154, "azimuth_deg": 0.0, "altitude_m": 240.0 },
  "aps":        [ … same as rooms[0].anchors … ],
  "walls":      []
}
```

Three layers of abstraction, each scoped to one editor section:

| Layer        | Carries                                                      | Edited in     |
|--------------|--------------------------------------------------------------|---------------|
| `floor_plans[]` | Area on the world map: image + WGS84 origin + bearing + size | World section |
| `rooms[]`    | Bounded indoor areas inside a floor plan                     | Plan section  |
| `anchors[]`  | Per-technology positioning instruments inside a room         | Room section  |

The `aps[]` array (legacy mirror of `rooms[0].anchors`) carries every anchor / reference device, regardless of technology. The field name is kept for back-compat with older v1 consumers.

| Field          | Required | Notes                                                                                                         |
|----------------|----------|---------------------------------------------------------------------------------------------------------------|
| `id`           | yes      | Anchor identifier, unique within the layout                                                                   |
| `technology`   | no (`wifi`) | One of `wifi` / `wittra` / `fiveg` / `gnss`. Unknown values fall back to the wifi visual palette. Drives editor grouping and demo filter chips |
| `x`, `y`       | yes      | Position in metres, local frame (`y` is depth on the SVG / +z in 3D)                                          |
| `height_m`     | no       | Mounting height in metres. Per-technology defaults: WiFi 2.7, UWB 3.0, 5G 10.0, GNSS 0.0                      |
| `coverage_m`   | no       | Visual coverage hint (dashed ring in the editor). Per-technology defaults: WiFi 30, UWB 15, 5G 500, GNSS 0    |
| WiFi-specific  | no       | `band`, `channel`, `tx_power_dbm`, `vendor`, `model`: only meaningful for `technology = "wifi"`              |

`gps_origin` here is the same one-time-survey record as in the floor plan: when the editor saves it, downstream consumers (engine, demo) pick it up without a backend change.

Status codes: `200` on success, `404` when the layout file is missing, `500` when the file exists but is malformed.

### `PUT /api/layout`

Overwrite the layout. Body is the new full JSON (no patching). Unknown top-level fields are preserved (schema is `extra="allow"` so the UI can evolve without backend changes).

```json
{ "status": "ok", "path": "/app/data/layout.json" }
```

Auth: not yet wired in (`v0.0.1` scaffold). When wired, the realm role will be `placement-admin`: distinct from the CAMARA consumer role so a positioning client cannot mutate placement.

## SMF session info

Consumed by the gateway from the Open5GS SMF management API (mocked by [`dev/mock_smf.py`](../dev/mock_smf.py)).

`GET /session-info`:

```json
{
  "sessions": [
    {
      "imsi":          "001010123456786",
      "dnn":           "internet",
      "ipv4":          "10.45.0.3",
      "ipv6":          "",
      "snssai":        { "sst": 1, "sd": "000001" },
      "up_cnx_state":  "ACTIVATED"
    }
  ]
}
```

`up_cnx_state` is `"ACTIVATED"` or `"DEACTIVATED"`. Any value other than `"DEACTIVATED"` is treated as active for defensive handling.
