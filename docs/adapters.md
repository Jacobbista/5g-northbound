# Adapters

An adapter connects one positioning source to the engine. It answers
`GET /measurement/{positioningId}` with the latest fix of a device, registers
itself with the engine, and declares what its source can do. The engine knows
nothing else about a source.

| Adapter | Source | Computes the fix |
|---------|--------|------------------|
| [`wifi-adapter`](https://github.com/Jacobbista/5g-northbound/tree/main/services/wifi-adapter/) | WiFi RSSI scans posted by an edge scanner | this adapter, by multilateration |
| [`vendor-adapter`](https://github.com/Jacobbista/5g-northbound/tree/main/services/vendor-adapter/) | a vendor's REST positioning cloud, described by a schema document | the vendor |
| [`synthetic-adapter`](https://github.com/Jacobbista/5g-northbound/tree/main/services/synthetic-adapter/) | generated devices walking in a room | this adapter |

For a vendor with a REST API, adding a source is a schema document loaded into
`vendor-adapter`, with no code. See
[integrating a vendor REST API](integrating-a-vendor-rest-api.md). A separate
adapter is written for what a schema cannot express: a proprietary SDK, a push
transport, an on-site solver. Adapters that carry vendor SDKs or material
under NDA live in private repositories and ship as private images that
implement the same contract.

No adapter exists yet for 5G positioning or GNSS. The editor can place anchors
of those technologies, and an asset whose capability names such a source has
no position.

## HTTP contract

| Endpoint | Required | Purpose |
|----------|----------|---------|
| `GET /measurement/{positioningId}` | yes | the latest fix of a device, or `404` when there is none |
| `GET /health` | yes | liveness: `200` while the process runs |
| `GET /ready` | yes | readiness: `200` once the configuration is loaded, otherwise `503 {"status": "not-ready", "error": …}` |
| `GET /devices` | with the `devices` capability | the devices the source knows, for onboarding |
| `PUT`, `DELETE /devices/{id}/placement` | with the `placement` capability | the start point of a synthetic device |

Other endpoints, such as the WiFi ingest path or the vendor schema, belong to
one adapter. The engine never calls them.

### `GET /measurement/{positioningId}`

The machine-readable contract is
[`schema/adapter-measurement.schema.json`](https://github.com/Jacobbista/5g-northbound/blob/main/schema/adapter-measurement.schema.json),
generated from the model the engine parses with. A body that does not satisfy
it is dropped as malformed.

```json
{
  "source":     "wifi",
  "frame":      "room",
  "room":       "room-01",
  "x":          11.5,
  "y":          10.3,
  "accuracy":   2.4,
  "confidence": 0.85,
  "timestamp":  1790500000.0
}
```

```json
{
  "source":    "wittra",
  "frame":     "wgs84",
  "latitude":  59.404251,
  "longitude": 17.949247,
  "z":         1.2,
  "confidence": 0.95,
  "timestamp": 1790500000.0,
  "lastSeen":  1790507200.0
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `source` | string | Technology tag. Defaults to the adapter's registered name. |
| `frame` | `room`, `venue`, `wgs84` | Reference of the horizontal position. Defaults to `venue`. |
| `room` | string | Blueprint room id. Required with `frame: room`. A room the blueprint does not hold leaves the fix unplaced, and the engine drops it. |
| `x`, `y` | metres | Required with `room` or `venue`: x along the width, y along the depth, from the lower-left corner. |
| `latitude`, `longitude` | degrees | Required with `wgs84`. The engine applies the venue georef. |
| `z` | metres, optional | Height above the venue floor. Sent only when measured for this fix, by a source that declares `z: true`. |
| `verticalAccuracy` | metres, optional | One-sigma error of `z`. Sent only with `z`, when the source reports it. |
| `accuracy` | metres, optional | One-sigma horizontal error radius. When absent the engine uses the declared nominal accuracy ([below](#accuracy_class-and-nominal-accuracies)). |
| `confidence` | 0 to 1, optional | The source's own reliability score, a multiplier on the fusion weight. At 0 the measurement is left out. |
| `timestamp` | epoch seconds | Required. When the fix was taken. |
| `lastSeen` | epoch seconds, optional | When the device last communicated with its source. For an `on_motion` source it confirms the last fix. Published as `lastCommunicationTime`. |

`room` suits a source that computes inside a room from anchors placed in it,
as RSSI multilateration does. `wgs84` suits a source whose backend is placed on
a map, as vendor clouds usually are. The frames are defined in
[architecture](architecture.md#coordinate-frame).

A `404` means no fix for this device, and the engine skips the source for that
cycle. Network errors, `5xx` responses and malformed bodies count as failures:
after three in a row the engine stops calling the adapter for 2 s, doubling up
to 60 s while failures continue, and a success resets the count. Other `4xx`
responses, such as a rejected credential, skip the cycle without counting. An adapter returns its last fix with its real `timestamp`
however old it is. The engine and the gateway judge its age.

### `GET /devices`

```json
{
  "origin": "inventory",
  "devices": [
    { "id": "wittra-tag-01", "role": "asset", "sourceClass": "uwb",
      "deviceType": "tag", "label": "Tag 01", "lastSeen": 1790507200.0 }
  ]
}
```

The contract is
[`schema/adapter-devices.schema.json`](https://github.com/Jacobbista/5g-northbound/blob/main/schema/adapter-devices.schema.json).
`origin` is `inventory` when the source keeps a list of its devices, and
`observed` when a device appears only once it is seen. `id` becomes a
capability's `positioningId` when the device is onboarded. `role` separates
tracked assets from fixed infrastructure such as anchors, which are never
onboarded. The engine aggregates the lists of all adapters, and the gateway
offers the devices not yet onboarded at `GET /assets/discoverable`. See
[asset registry](asset-registry.md#onboarding-discovered-devices).

## Registration

An adapter registers with `POST /adapters` on the engine at start, repeats it
as a heartbeat, and deregisters on shutdown. It reads four variables:

| Variable | Meaning |
|----------|---------|
| `POSITIONING_ENGINE_URL` | the engine |
| `ADAPTER_NAME` | the name it registers under, equal to the `source` of the capabilities it serves |
| `ADAPTER_BASE_URL` | the URL the engine uses to reach it |
| `ADAPTER_CAPABILITIES` | the declaration below, as JSON |

The body is
[`schema/adapter-announcement.schema.json`](https://github.com/Jacobbista/5g-northbound/blob/main/schema/adapter-announcement.schema.json).
The engine refuses a malformed declaration with `422`. Lifecycle, health and
routing are in [adapter registry](adapter-registry.md). The in-repository
adapters share one implementation, `app/register.py`.

## What an adapter declares

Each adapter image carries `adapter.contract.yaml`. Its `capabilities` state
what is true of the binary, and `ADAPTER_CAPABILITIES` adds what is true of the
source it is bound to in one deployment. The adapter announces the merge.
`make positioning-check` verifies that the compose file and the contract files
agree.

| Key | Meaning |
|-----|---------|
| `source` | technology tag of the fixes |
| `kinds` | asset kinds the source positions |
| `frame` | frame of its measurements |
| `z` | the source measures height. A height from a source without `z: true` is discarded, with its `verticalAccuracy` |
| `accuracy_class` | `sub-metre`, `metre` or `coarse` |
| `nominalAccuracy` | metres, for a fix that reports no `accuracy` |
| `nominalVerticalAccuracy` | metres, for a fix that carries `z` without `verticalAccuracy`. Requires `z: true` |
| `reporting`, `reportingInterval` | how the source produces fixes |
| `streaming` | the adapter pushes instead of being polled (none does today) |
| `devices`, `discover`, `diagnostics`, `calibration`, `placement` | the optional endpoints it serves |

The `vendor-adapter` image is generic, so its contract file declares only its
endpoints. Every trait of the bound vendor arrives in `ADAPTER_CAPABILITIES`.

### `reporting` and `reportingInterval`

`reporting` states how the source produces fixes, and so how old a position
really is.

| `reporting` | The source | A position holds as of |
|-------------|------------|------------------------|
| `on_request` | computes a fix at each poll | the fix time |
| `periodic` | produces a fix at least every `reportingInterval` | the fix time |
| `on_motion` | produces a fix whenever the device moves, and communicates at least every `reportingInterval` while it is still | the later of the fix time and `lastSeen` |

`reportingInterval` is the longest time between two reports the source
guarantees, in seconds, transport included. It is required with `periodic` and
`on_motion`. A position is **current** when it is as recent as its source can
provide: always for `on_request`, within one `reportingInterval` for the other
two. A source that declares no model counts as `periodic` without an interval:
its position holds as of the fix time and is never current.

Under `on_motion`, a communication confirms the last fix because the
declaration states that any movement produces a new one. Whoever binds the
adapter to a source answers for the declaration. `vendor-adapter` checks it
against the schema and the payloads (see
[integrating a vendor REST API](integrating-a-vendor-rest-api.md#declaring-how-the-source-reports)).

For each fused position the engine reports `establishedAt`, the earliest
established time among its contributions, and `current`, true when every
contribution is current. The gateway judges `maxAge` on them.

| Adapter | `reporting` | `reportingInterval` |
|---------|-------------|---------------------|
| `synthetic-adapter` | `on_request` | |
| `wifi-adapter` | `periodic` | 2 s, for the edge scanner's default of one scan a second |
| `vendor-adapter` | per deployment | per deployment |

### `accuracy_class` and nominal accuracies

`accuracy_class` is the band the source's technology usually delivers. The
bands are defined in
[`spec/private-profile/accuracy-class-vocabulary.json`](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/accuracy-class-vocabulary.json).
An application reads them from `GET /capabilities` to weigh a position by its
provenance as well as its radius. The class describes the technology, not a
bound on each fix: a degraded fix reports its own larger accuracy.

The engine also uses them for a source that reports no accuracy. It takes the
adapter's `nominalAccuracy` if declared, otherwise the upper bound of the
declared class. `coarse` has no upper bound, so a `coarse` source without
per-fix accuracy must declare `nominalAccuracy`. A measurement with no way to
obtain an accuracy is dropped with a warning.

`nominalVerticalAccuracy` does the same for the height: a fix that carries `z`
without `verticalAccuracy` takes it. There are no vertical classes. Without the
declaration such a fix has no vertical error, and a fused height that includes
it has none either. The fusion needs no vertical error, so the fix is kept.

Both nominal values describe the deployed hardware, so they belong in the
deployment's `ADAPTER_CAPABILITIES`. `confidence` is a different quantity: the
source's score for one fix, which multiplies its weight in the fusion.

### `placement`

A synthetic source can be told where a device starts. `PUT
/devices/{id}/placement` takes `{x, y}` in the frame of the room the source
walks and clamps the point into it. `DELETE` removes the device, which then
has no position. With `SPAWN_REQUIRED` set, a device reports nothing until
placed. The gateway offers this per asset at `/assets/{assetId}/placement` and
refuses a source that does not declare `placement` with `422 NOT_PLACEABLE`.

## Engine options per adapter

The engine reads optional variables per adapter name, uppercased with other
characters replaced by `_` (`wittra` becomes `WITTRA`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `ADAPTER_<NAME>_API_KEY` | unset | a token the engine sends on every request to this adapter |
| `ADAPTER_<NAME>_API_KEY_HEADER` | `X-API-Key` | the header carrying it |
| `ADAPTER_<NAME>_TIMEOUT` | `1.0` | request timeout in seconds |

They are declared in the engine's environment contract with the placeholder
`{NAME}`, and the key is sensitive. Adapters inside the cluster need none of
them. An adapter reached over an
untrusted network needs TLS and authentication, and one that accepts pushes
from devices, as `wifi-adapter` does, authenticates or rate-limits them itself.

## Writing an adapter

```python
from typing import Optional

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel


class Measurement(BaseModel):
    frame: str = "room"
    room: str = "room-01"
    x: float
    y: float
    z: Optional[float] = None
    accuracy: Optional[float] = None
    confidence: Optional[float] = None
    timestamp: float


app = FastAPI()
latest: dict[str, Measurement] = {}   # filled by the adapter's own ingestion
ready = True


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready_probe(response: Response):
    if not ready:
        response.status_code = 503
        return {"status": "not-ready", "error": "configuration not loaded"}
    return {"status": "ready"}


@app.get("/measurement/{positioning_id}", response_model=Measurement, response_model_exclude_none=True)
async def measurement(positioning_id: str):
    if positioning_id not in latest:
        raise HTTPException(404)
    return latest[positioning_id]
```

Add registration (copy `app/register.py` from an in-repository adapter), an
`adapter.contract.yaml`, and an `env.contract.yaml` served at `GET /contract`.
Package it as an image listening on port 8080 with a non-root user, and deploy
it with a `ClusterIP` Service. Once it registers, the engine routes to it every
capability whose `source` equals its `ADAPTER_NAME`.

`wifi-adapter` is the reference for a source that computes on site: an ingest
endpoint receives raw scans, a solver turns them into positions, and
`/measurement` serves the latest one. Its configuration and calibration are in
[blueprint vs bindings](blueprint-vs-bindings.md).
