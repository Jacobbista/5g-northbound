# Data Contracts

This document is the source of truth for the data contracts between the components in this repository and any external consumer.

- [CAMARA Device Location API](#camara-device-location-api) — northbound, consumed by browsers and any third-party CAMARA client.
- [Engine northbound contract](#engine-northbound-contract) — internal, between `camara-gateway` and `positioning-engine`.
- [Adapter contract](#adapter-contract) — internal, between `positioning-engine` and adapter pods (see [`adapters.md`](adapters.md) for the full implementer's guide).
- [Floor plan](#floor-plan) — loaded by the engine at startup.
- [SMF session info](#smf-session-info) — consumed by the gateway for cross-technology identity resolution.

## CAMARA Device Location API

The gateway implements two distinct CAMARA APIs, pinned to meta-release **r3.2** (commit `bc17ceeb4ee34929d5f65b8851d99d4dda4c5af1`). The pinned OpenAPI documents in [`camara-gateway/spec/`](../camara-gateway/spec/) are the source of truth — the examples below are illustrative.

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

Errors use the CAMARA envelope `{status, code, message}`. Standard codes are `400 INVALID_ARGUMENT`, `401 UNAUTHENTICATED`, `403 PERMISSION_DENIED`, `404 IDENTIFIER_NOT_FOUND`, `422 MISSING_IDENTIFIER`.

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
  "sources":    ["uwb", "wifi"]
}
```

The engine owns its native coordinate frame and normalises to WGS84 at this boundary. The gateway passes `latitude`/`longitude` straight into the CAMARA `area.center`, with `radius = max(accuracy_m, 1)`. When `POSITIONING_ENGINE_URL` is unset or unreachable the gateway falls back to a built-in mock position so the system degrades gracefully.

## Adapter contract

Adapter pods expose the following endpoint, consumed by the engine via [`HttpAdapter`](../positioning-engine/app/adapters/http.py):

```
GET /measurement/{device_id}  → 200 OK
{
  "source":     "wifi",
  "x":          11.5,
  "y":          0.0,
  "z":          10.3,
  "accuracy_m": 6.6,
  "confidence": 0.85,
  "timestamp":  1700000000.0
}
```

`404 Not Found` indicates no measurement for the device. `timestamp` is Unix epoch seconds; omit for "now". Coordinates are in the room-local frame defined by the floor plan (origin = lower-left corner, x = east, z = north, y = vertical). See [`adapters.md`](adapters.md) for the full specification and implementer's guide.

## Floor plan

Loaded at engine startup from `/app/config/floor-plan.json` (mounted in production from the `positioning-floor-plan` Kubernetes ConfigMap).

```json
{
  "version": 1,
  "gps_origin": { "latitude": 45.064312, "longitude": 7.659154 },
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

`gps_origin` is optional. When absent, the engine returns `latitude: 0, longitude: 0` and logs a warning. The development fixture [`dev/floor-plan.json`](../dev/floor-plan.json) carries a placeholder origin so the local demo works; the production ConfigMap omits it until a real lab GPS reference is available.

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
