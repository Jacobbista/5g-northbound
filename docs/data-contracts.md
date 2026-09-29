# Data contracts

An example of every body the services exchange. The schemas are listed in
[contracts](contracts.md), the routes in [API reference](api-reference.md), and
the meaning of each field on the page each section links to. The examples use
the Stockholm demo venue and the assets of `dev/assets.json`.

## CAMARA retrieval

`POST /location-retrieval/v0.5/retrieve`
([profile](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/README.md)):

```json
{ "device": { "assetId": "robot-2" }, "maxAge": 60, "maxSurface": 100 }
```

```json
{
  "lastLocationTime": "2026-09-29T10:00:05Z",
  "area": {
    "areaType": "CIRCLE",
    "center": { "latitude": 59.404251, "longitude": 17.949247 },
    "radius": 1.0
  },
  "source": "wifi",
  "kind": "forklift",
  "horizontalAccuracy": 0.29,
  "altitude": 32.6,
  "verticalAccuracy": 0.8
}
```

`radius` is `horizontalAccuracy` raised to CAMARA's 1 m minimum. `source` names
the primary capability, although the position here fuses WiFi and UWB.
`altitude` and `verticalAccuracy` are absent when no source measures height or
the venue origin has no surveyed altitude.

## CAMARA verification

`POST /location-verification/v3/verify`:

```json
{
  "device": { "assetId": "pkg-4471" },
  "area": {
    "areaType": "CIRCLE",
    "center": { "latitude": 59.404210, "longitude": 17.949278 },
    "radius": 50
  },
  "maxAge": 60
}
```

```json
{ "verificationResult": "PARTIAL", "matchRate": 72, "lastLocationTime": "2026-09-29T10:00:05Z" }
```

`matchRate` is present with `PARTIAL` only.

## Errors

Every error of the gateway uses the CAMARA envelope, and every response
carries `x-correlator`
([codes](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/README.md#errors)):

```json
{ "status": 422, "code": "LOCATION_RETRIEVAL.UNABLE_TO_FULFILL_MAX_AGE", "message": "Unable to provide a location fresh enough for the requested maxAge." }
```

## Position stream

`WS /positions/stream`, one message per engine broadcast, one entry per asset
with a position
([AsyncAPI](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/asyncapi-stream.yaml)):

```json
[
  {
    "assetId": "pkg-4471",
    "positioningId": "wittra-tag-01",
    "source": "wittra",
    "kind": "pallet",
    "org": "acme",
    "latitude": 59.404251,
    "longitude": 17.949247,
    "accuracy": 0.9,
    "altitude": 32.6,
    "verticalAccuracy": 0.8,
    "timestamp": "2026-09-29T07:36:01Z",
    "observedAt": "2026-09-29T09:36:04Z",
    "lastCommunicationTime": "2026-09-29T09:35:58Z",
    "sources": ["wittra"],
    "strategy": "weighted_avg",
    "diagnostics": { "vendorSpecific": { "motion": "STATIONARY" } }
  }
]
```

| Time | Meaning |
|------|---------|
| `timestamp` | when the fix was taken. It stays fixed while a still asset keeps reporting |
| `observedAt` | when the engine produced this message |
| `lastCommunicationTime` | when the device last communicated with its source, the latest across the fused sources. It stops advancing when the device goes silent |

## Asset surfaces

`GET /assets` returns the asset map filtered by the token's organisation, the
same document `PUT /assets` writes
([asset registry](asset-registry.md#the-document)):

```json
{
  "version": 4,
  "assets": [
    {
      "assetId": "robot-2",
      "kind": "forklift",
      "org": "acme",
      "capabilities": [
        { "source": "wifi", "positioningId": "wifi-asset-02" },
        { "source": "wittra", "positioningId": "wittra-tag-02" }
      ],
      "label": "Mobile robot 2",
      "metadata": { "floor": 0, "note": "WiFi + UWB, fused" }
    }
  ]
}
```

`GET /assets/{assetId}/details`. `telemetry` is `null` when no source has a
position:

```json
{
  "assetId": "robot-2",
  "positioningId": "wifi-asset-02",
  "source": "wifi",
  "kind": "forklift",
  "org": "acme",
  "label": "Mobile robot 2",
  "telemetry": {
    "latitude": 59.404251,
    "longitude": 17.949247,
    "accuracy": 0.29,
    "altitude": 32.6,
    "verticalAccuracy": 0.8,
    "lastLocationTime": "2026-09-29T10:00:05Z",
    "strategy": "weighted_avg",
    "sources": ["wifi", "wittra"]
  }
}
```

`GET /assets/discoverable`, operator token only
([onboarding](asset-registry.md#onboarding-discovered-devices)):

```json
{
  "candidates": [
    { "id": "wittra-tag-09", "source": "wittra", "origin": "inventory", "role": "asset",
      "deviceType": "tag", "label": "Tag 09", "lastCommunicationTime": "2026-09-29T09:58:12Z" },
    { "id": "synthetic-anchor-01", "source": "synthetic", "origin": "inventory",
      "role": "infrastructure", "sourceClass": "uwb" }
  ]
}
```

`PUT /assets/{assetId}/placement` takes a point in the frame of the room the
synthetic source walks. The answer names the room and the point after
clamping ([placement](adapters.md#placement)):

```json
{ "x": 4.0, "y": 2.5 }
```

```json
{ "assetId": "forklift-7", "room": "room-01", "x": 4.0, "y": 2.5, "placed": true }
```

## Device diagnostics

`GET /device-diagnostics/v0/{assetId}`
([vocabulary](profile-extensions.md#diagnostics-vocabulary)):

```json
{
  "assetId": "pkg-4471",
  "source": "wittra",
  "diagnostics": {
    "battery": 84,
    "lastCommunicationTime": "2026-09-29T09:58:12Z",
    "vendorSpecific": { "motion": "STATIONARY", "accuracy_value": 0.42, "accuracy_kind": "vendor-confidence-score" }
  }
}
```

## Deployment surfaces

`GET /capabilities`, for the token's organisation:

```json
{
  "profile": "camara-private-asset",
  "kinds": ["asset", "forklift", "pallet", "tool", "uwb-tag"],
  "sources": ["synthetic", "wifi", "wittra"],
  "orgs": ["acme"],
  "streaming": false,
  "altitude": true,
  "accuracyClasses": ["metre", "sub-metre"],
  "adapters": [
    { "name": "wittra", "source": "wittra", "state": "live",
      "capabilities": { "source": "wittra", "frame": "wgs84", "z": true, "accuracy_class": "sub-metre" } }
  ]
}
```

`kinds` joins the kinds of the organisation's assets with those the adapters
advertise. `altitude` is true when a registered adapter declares `z: true`.

`GET /adapters`:

```json
{
  "adapters": [
    { "name": "wifi", "state": "live", "capabilities": { "source": "wifi", "frame": "room", "z": false } },
    { "name": "wittra", "state": "unreachable", "capabilities": { "source": "wittra", "frame": "wgs84", "z": true } }
  ]
}
```

`state` is `live`, `unreachable` (requests fail and the engine has paused
them) or `stale` (the adapter stopped announcing itself)
([adapter registry](adapter-registry.md)). The list is empty when the engine
cannot be reached.

`GET /anchors/calibration`, fitted parameters per WiFi anchor, without BSSIDs.
`calibrated: false` means the file-level defaults are in force:

```json
{
  "params": {
    "AP07": { "txPowerRef": -39.0, "pathLossExponent": 2.1, "calibrated": true },
    "AP08": { "txPowerRef": -42.0, "pathLossExponent": 2.7, "calibrated": false }
  }
}
```

## Engine position

`GET /position/{positioningId}?source=wittra` on the engine, read by the
gateway
([`engine-position.schema.json`](https://github.com/Jacobbista/5g-northbound/blob/main/schema/engine-position.schema.json)):

```json
{
  "positioningId": "wittra-tag-02",
  "latitude": 59.404251,
  "longitude": 17.949247,
  "accuracy": 0.3,
  "altitude": 32.6,
  "verticalAccuracy": 0.8,
  "timestamp": "2026-09-29T08:12:40Z",
  "establishedAt": "2026-09-29T10:00:05Z",
  "current": true,
  "sources": ["wittra"],
  "strategy": "weighted_avg",
  "fusions": null
}
```

`timestamp` is the fix time and `establishedAt` the latest time the position
is known to hold, here confirmed by later communications of a still tag
([reporting](adapters.md#reporting-and-reportinginterval)). `fusions` carries
the outputs of the comparison strategies when `FUSION_COMPARE` is set
([fusion strategies](fusion-strategies.md)).

## Adapter contract

`GET /measurement/{positioningId}` on an adapter, read by the engine
([adapters](adapters.md)):

```json
{
  "source": "wifi",
  "frame": "room",
  "room": "room-01",
  "x": 11.5,
  "y": 10.3,
  "accuracy": 3.1,
  "confidence": 0.85,
  "timestamp": 1790000000.0
}
```

```json
{
  "source": "wittra",
  "frame": "wgs84",
  "latitude": 59.404251,
  "longitude": 17.949247,
  "z": 1.4,
  "confidence": 0.92,
  "timestamp": 1790000000.0,
  "lastSeen": 1790007200.0
}
```

`POST /adapters` on the engine, the registration and heartbeat
([adapter registry](adapter-registry.md)):

```json
{
  "name": "wittra",
  "baseUrl": "http://vendor-adapter:8080",
  "kind": "vendor",
  "capabilities": {
    "source": "wittra", "kinds": ["pallet", "uwb-tag", "asset"], "frame": "wgs84",
    "z": true, "nominalVerticalAccuracy": 0.8, "accuracy_class": "sub-metre",
    "reporting": "on_motion", "reportingInterval": 900, "devices": true, "discover": true, "diagnostics": true
  }
}
```

`GET /devices` on an adapter, the devices it knows:

```json
{
  "origin": "inventory",
  "devices": [
    { "id": "wittra-tag-09", "role": "asset", "deviceType": "tag", "label": "Tag 09", "lastSeen": 1790007492.0 }
  ]
}
```

## Blueprint

`GET`, `PUT /blueprint` on the engine, and `GET /blueprint` on the gateway
([`layout.schema.json`](https://github.com/Jacobbista/5g-northbound/blob/main/schema/layout.schema.json),
[blueprint and bindings](blueprint-vs-bindings.md)):

```json
{
  "version": 3,
  "floor_plans": [{
    "id": "fp-01",
    "label": "Floor 6",
    "georef": {
      "latitude": 59.4042, "longitude": 17.9492, "azimuth_deg": -36.4,
      "altitude_m": 31.0, "width_m": 40, "depth_m": 30
    }
  }],
  "rooms": [{
    "id": "room-01", "label": "Lab", "floor_plan_id": "fp-01",
    "x_m": 4.0, "y_m": 16.0, "width_m": 10, "depth_m": 8, "rotation_deg": 0,
    "anchors": [
      { "id": "AP01", "technology": "wifi", "x": 1.0, "y": 7.0, "z": 2.7, "coverage_m": 30 }
    ],
    "walls": [
      { "x1": 5.0, "y1": 8.0, "x2": 5.0, "y2": 2.0, "thickness": 0.1, "height_m": 3.0,
        "openings": [{ "start_m": 2.0, "width_m": 1.0 }] }
    ]
  }]
}
```

Each level is placed in its parent, with x along the width, y along the depth,
z up, and the origin at the parent's lower-left corner
([architecture](architecture.md#coordinate-frame)).

| Level | Fields |
|-------|--------|
| floor plan in the world | `georef`: `latitude`, `longitude` of the lower-left corner, `azimuth_deg`, `altitude_m`, `width_m`, `depth_m` ([georeferencing](georeferencing.md#the-georef)) |
| room in the floor plan | `x_m`, `y_m` of its lower-left corner, `width_m`, `depth_m`, `rotation_deg` clockwise about its centre, optional `shape` in room coordinates |
| anchor in the room | `x`, `y`, `z` (mounting height), `technology` (`wifi`, `wittra`, `fiveg`, `gnss`), `coverage_m` |
| wall in the room | `x1`, `y1`, `x2`, `y2`, `thickness`, `height_m`, `openings` measured along the wall from (`x1`, `y1`) |

The engine migrates a stored version 1 or 2 document to version 3 at start and
on `PUT`.
