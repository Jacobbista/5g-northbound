# Data Contracts

This document is the source of truth for the data contracts between the components in this repository and any external consumer.

- [CAMARA Device Location API](#camara-device-location-api): northbound, consumed by browsers and any third-party CAMARA client.
- [Vendor extensions on the gateway](#vendor-extensions-on-the-gateway): non-CAMARA endpoints used by the demo UI (`/assets`, `/assets/{assetId}/details`, `/capabilities`, `/anchors/calibration`, `/adapters`, `/positions/stream` WebSocket).
- [Engine northbound contract](#engine-northbound-contract): internal, between `camara-gateway` and `positioning-engine`.
- [Adapter contract](#adapter-contract): internal, between `positioning-engine` and adapter pods (see [`adapters.md`](adapters.md) for the full implementer's guide).
- [Asset Identity Map](#asset-identity-map): the assets the gateway resolves and serves.
- [Floor plan](#floor-plan): loaded by the engine at startup.
- [Placement-editor API](#placement-editor-api): operator-facing service that owns the floor-plan / AP layout JSON.

A compact endpoint-by-endpoint reference (one row per route) is available in [`api-reference.md`](api-reference.md). This document explains the *contracts*; the reference is the *index*.

## CAMARA Device Location API

The gateway implements two distinct CAMARA APIs, pinned to meta-release **r3.2** (commit `bc17ceeb4ee34929d5f65b8851d99d4dda4c5af1`). The pinned OpenAPI documents in [`camara-gateway/spec/`](https://github.com/Jacobbista/5g-northbound/tree/main/services/camara-gateway/spec/) are the source of truth, the examples below are illustrative.

### Device identifier

This is the **private-asset profile** of the CAMARA `device` object: the tracked entity is an **asset** with a business id, not a phone subscriber. Every request carries a `device` object with an `assetId`:

```json
{ "assetId": "pkg-4471" }
```

`networkAccessIdentifier` (NAI) is accepted as an alias for `assetId` so off-the-shelf CAMARA clients that only emit NAI still work; it is treated as the asset id verbatim. `phoneNumber`, `ipv4Address`, and `ipv6Address` are **not** part of this profile, a private venue does not address assets by MSISDN or IP. See [the private-asset profile](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/README.md) for the rationale.

The gateway resolves `assetId` to a positioning source and tenant via the [Asset Identity Map](#asset-identity-map).

Errors use the CAMARA envelope `{status, code, message}`. Standard codes:

| HTTP | `code`                  | When                                              |
|------|-------------------------|---------------------------------------------------|
| 401  | `UNAUTHENTICATED`       | Missing or invalid JWT                            |
| 403  | `PERMISSION_DENIED`     | JWT lacks the `camara-location-read` realm role   |
| 404  | `IDENTIFIER_NOT_FOUND`  | `assetId` not in the asset map, **or** it belongs to another tenant (cross-tenant lookups 404 rather than leaking existence) |
| 404  | `NOT_FOUND`             | Asset exists but the engine has no fix            |
| 422  | `MISSING_IDENTIFIER`    | `device` body is absent                           |
| 502  | `BAD_GATEWAY`           | Engine reachable but returned 5xx                 |
| 503  | `SERVICE_UNAVAILABLE`   | Engine unreachable (network / DNS / timeout)      |

### Location Retrieval v0.5

`POST /location-retrieval/v0.5/retrieve`

Request:

```json
{ "device": { "assetId": "pkg-4471" }, "maxAge": 120 }
```

Response (`Location`):

```json
{
  "lastLocationTime": "2024-01-01T12:00:00Z",
  "area": {
    "areaType": "CIRCLE",
    "center":   { "latitude": 45.064312, "longitude": 7.659154 },
    "radius":   50.0
  },
  "source":           "wittra",
  "kind":             "pallet",
  "altitude":         240.4,
  "verticalAccuracy": 2.0
}
```

`area` is either a `CIRCLE` (centre + radius ≥ 1 m) or, per spec, a `POLYGON`. `radius` is in metres. `source`, `kind`, `altitude`, and `verticalAccuracy` are private-profile additions: descriptive fields the demo surfaces; a plain CAMARA client ignores them. `device` is mandatory; absence yields `422 MISSING_IDENTIFIER`.

### Location Verification v3

`POST /location-verification/v3/verify`

Request:

```json
{
  "device": { "assetId": "pkg-4471" },
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

The token's `org` claim is the tenant. The gateway joins it against each asset's `org`: a consumer sees and resolves only its own assets. A token with **no** `org` claim is treated as an operator and bypasses the tenant filter (fail-open for single-tenant / debug deployments). See [the profile](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/README.md) for the authorization model.

## Vendor extensions on the gateway

These endpoints live on the same gateway service but are **not part of CAMARA Device Location**. They support the demo UI (and any consumer that needs to enumerate or inspect assets). They share the same authentication: `Authorization: Bearer <jwt>` with the `camara-location-read` realm role, and the same `org`-scoping. `GET /health` is exempt; everything else requires a valid token.

### Asset discovery

`GET /assets` → every asset the caller's tenant owns.

```json
{
  "assets": [
    { "asset_id": "tool-880", "positioning_id": "wifi-asset-01", "source": "wifi",   "kind": "tool",     "org": "fiskarheden", "label": "Cordless drill 880", "simulated": false },
    { "asset_id": "pkg-4471", "positioning_id": "wittra-tag-01", "source": "wittra", "kind": "pallet",   "org": "fiskarheden", "label": "Timber bundle 01",  "simulated": false }
  ]
}
```

The list is read from the [Asset Identity Map](#asset-identity-map) and filtered to the caller's `org`. Order matches the store. Empty list (`{"assets": []}`) when the tenant owns nothing, not a 404.

`simulated` is `true` when the asset is wired to a synthetic source (`mock-positioning`, `mock-wittra`, or any demo fixture). The UI renders a `MOCK` badge. Real assets omit the field (defaults to `false`).

`PUT /assets` replaces the map (operator action; the editor proxies it). Body is `{"assets":[…]}` conforming to [`schema/asset.schema.json`](https://github.com/Jacobbista/5g-northbound/blob/main/schema/asset.schema.json).

### Asset details

`GET /assets/{assetId}/details` → asset entry + engine telemetry.

```json
{
  "asset_id":       "pkg-4471",
  "positioning_id": "wittra-tag-01",
  "source":         "wittra",
  "kind":           "pallet",
  "org":            "fiskarheden",
  "label":          "Timber bundle 01",
  "telemetry": {
    "latitude":         45.064547,
    "longitude":        7.659272,
    "altitude_m":       240.4,
    "accuracy_m":       1.5,
    "lastLocationTime": "2026-06-03T14:36:17Z",
    "strategy":         "weighted_avg",
    "sources":          ["wittra"]
  }
}
```

- `telemetry` is `null` when the engine has no fix, the asset is **registered but offline**, not an error.
- `assetId` not in the caller's tenant → `404 IDENTIFIER_NOT_FOUND` (a cross-tenant id is indistinguishable from a missing one).
- Surfaces engine fields (`strategy`, `sources`, `altitude_m`) intentionally hidden by the CAMARA `Location` response. Field names match the engine's `EnginePosition` to make the boundary obvious.

### Capabilities

`GET /capabilities` → what this deployment can do, aggregated live from the registered adapters and the tenant's assets.

```json
{
  "adapters":  [ { "name": "wifi", "kind": "wifi", "capabilities": { "modalities": ["wifi"], "fixed": false } } ],
  "sources":   ["wifi", "wittra"],
  "kinds":     ["tool", "pallet"]
}
```

`sources` and `kinds` are derived from the caller's own assets; `adapters` mirrors the engine's live registry (see [adapter-registry.md](adapter-registry.md)). The editor uses this to offer a `source` picker bound to adapters that actually exist.

### Anchor calibration

`GET /anchors/calibration` → real per-AP RF parameters, proxied from wifi-positioning's `/calibration/params`.

```json
{
  "anchors": [
    { "id": "AP07", "tx_power_ref_dbm": -39.0, "path_loss_n": 2.1, "calibrated": true }
  ]
}
```

Exposes the *measured* RF (from the calibration tool, persisted in the bindings) so the demo shows true radio parameters instead of the editor's placeholder defaults. No BSSIDs cross this boundary. Empty / disabled when `WIFI_POSITIONING_URL` is unset.

### Adapter health

`GET /adapters` → operator diagnostic, proxied from the engine's [`/adapters`](#engine-adapter-status) snapshot. Lets the demo show "wittra: degraded" without bypassing the gateway (the demo is not allowed to talk to the engine directly).

```json
{
  "adapters": [
    { "name": "wifi",   "base_url": "http://wifi-positioning:8080",   "fail_count": 0, "in_cooldown": false, "cooldown_seconds_remaining": 0.0 },
    { "name": "wittra", "base_url": "https://api.wittra.example.com", "fail_count": 5, "in_cooldown": true,  "cooldown_seconds_remaining": 23.5 }
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

Token is supplied as a query parameter because browsers cannot set `Authorization` headers on a WebSocket handshake. The gateway validates the token against the same Keycloak realm and `camara-location-read` role as the REST endpoints, opens a single upstream connection to the engine's `/ws/positions`, and forwards every payload after **enriching it from the asset map** (the engine broadcasts `positioning_id`; the gateway maps each to its asset and drops unregistered or cross-tenant entries). Each payload is a JSON array, one object per asset with at least a fix:

```json
[
  {
    "asset_id":        "pkg-4471",
    "positioning_id":  "wittra-tag-01",
    "source":          "wittra",
    "kind":            "pallet",
    "org":             "fiskarheden",
    "latitude":        45.064547,
    "longitude":       7.659272,
    "altitude_m":      240.4,
    "accuracy_m":      1.5,
    "timestamp":       "2026-06-10T07:36:01Z",
    "sources":         ["wittra"],
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

`GET /position/{positioning_id}?source=<source>` → `EnginePosition`:

```json
{
  "device_id":  "wifi-asset-01",
  "latitude":   45.064581,
  "longitude":  7.659408,
  "altitude_m": 240.4,
  "accuracy_m": 0.3,
  "timestamp":  "2024-01-01T12:00:00Z",
  "sources":    ["wifi"],
  "strategy":   "weighted_avg",
  "fusions":    null
}
```

The path id is the asset's `positioning_id` (the internal/vendor-native id), **not** the CAMARA `assetId`; the gateway substitutes it from the asset map. The optional `?source=` query selects routing (see below). The engine owns its native coordinate frame and normalises to WGS84 at this boundary; `altitude_m` is the origin altitude plus the local vertical. The gateway passes `latitude`/`longitude` straight into the CAMARA `area.center`, with `radius = max(accuracy_m, 1)`.

**Routing.** `?source=<x>` selects the single registered adapter whose `ADAPTER_NAME == x`. If `source` is absent or matches no adapter, the engine falls back to the optional `DEVICE_MAP` (`positioning_id=adapter` pins), and finally fans out to every registered adapter and fuses the responders. The gateway always passes the asset's `source`, so steady-state routing is single-adapter; fan-out is the no-source fallback. See [adapter-registry.md](adapter-registry.md).

The **broadcast** is also single-adapter, not fan-out: it does not read a static id list or the asset map but learns its target ids from adapters advertising the `devices` capability, and routes each id to the adapter that reported it (the reporter *is* the source). This keeps the engine asset-agnostic. When two adapters report the same id (a misconfiguration - steady state is one source per id), precedence is deterministic: higher `origin` rank (`observed` > `inventory`), then adapter name alphabetically. `DEVICE_IDS` is only a cold-start seed used when no adapter advertises `devices`.

Status codes the engine returns:

| HTTP | When                                                                                              |
|------|---------------------------------------------------------------------------------------------------|
| 200  | At least one adapter returned a measurement and fusion succeeded                                  |
| 404  | No adapter has a fix for this id (legitimate "offline", not an error)                             |
| 500  | Fusion or projection raised an unexpected exception                                               |

The gateway propagates these:

| Engine response          | Gateway response                                  |
|--------------------------|---------------------------------------------------|
| 200                      | 200 with CAMARA `Location`                         |
| 404                      | 404 `NOT_FOUND` (CAMARA envelope)                  |
| 5xx                      | 502 `BAD_GATEWAY` (after one short retry)          |
| network error / timeout  | 503 `SERVICE_UNAVAILABLE` (after one short retry)  |

Transient engine failures (`5xx`, connect errors, read timeouts) are retried once after a 200 ms backoff before the gateway gives up. `404` is **not** retried (it's a legitimate "no fix", not a failure to reach the engine).

When `POSITIONING_ENGINE_URL` is **unset** the gateway falls back to a built-in mock position so the system degrades gracefully in dev. As soon as the env var points at a real engine, the engine is the only source of truth, no silent mock fallback.

#### Engine adapter status

`GET /adapters` on the engine returns the same shape proxied by the gateway above, the engine is the source of truth, the gateway forwards it as a vendor extension. Useful when debugging the engine directly:

```bash
curl http://localhost:8081/adapters
```

`strategy` names the primary fusion algorithm that produced the result; see [`fusion-strategies.md`](fusion-strategies.md). `fusions` is `null` unless the engine is configured with `FUSION_COMPARE`, in which case it maps each comparison strategy name to its own `{latitude, longitude, accuracy_m, sources}`: used by the demo to render multiple tracks side by side, ignored by the CAMARA gateway.

## Adapter contract

Adapter pods expose the following endpoint, consumed by the engine via [`HttpAdapter`](https://github.com/Jacobbista/5g-northbound/blob/main/services/positioning-engine/app/adapters/http.py):

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

`{device_id}` here is the asset's `positioning_id`, substituted verbatim. `404 Not Found` indicates no measurement for it. `timestamp` is Unix epoch seconds; omit for "now". `frame` declares the coordinate system of the reply. `"local"` (default) means x/y/z are metres in the floor-plan-local frame (origin = lower-left corner, x = east, z = north, y = vertical), `"wgs84"` means the reply carries `latitude` and `longitude` instead and the engine projects them into the local frame using the georeference before fusion. See [`adapters.md`](adapters.md) for the full specification and implementer's guide.

## Asset Identity Map

The gateway is the **network authority for asset identity**, mirroring the way the engine owns the blueprint. It serves the map over [`GET/PUT /assets`](#asset-discovery) and persists it to a writable store.

| Path | Role |
|------|------|
| `ASSET_STORE_FILE` (`/app/data/assets.json`, PVC) | the live, writable map |
| `ASSET_SEED_FILE` (`/app/config/assets.seed.json`) | read-only seed, copied to the store once on first boot when it is empty |

The dev fixture is [`dev/assets.json`](https://github.com/Jacobbista/5g-northbound/blob/main/dev/assets.json). The store content is tenant inventory (Tier-1): gitignored in dev, never committed, PVC-backed in prod. Each entry conforms to [`schema/asset.schema.json`](https://github.com/Jacobbista/5g-northbound/blob/main/schema/asset.schema.json):

```json
{
  "asset_id":       "pkg-4471",
  "positioning_id": "wittra-tag-01",
  "source":         "wittra",
  "kind":           "pallet",
  "org":            "fiskarheden",
  "label":          "Timber bundle 01",
  "simulated":      false
}
```

- `asset_id`: the business identifier the consumer sends in `device.assetId`. **Not** a phone number.
- `positioning_id`: the internal id the engine fuses on. For a vendor adapter it **must equal the vendor-native device id** (substituted verbatim into the vendor path). See [integrating-a-vendor-rest-api.md](integrating-a-vendor-rest-api.md#identity-resolution-from-a-camara-assetid-to-a-vendor-fix).
- `source`: **must equal the adapter's `ADAPTER_NAME`**, it is the routing key (see [Engine northbound contract](#engine-northbound-contract)).
- `kind`: asset class (`tool` / `pallet` / `forklift` / `uwb-tag` / …), descriptive.
- `org`: tenant; the gateway gates consumers by it.
- `label`: human-readable name surfaced by the demo. Optional; defaults to `asset_id`.
- `simulated`: optional boolean (default `false`). `true` for assets wired to a fixture, so the UI can render a `MOCK` badge.

## Floor plan

Loaded at engine startup from `/app/config/floor-plan.json` (mounted in production from the `positioning-floor-plan` Kubernetes ConfigMap). In steady state the placement-editor PUTs the blueprint over HTTP; this file is the cold-start seed.

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

`gps_origin` is the **single georeference** that links the local floor-plan frame (metres, lower-left origin, +x east-ish / +z north-ish) to WGS84. Survey it once for a venue; every anchor and asset position is then carried in local metres and projected to lat/lon at the engine boundary. This bounds positioning error by *one* calibration instead of letting it accumulate per AP.

| Field         | Required | Notes                                                                       |
|---------------|----------|-----------------------------------------------------------------------------|
| `latitude`    | yes      | Latitude of the floor-plan origin (lower-left corner of the room)          |
| `longitude`   | yes      | Longitude of the floor-plan origin                                          |
| `azimuth_deg` | no (0)   | Bearing of the local +z axis (the SVG "up") clockwise from true north. 0 means the room is north-aligned; 30 means the room is rotated 30° east of north |
| `altitude_m`  | no       | Altitude of the origin above sea level. Added to the local vertical to produce `altitude_m` on the fix |

`gps_origin` itself is optional. When absent, the engine returns `latitude: 0, longitude: 0` and logs a warning. The development fixture [`dev/floor-plan.json`](https://github.com/Jacobbista/5g-northbound/blob/main/dev/floor-plan.json) carries a placeholder origin so the local demo works; the production ConfigMap omits it until a real lab GPS reference is available. The full georeference model (datums, tile drift, N-point calibration) is in [`georeferencing.md`](georeferencing.md).

## Placement-editor API

Standalone operator-facing service that owns the floor-plan / AP layout JSON. Lives in [`services/placement-editor/`](https://github.com/Jacobbista/5g-northbound/tree/main/services/placement-editor/) and ships as its own image. The demo and the engine both consume the same layout the editor writes (the engine is the blueprint authority; the editor PUTs to it).

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
      { "id": "AP07",  "technology": "wifi",   "x": 11.5, "y": 28, "height_m": 2.7, "coverage_m": 30 },
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

Real per-AP RF (`tx_power_ref_dbm`, `path_loss_n`) is **not** authored here, it is measured by the calibration tool and lives in the bindings, surfaced via [`/anchors/calibration`](#anchor-calibration). See [`blueprint-vs-bindings.md`](./blueprint-vs-bindings.md).

`gps_origin` here is the same one-time-survey record as in the floor plan: when the editor saves it, downstream consumers (engine, demo) pick it up without a backend change.

Status codes: `200` on success, `404` when the layout file is missing, `500` when the file exists but is malformed.

### `PUT /api/layout`

Overwrite the layout. Body is the new full JSON (no patching). Unknown top-level fields are preserved (schema is `extra="allow"` so the UI can evolve without backend changes).

```json
{ "status": "ok", "path": "/app/data/layout.json" }
```

Auth: not yet wired in (`v0.0.1` scaffold). When wired, the realm role will be `placement-admin`: distinct from the CAMARA consumer role so a positioning client cannot mutate placement.

## Blueprint vs bindings

Venue config splits into two files, geometry (portable, no secrets) and per-venue bindings (BSSIDs / MACs / vendor IDs, never committed). The wifi-positioning service joins them on anchor `id` at startup. The full rationale, layout, and deployment flow live in [`blueprint-vs-bindings.md`](./blueprint-vs-bindings.md).
