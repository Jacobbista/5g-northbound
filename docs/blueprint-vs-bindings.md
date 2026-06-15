# Blueprint vs bindings, what lives where, and why

This project splits venue config into **two files** that travel separately.
Read this once before you deploy to a new site; nothing else in the docs
makes sense without the distinction.

## The two files

```
┌─────────────────────────────┐        ┌────────────────────────────────┐
│ blueprint                   │        │ bindings (per-venue, secret)   │
│ ───────────                 │        │ ──────────────────────────     │
│ rooms, walls, openings,     │  + ──▶ │ id → BSSID(s),                 │
│ anchor id + x/y/z + tech,   │        │ tx_power, path_loss_n,         │
│ georef (lat/lon)            │        │ algorithm, smoothing tunables, │
│                             │        │ per-AP calibration overrides,  │
│                             │        │ calibration samples            │
│ portable, geometry only     │        │ rotates with hardware,         │
│ committable? **only the     │        │ never committed                │
│ placeholder is**            │        │                                │
└─────────────────────────────┘        └────────────────────────────────┘
        │                                       │  (read AND write:
        │                                       │   calibration writes
        ▼                                       ▼   back here)
┌────────────────────────────────────────────────────────────────────────┐
│ wifi-positioning service                                               │
│ joins blueprint + bindings on anchor `id` at startup,                  │
│ exposes the standard `GET /measurement/{device_id}` adapter contract,  │
│ exposes calibration tool that persists samples + per-AP params         │
└────────────────────────────────────────────────────────────────────────┘
```

## Why the split

| Concern                       | Blueprint         | Bindings              |
| ----------------------------- | ----------------- | --------------------- |
| Stable per building?          | yes               | no, changes with AP swap |
| Sensitive (real MACs / SSIDs)?| no                | yes                   |
| Same across clusters?         | yes               | no (each cluster has its own APs) |
| Authored where?               | placement-editor  | hand-edited on the cluster |
| Committed to git?             | only placeholder  | **never** (always `*.local.json`) |

Keeping them together (the legacy `wifi-config.json` shape with positions
inline) means a real BSSID is one careless `git add` away from being
public, and that moving the blueprint between sites requires editing
positions twice. We don't.

## Where each file lives

| File                                        | Owner                | Mounted into                                      |
| ------------------------------------------- | -------------------- | ------------------------------------------------- |
| `services/positioning-demo/public/layout.json` (gitignored working copy) | placement-editor | placement-editor, positioning-demo, mock-positioning, wifi-positioning, positioning-engine |
| `services/positioning-demo/public/layout.example.json` (committed template) | repo          | bootstrapped into `layout.json` by `make demo` on first run |
| `dev/wifi-config.json` (placeholder)        | repo                 | wifi-positioning (legacy / demo)                  |
| `dev/wifi-config.local.json` (real venue)   | operator             | wifi-positioning (auto-mounted by `make demo` when present; gitignored) |

The blueprint file in `services/positioning-demo/public/layout.json` is the
canonical name in the dev stack. It is **gitignored**: the editor auto-saves
your real venue (floor-plan imagery, building georef, anchor positions) into
it, and none of that belongs in the repository. The committed
`layout.example.json` carries a generic demo venue so a fresh clone runs.
On a real cluster, both files come from a ConfigMap or PVC; the placement
editor writes the blueprint back to the same PVC, so the loop closes:

```
edit anchors in editor  ──▶  blueprint on PVC  ──▶  wifi-positioning rebuilds AP map
                                              └──▶  positioning-engine reads gps_origin
                                              └──▶  positioning-demo renders the scene
```

Each consumer reads only what it needs from the one blueprint:

| Consumer            | Reads from the blueprint                                   |
|---------------------|------------------------------------------------------------|
| wifi-positioning    | WiFi anchor positions (`rooms[].anchors`, joined to BSSIDs) |
| positioning-engine  | `floor_plans[0].georef` as `gps_origin` for the WGS84 conversion (set `LAYOUT_PATH`; falls back to the legacy `FLOOR_PLAN_PATH`) |
| mock-positioning    | room bounds + walls for the synthetic walker               |
| positioning-demo    | full geometry (rooms, walls, anchors) for the 3D scene     |

The `rest-adapter` is the exception: it does **not** read the blueprint. A
vendor cloud returns positioned WGS84 fixes that the adapter passes through.
The editor's `↻ sync vendor` imports those positions into the blueprint at
authoring time, but the adapter never consumes it at runtime.

Wiring this in the cluster: mount the same blueprint PVC (or a ConfigMap
rendered from it) into positioning-engine and set `LAYOUT_PATH` to it, exactly
as wifi-positioning already does. Do not leave the engine on the generic
`floor-plan.json` ConfigMap, or it will report positions against a 20x30 box
instead of the authored venue.

## Authoring flow

### 1. Author the blueprint in the placement editor

Open the editor (`make demo`, then http://localhost:3003). Walk the three
steps:

1. **World**: pin the building on the map, calibrate scale + rotation.
2. **Plan**: draw the rooms inside the floor plan.
3. **Room**: drop anchors (`+ UWB`, `+ WiFi`, …), draw inner walls,
   set ceiling height + per-wall openings.

The editor auto-saves to `services/positioning-demo/public/layout.json` after
every committed action. No manual save needed in the dev stack.

### 2. Export the blueprint (when you need to move it)

Header → `↓ export`. Downloads `blueprint-<timestamp>.json`. This is the
**portable** file. It contains geometry only.

Move it onto the target cluster by:

- copying into the PVC the wifi-positioning ConfigMap reads from,
- or replacing `services/positioning-demo/public/layout.json` on the dev host,
- or sharing it with another operator (no BSSIDs in it).

### 3. Import a blueprint into a fresh editor

Header → `↑ import`. Pick the JSON. The current layout is pushed to undo
(so `Ctrl+Z` recovers it) and the imported blueprint replaces it.

### 4. Wire BSSIDs on the cluster

Once the blueprint is in place, the operator on the cluster edits the
**bindings file** (`dev/wifi-config.local.json` in the dev stack; a
mounted secret/ConfigMap in production) and lists the real BSSIDs per
anchor `id`. Example minimal bindings file:

```json
{
  "tx_power": -42,
  "path_loss_n": 2.7,
  "algorithm": "trilateration",
  "smoothing": true,
  "process_noise": 1.0,
  "bindings": [
    { "id": "AP07", "bssids": ["AA:BB:CC:01:02:03"] },
    { "id": "AP08", "bssids": ["AA:BB:CC:01:02:04"] },
    { "id": "AP09", "bssids": ["AA:BB:CC:01:02:05"] },
    { "id": "AP10", "bssids": ["AA:BB:CC:01:02:06"] }
  ]
}
```

The `id` here MUST match an anchor id in the blueprint with
`technology: "wifi"`. Mismatches are logged at startup and skipped:
unbound anchors don't position; unmatched bindings don't pollute the
adapter.

Restart `wifi-positioning` to pick up changes (or roll the deployment in
production). The calibration tool described below hot-reloads the live
config on apply, so an in-flight calibration session does not need a
restart.

### 5. Calibrate WiFi path-loss per AP

Generic `tx_power` and `path_loss_n` give RSSI multilateration accuracy
in the ten-metre range. Per-AP values fitted from a short survey bring
that down to three to five metres on a typical office floor. The
calibration tool lives in the placement editor (section 3, button `↹
calibrate`) and drives a guided survey:

1. Walk to a known point. Click on the canvas where you are standing.
2. The adapter collects ten raw scans from the device (no extra setup;
   the existing `/ingest/wifi-scan` stream is captured into the active
   session).
3. Repeat at 8 to 12 points distributed across the room. Each AP needs
   at least three points at different distances; one point under each
   AP plus a few mid-room points is usually enough.
4. Press `⚙ derive`. The tool fits the log-distance model per AP and
   shows `tx_power`, `path_loss_n`, R², and the sample count.
5. Press `✓ apply`. The derived parameters are written back to the
   bindings file under each binding, and the live config is reloaded in
   place. Next scan uses the new model.

Samples auto-persist after every capture (and after every delete or
clear), written to the same bindings file under `calibration_samples`.
They survive container restarts without needing apply. Apply itself
writes both the samples and the per-binding overrides; revisiting the
calibration tool later picks the survey back up from where you left it.

The bindings file goes from read-only to read-write because of this
flow. On a single-host docker compose the bind-mount must allow writes;
on Kubernetes the volume must be a writable PVC, not a ConfigMap or
Secret. See **Deploying to Kubernetes** below.

## What the wifi-positioning service does at startup

```
LAYOUT_PATH set + readable?
   ├── yes ──▶ load blueprint, extract `rooms[0].anchors`
   │            where `technology == "wifi"` (id, x, y),
   │           load bindings file (id → bssids),
   │           join on id → WifiConfig.routers
   │
   └── no  ──▶ legacy mode: bindings file MUST carry positions inline
                 (`routers: [{id, x, y, bssids}]`). Used by tests and
                 single-file demos.
```

See [`services/wifi-positioning/app/assemble.py`](../services/wifi-positioning/app/assemble.py)
for the exact code.

## Deploying to Kubernetes

The bindings file is **read-write** at runtime. The calibration tool
appends samples after every capture and rewrites per-AP overrides on
apply. ConfigMaps and Secrets are mounted read-only by Kubernetes; they
cannot host the bindings file as-is. You need a writable volume.

Recommended layout on the cluster:

```
PVC: positioning-blueprint            (RWO, ~1 MB)
  └─ /app/config/layout.json          (geometry; shared with placement-editor)

PVC: wifi-positioning-bindings        (RWO, ~5 MB)
  └─ /app/config/wifi-config.json     (BSSIDs, tunables, calibration data)
```

The **bindings** PVC is mounted only by wifi-positioning, so `ReadWriteOnce`
is enough.

The **blueprint** PVC has more than one reader: placement-editor mounts it
read-write (it writes the file), while positioning-engine, positioning-demo,
mock-positioning and wifi-positioning mount it read-only. RWO allows multiple
pods only when they are co-scheduled on the same node. On a single-node
testbed that holds; if the blueprint consumers can land on different nodes,
use `ReadWriteMany` (NFS, Longhorn, etc.) for the blueprint PVC. The bindings
PVC stays RWO regardless.

Mount it read-only everywhere except placement-editor:

| Service             | Blueprint mount | Env                                      |
|---------------------|-----------------|------------------------------------------|
| placement-editor    | read-write      | `LAYOUT_FILE=/app/data/layout.json`      |
| positioning-engine  | read-only       | `LAYOUT_PATH=/app/config/layout.json`    |
| wifi-positioning    | read-only       | `LAYOUT_PATH=/app/config/layout.json`    |
| mock-positioning    | read-only       | `LAYOUT_PATH=/app/data/layout.json`      |
| positioning-demo    | read-only       | mounted into nginx html as `/layout.json` (the SPA fetches it over HTTP) |

The engine consuming the blueprint replaces its generic `floor-plan.json`
ConfigMap: keep that ConfigMap only as the fallback for a cluster that has not
provisioned the blueprint PVC yet.

Pod-side, the container's user must be able to write the volume. The
`wifi-positioning` Dockerfile runs as the `app` user (uid 1001). The
`securityContext` block below gives that uid ownership of the mounted
volume via `fsGroup`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: wifi-positioning
spec:
  replicas: 1
  template:
    spec:
      securityContext:
        fsGroup: 1001
      containers:
        - name: wifi-positioning
          image: ghcr.io/jacobbista/5g-northbound/wifi-positioning:<tag>
          env:
            - { name: WIFI_CONFIG_PATH, value: /app/config/wifi-config.json }
            - { name: LAYOUT_PATH,      value: /app/config/layout.json }
          securityContext:
            runAsUser: 1001
            runAsGroup: 1001
          volumeMounts:
            - { name: bindings,  mountPath: /app/config/wifi-config.json, subPath: wifi-config.json }
            - { name: blueprint, mountPath: /app/config/layout.json,      subPath: layout.json }
      volumes:
        - name: bindings
          persistentVolumeClaim:
            claimName: wifi-positioning-bindings
        - name: blueprint
          persistentVolumeClaim:
            claimName: positioning-blueprint
```

`fsGroup` retags every file on the mounted volume with group 1001 and
rw permission. Without it the bind to the container's non-root user
fails the same way it does on docker compose without `HOST_UID`.

### Seeding the volumes

PVCs start empty. The bindings PVC needs initial content (tunables plus
the `id → BSSIDs` map for the venue) before the operator can calibrate.
Two patterns work:

- **`kubectl cp` on first install** (simplest):

  ```bash
  # 1. Start the deployment so the pod runs and the PVCs are bound.
  kubectl -n positioning apply -f wifi-positioning.yaml

  # 2. Copy the seed files into the running pod.
  POD=$(kubectl -n positioning get pod -l app=wifi-positioning -o name | head -1)
  kubectl -n positioning cp ./wifi-config.local.json $POD:/app/config/wifi-config.json
  kubectl -n positioning cp ./exported-blueprint.json $POD:/app/config/layout.json

  # 3. Restart the pod so it picks up the seeded files.
  kubectl -n positioning rollout restart deployment wifi-positioning
  ```

- **Init container** (one-shot, idempotent, fits GitOps): runs before
  the main container, checks whether `/app/config/wifi-config.json`
  exists on the PVC, and copies a seed payload from a Secret if not.
  More moving parts; pick this when you operate more than one venue.

The placement editor can also write the blueprint PVC directly (its
`PUT /api/layout` endpoint persists to the same path). On the cluster,
mount the same PVC into both pods.

### What about the `HOST_UID` trick on docker compose?

The compose stack works around the same ownership problem in dev by
passing the host user's uid:gid into the wifi-positioning container
(`make demo` sets `HOST_UID` automatically). The Kubernetes equivalent
is `fsGroup` above. Same idea, different machinery.

## What the placeholder blueprint in the repo is for

`services/positioning-demo/public/layout.json` ships with a generic test layout
so `make demo` works on a fresh clone. **Do not commit your real venue
to that file.** Either:

- keep your real blueprint outside the repo (download via `↓ export`,
  store on a personal drive), or
- maintain it on the PVC and treat the repo's copy as a sample.

If a real BSSID ever ends up in `dev/wifi-config.json` (committed) or
in the blueprint, treat it as a leak and rotate the AP.

## UWB / vendor sync (alternative to manual placement)

WiFi APs are positioned by the operator inside the editor. For UWB and
other vendor-managed anchors the cloud usually already knows the
positions (the vendor's deployment app puts them on a map). The editor
can pull that list via the `↻ sync vendor` toolbar button in section 3:

1. The button drives the placement editor's `/api/vendor/discover`
   proxy, which calls the rest-adapter's `GET /discover`.
2. The active schema's optional `discover` block tells the rest-adapter
   how to walk the vendor's list endpoint (path, pagination, field
   mapping). No code change to support a new vendor; only a new schema.
3. The right-rail panel lists every device, projects its cloud lat/lon
   into the room frame using the blueprint's `gps_origin`, and shows
   ghost markers on the canvas at the proposed positions. Drift against
   any existing editor anchor with the same `vendor_device_id` is
   surfaced as a coloured pill.
4. `↓ import` (per device) or `↓ import all` upserts anchors with
   `technology` matching the vendor (e.g. `"wittra"`), keyed by
   `vendor_device_id`. Re-syncs update positions without creating
   duplicates.

The full schema + workflow is in [`integrating-a-vendor-rest-api.md`](./integrating-a-vendor-rest-api.md#optional-discover-block-vendor-sync-in-the-placement-editor).

## Cheat sheet

- **Move config to a new cluster** → export blueprint, copy to cluster,
  wire bindings there.
- **Demo on a laptop without the cluster** → blueprint is enough;
  bindings get the placeholder file; mock devices walk the room.
- **Swap an AP** → only the bindings file changes; blueprint stays.
- **Renovate the building** → blueprint changes; bindings only update
  if anchor IDs change.
- **Share the layout with a colleague** → send the exported blueprint;
  never the bindings.
- **Calibrate WiFi for better accuracy** → run the placement editor's
  `↹ calibrate` tool; samples and per-AP overrides land in the bindings
  file automatically.
- **Add UWB anchors from the vendor cloud** → run the placement editor's
  `↻ sync vendor` tool; cloud devices appear as purple ghost markers and
  one click drops them at the cloud-reported position.
- **Deploy to Kubernetes** → bindings on a writable PVC, not a
  ConfigMap; set `fsGroup: 1001` so the container can write. Seed via
  `kubectl cp` on first install.
