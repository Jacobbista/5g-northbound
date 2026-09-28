# Blueprint and bindings

The venue configuration is in two documents. The **blueprint** describes the
building: floor plans, rooms, walls, anchors and the georeference. The
**bindings** tie the WiFi anchors of the blueprint to the radios of one
installation: the BSSIDs of each access point, the propagation parameters and
the calibration survey.

| | Blueprint | Bindings |
|---|-----------|----------|
| Content | geometry and anchor positions | BSSIDs, propagation parameters, calibration samples |
| Changes when | the building or the anchor layout changes | an access point is replaced or recalibrated |
| Held by | positioning-engine, `GET`/`PUT /blueprint` | wifi-adapter, `GET`/`PUT /bindings` |
| Edited in | placement-editor | placement-editor calibration panel, or a file |
| Committed | the placeholder `layout.example.json` only | the placeholder `dev/wifi-config.json` only |

The two are joined on the anchor `id`. A blueprint carries no BSSID, so it can
be shared and moved between installations. The bindings carry real network
identifiers and stay on the installation.

## The blueprint

The contract is
[`schema/layout.schema.json`](https://github.com/Jacobbista/5g-northbound/blob/main/schema/layout.schema.json),
version 3, with an example in
[`schema/examples/layout.example.json`](https://github.com/Jacobbista/5g-northbound/blob/main/schema/examples/layout.example.json).
The engine stores it at `BLUEPRINT_PATH` (`/app/data/blueprint.json`), on its
own persistent volume. `PUT /blueprint` migrates an older version to version 3,
validates the document against the schema (`422` on violation), persists it and
applies the new georeference without a restart. At start the engine migrates
a stored older version in place, and when the file is absent it copies
`BLUEPRINT_SEED_PATH` into it once.

| Service | Access |
|---------|--------|
| placement-editor | reads and writes it through its `/api/layout` proxy |
| wifi-adapter | reads it at start, see below |
| synthetic-adapter | reads it to walk inside the first room and its walls, with `LAYOUT_PATH` as a fallback file and `WIDTH_M`/`DEPTH_M` as bounds without either |
| camara-gateway | serves it read-only on `GET /blueprint` to CAMARA consumers |
| location-app | reads it from the gateway |

The engine answers `/blueprint` without authentication. It is reachable only
inside the cluster, and writes arrive through the placement-editor, which sits
behind the operator's access gate.

## Authoring in the placement editor

The editor has three sections: **World** places the floor plan on the map,
**Plan** places the rooms on the floor plan, **Room** places anchors and walls
in one room. Every change is written to the engine 600 ms after it is made.
The [georeferencing](georeferencing.md) page describes the World and Plan
calibrations.

`↓ export` downloads the blueprint as `blueprint-<timestamp>.json`.
`↑ import` loads such a file, including version 1 and 2 documents, and
replaces the current blueprint. The replaced one stays on the undo stack. This
is how a venue moves between installations.

Anchors that a vendor cloud already positions can be imported instead of
placed by hand: the `↻ sync` button of an adapter that advertises `discover`
lists the vendor's devices on the room
([the device list](integrating-a-vendor-rest-api.md#the-device-list)).

## The bindings

wifi-adapter reads the bindings from `WIFI_CONFIG_PATH`
(`/app/config/wifi-config.json`):

```json
{
  "tx_power": -42.0,
  "path_loss_n": 2.7,
  "algorithm": "trilateration",
  "weight_power": 2.0,
  "smoothing": true,
  "process_noise": 1.0,
  "motion_model": "random-walk",
  "bindings": [
    { "id": "AP07", "bssids": ["AA:BB:CC:00:07:01", "AA:BB:CC:00:07:02"] },
    { "id": "AP08", "bssids": ["AA:BB:CC:00:08:01", "AA:BB:CC:00:08:02"] }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `tx_power`, `path_loss_n` | the log-distance model: RSSI at 1 m in dBm, and path-loss exponent. A binding may carry its own pair, written by calibration |
| `algorithm` | `trilateration` (least squares over all ranges) or `centroid` (average of the anchor positions weighted by inverse distance to the power `weight_power`) |
| `smoothing`, `process_noise`, `motion_model` | the Kalman filter applied to each device's fix, see below |
| `bindings` | per anchor `id`, the BSSIDs its radio transmits on |
| `calibration_samples`, `samples_frame` | the calibration survey, written by the adapter |

At start the adapter fetches the blueprint from the engine
(`POSITIONING_ENGINE_URL`), retrying until the engine answers, and falls back to
`LAYOUT_PATH` when that is set. It takes the `wifi` anchors of the first room
and joins them to the bindings on `id`. An anchor without BSSIDs and a binding
without an anchor are logged and skipped. Fixes are in the frame of that room.
An absent or unreadable bindings file counts as empty: the adapter starts with
no bound anchors. Until the blueprint is loaded the pod is not ready.

`GET /contract` reports `routers_bound`, the number of anchors that have both a
position and a BSSID. With `0`, no scan can be located. It also reports
`debug`, whether `WIFI_DEBUG` was set when the process started. With
`WIFI_DEBUG` on, a scan that matches no bound anchor is logged.

### Motion model and algorithm

`motion_model` and `algorithm` are chosen from a set the image implements.
`GET /contract` publishes the set as `motion_models` and `algorithms`, beside
the value in force, and `PUT /bindings` answers `422` for a name outside it.

| `motion_model` | Prediction | Still device | Moving device |
|----------------|------------|--------------|---------------|
| `random-walk` (default) | widens the uncertainty, keeps the estimate | stays put | trails the true position |
| `constant-velocity` | extrapolates along the estimated velocity | drifts after a bad fix while the velocity estimate lasts | follows constant motion without lag |

For a given `process_noise` both models respond equally fast. Under
`random-walk` a higher `process_noise` is more responsive and a lower one
smoother. Under `constant-velocity`, raising it trades drift for jitter and
lowering it makes a drift last longer.

### Calibration

Generic `tx_power` and `path_loss_n` values limit the accuracy of RSSI ranging.
The `↹ calibrate` tool in the editor's Room section fits them per access point
from a survey:

1. Stand at a point in the room and click it. The adapter averages the next ten
   scans from the device into a sample.
2. Repeat across the room. An access point is fitted from the samples that
   hear it at more than 0.5 m, and needs three of them.
3. `⚙ derive` fits the log-distance model per access point and shows
   `tx_power`, `path_loss_n`, R² and the sample count.
4. `✓ apply` writes the fitted pair into each binding and reloads the adapter.
   An access point with too few samples keeps its previous values.

Samples are saved to the bindings file after every capture and deletion, so a
survey survives a restart. The bindings file is therefore written at runtime:
on Kubernetes it lives on a persistent volume, not a ConfigMap or Secret. In
the compose stack, wifi-adapter runs with the host user's uid (`HOST_UID`,
set by `make demo`) so it can write the mounted file.

`⇩ export bindings` and `⇪ import bindings` in the calibration panel read and
replace the whole file through `GET`/`PUT /bindings`, BSSIDs included. An
import applies at once. This is how a calibration moves between installations,
and how a fresh installation receives its BSSIDs. `PUT /bindings` also accepts
the older `routers: [{id, x, y, bssids}]` shape, whose positions it discards.

Outside the cluster the bindings are reached only through the
placement-editor. CAMARA consumers read the
fitted parameters without BSSIDs from the gateway's `GET /anchors/calibration`,
which relays wifi-adapter's `GET /calibration/params`.

## Local files

| File | Role |
|------|------|
| `services/location-app/public/layout.example.json` | committed demo venue |
| `services/location-app/public/layout.json` | ignored by git. `make demo` creates it from the example. The engine uses it as `BLUEPRINT_SEED_PATH` and the synthetic-adapter as `LAYOUT_PATH` |
| `dev/wifi-config.json` | committed bindings with placeholder BSSIDs |
| `dev/wifi-config.local.json` | ignored by git. `make demo` mounts it instead of the placeholder when it exists |

After the first start the engine holds the blueprint, and edits in the editor
do not reach `layout.json`. A real BSSID committed to the repository is a leak:
the access point is then reconfigured.
