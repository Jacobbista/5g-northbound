# Deployment

This repository produces container images and exposes a deployment contract (environment variables, ConfigMap shape, port numbers, health probes). The companion repository `kelt` consumes that contract through Ansible roles that render Kubernetes manifests. This document covers the producer side.

## Images

Seven images are built and published by CI on every `v*` tag:

| Image                                                              | Source path                                    | Default port |
|--------------------------------------------------------------------|------------------------------------------------|--------------|
| `ghcr.io/jacobbista/5g-northbound/camara-gateway:<tag>`            | [`services/camara-gateway/`](https://github.com/Jacobbista/5g-northbound/tree/main/services/camara-gateway/)        | 8080         |
| `ghcr.io/jacobbista/5g-northbound/positioning-engine:<tag>`        | [`services/positioning-engine/`](https://github.com/Jacobbista/5g-northbound/tree/main/services/positioning-engine/)| 8080         |
| `ghcr.io/jacobbista/5g-northbound/wifi-positioning:<tag>`          | [`services/wifi-positioning/`](https://github.com/Jacobbista/5g-northbound/tree/main/services/wifi-positioning/)    | 8080         |
| `ghcr.io/jacobbista/5g-northbound/placement-editor:<tag>`          | [`services/placement-editor/`](https://github.com/Jacobbista/5g-northbound/tree/main/services/placement-editor/)    | 8080         |
| `ghcr.io/jacobbista/5g-northbound/positioning-demo:<tag>`          | [`services/positioning-demo/`](https://github.com/Jacobbista/5g-northbound/tree/main/services/positioning-demo/)    | 80           |
| `ghcr.io/jacobbista/5g-northbound/rest-adapter:<tag>`              | [`services/rest-adapter/`](https://github.com/Jacobbista/5g-northbound/tree/main/services/rest-adapter/)            | 8080         |
| `ghcr.io/jacobbista/5g-northbound/mock-positioning:<tag>`          | [`mocks/mock-positioning/`](https://github.com/Jacobbista/5g-northbound/tree/main/mocks/mock-positioning/)    | 8080         |

`mock-positioning` is published because a synthetic walking adapter is useful in the testbed for a demo device with no real hardware. `mock-wittra` is **not** published: it is a local fake of the Wittra cloud used only by `make demo` (compose builds it from source); in the testbed `rest-adapter` points at the real vendor cloud.

Each tag publishes three references: the semver tag (`0.1.0`), `latest`, and a short-SHA tag (`sha-abcdef0`).

The Python services share a common Dockerfile pattern: multi-stage `python:3.11-slim`, non-root user, no shell entry point, `uvicorn` as PID 1. The demo image is `node:20-alpine` → `nginx:alpine` and serves a Vite-built bundle with a runtime configuration file (`env-config.js`) mounted from a ConfigMap and served `Cache-Control: no-cache`.

GitHub Packages defaults each new package to private. They must be flipped to **Public** once per package, via *Repo → Packages → \<pkg\> → Package settings → Change visibility*. `GITHUB_TOKEN` cannot change visibility; this is a one-time manual step.

## CI

[`.github/workflows/test.yml`](https://github.com/Jacobbista/5g-northbound/blob/main/.github/workflows/test.yml) runs the Python and JavaScript test suites on every push and pull request. [`.github/workflows/build.yml`](https://github.com/Jacobbista/5g-northbound/blob/main/.github/workflows/build.yml) builds and pushes the seven published images on `v*` tags. Both use a matrix over services; a failure in one service does not block the others.

To cut a release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

On the first release each ghcr package is created private. Flip every package to **Public** once (Repo, Packages, the package, Package settings, Change visibility); `GITHUB_TOKEN` cannot do this.

## Configuration mechanism (single, by convention)

Every service in this repository takes its configuration through exactly one
input: **pod environment variables**. There is no second mechanism, and a
deploy tool can treat all services identically:

- Non-sensitive variables (a contract entry with `sensitive: false`) go in a
  **ConfigMap**; sensitive ones in a **Secret**. Both are wired to the pod with
  `envFrom`. The `sensitive` flag on each `/contract` entry is the only thing
  that decides which.
- **Frontends are not an exception.** `positioning-demo` and `placement-editor`
  run in the browser and cannot read pod env vars directly, so their image's
  `entrypoint.sh` renders the same env vars into `env-config.js`
  (`window.__ENV__`) at container start. The *source* is still pod env vars;
  the file is an internal materialisation step, invisible to the deployer.
- **Apply is uniform:** write the operator's answers into the service's
  ConfigMap + Secret, then `kubectl rollout restart`. The frontend entrypoint
  re-renders `env-config.js` on the restart. Same path for every service.

**Anti-pattern, do not do this:** mounting `env-config.js` directly from a
ConfigMap as a file. That predates the entrypoint and creates a second,
divergent config path for the frontends. Always supply env vars via `envFrom`
and let the entrypoint render the file. (In local `docker compose` the file is
bind-mounted for hot-editing convenience; that is a dev affordance, not the
cluster pattern.)

The worked example [`deploy/k8s/examples/placement-editor.yaml`](https://github.com/Jacobbista/5g-northbound/blob/main/deploy/k8s/examples/placement-editor.yaml)
follows this exactly: `envFrom` a ConfigMap + a Secret, no file-mounted
`env-config.js`. Copy it; do not reintroduce the file mount.

## Deploying to the testbed

End-to-end path from a green build to running pods. The manifests live in the companion repository; this section is the producer-side checklist.

**1. Read what each service needs.** Every service declares its environment surface in `env.contract.yaml` next to its code. Inspect them without leaving the repo:

```bash
make env-check                                       # required vars per service + where each is set
python3 deploy/tools/contracts.py validate -v        # full per-var breakdown
python3 deploy/tools/contracts.py render-k8s <svc>   # ConfigMap + Secret skeleton with <FILL> sentinels
```

`sensitive: true` in a contract means the value belongs in a `Secret`; `false` means a `ConfigMap`. `runtime_layer: window.__ENV__` flags a browser variable that the container's `entrypoint.sh` renders into `env-config.js` at start, so it is still supplied as a normal pod env var.

**2. Copy the manifest pattern.** [`deploy/k8s/examples/placement-editor.yaml`](https://github.com/Jacobbista/5g-northbound/blob/main/deploy/k8s/examples/placement-editor.yaml) is a complete worked example: ConfigMap + Secret + Deployment (`envFrom` both, `fsGroup` for the writable PVC) + PVC + Service. Replicate it per service, filling values from that service's contract. The per-variable tables below add the cross-service context (which URL points where) that does not fit a contract field.

**3. Carry the data that never enters the repo.** These are gitignored locally and become cluster resources:

| Artifact                    | Local source                              | Cluster resource                                  |
|-----------------------------|-------------------------------------------|---------------------------------------------------|
| Blueprint (geometry)        | editor `↓ export`                         | PVC shared by placement-editor + engine + demo    |
| Bindings (BSSIDs, calib.)   | `dev/wifi-config.local.json`              | writable PVC on wifi-positioning                  |
| Vendor credentials          | `services/rest-adapter/.env`              | `Secret` (names come from the active vendor schema) |
| Mapbox token                | editor `env-config.js`                    | `Secret`, injected as `VITE_MAPBOX_TOKEN`          |
| Asset Identity Map          | `dev/assets.json`                         | **PVC** (`ASSET_STORE_FILE`) seeded from `ASSET_SEED_FILE` |
| Engine floor-plan georef    | `dev/floor-plan.json`                     | `ConfigMap` (`FLOOR_PLAN_PATH`)                   |

The blueprint/bindings split and its cluster mounts are detailed in [`blueprint-vs-bindings.md`](blueprint-vs-bindings.md); the georef workflow, if you re-calibrate for a new venue, in [`georeferencing.md`](georeferencing.md).

**4. Rotate secrets without a rebuild.** Edit the `Secret`, then `kubectl rollout restart`. Frontend containers regenerate `env-config.js` from env vars at start, so a restart is enough; no image rebuild.

## Environment variables

Every service ships an authoritative declaration of its environment surface
next to its code as `env.contract.yaml` (required vs optional, sensitive flag,
default, description, runtime layer). The tables below mirror those contracts
and add the cross-service context that does not fit a YAML field - but if a
value disagrees, the contract is the source of truth.

Discover them locally:

```bash
make env-check                                       # what each service needs and where to set it
python3 deploy/tools/contracts.py validate -v        # full per-var breakdown
python3 deploy/tools/contracts.py render-k8s <svc>   # preview a ConfigMap + Secret pair
```

### camara-gateway

| Variable                  | Default                                                | Notes |
|---------------------------|--------------------------------------------------------|-------|
| `KEYCLOAK_URL`            | `http://keycloak.iam.svc.cluster.local:8080`           | Full base URL including any path prefix |
| `KEYCLOAK_REALM`          | `5g-testbed`                                           | |
| `REQUIRED_ROLE`           | `camara-location-read`                                 | Realm role required to call CAMARA endpoints |
| `POSITIONING_ENGINE_URL`  | empty (mock fallback)                                  | Engine base URL; gateway calls `GET /position/{positioning_id}?source=` |
| `WIFI_POSITIONING_URL`    | empty                                                  | wifi-positioning base URL, proxied by `/anchors/calibration` so the demo reads real per-AP RF. Empty disables that extension |
| `ASSET_STORE_FILE`        | `/app/data/assets.json`                                | **Writable** Asset Identity Map store. Back it with a **PVC** (not a read-only ConfigMap) so `PUT /assets` survives restart/upgrade. Content is tenant inventory (Tier-1): never committed |
| `ASSET_SEED_FILE`         | `/app/config/assets.seed.json`                         | Read-only seed copied into the store once on first boot when it is empty. Conforms to `schema/asset.schema.json` |
| `SKIP_AUTH`               | `false`                                                | Development override only, bypasses JWT validation for every endpoint except `/health` |

The gateway also exposes **vendor-extension** endpoints used by the demo UI (not part of CAMARA): `GET /assets`, `GET /assets/{assetId}/details`, `GET /capabilities`, `GET /anchors/calibration`. Auth and error envelope are identical to the CAMARA routes, and all are `org`-scoped. See [`data-contracts.md`](data-contracts.md#vendor-extensions-on-the-gateway).

### positioning-engine

| Variable                | Default                              | Notes |
|-------------------------|--------------------------------------|-------|
| `ADAPTER_URLS`          | empty                                | Comma-separated `name=url` entries (e.g. `wifi=http://wifi-positioning:8080,mock=http://mock-positioning:8080`). A bare URL is accepted as a back-compat shortcut and gets an auto-generated name. Empty → no measurements produced |
| `DEVICE_MAP`            | empty                                | Optional cold-start override: comma-separated `positioning_id=adapter_name` pins. Routing prefers the asset's `source` (adapter whose `ADAPTER_NAME` matches); `DEVICE_MAP` is only consulted when `source` is unset or matches nothing; unlisted ids then fan out to every adapter and are fused. Normally unset |
| `FUSION_STRATEGY`       | `weighted_avg`                       | Name of the primary fusion strategy (see [`fusion-strategies.md`](fusion-strategies.md)) |
| `FUSION_COMPARE`        | empty                                | Optional comma-separated strategies whose outputs are surfaced under `fusions` for side-by-side rendering. Demo / research feature; leave empty in production |
| `FLOOR_PLAN_PATH`       | `/app/config/floor-plan.json`        | Mounted from `positioning-floor-plan` ConfigMap |
| `WEBSOCKET_INTERVAL_MS` | `500`                                | Cadence of the WebSocket position broadcast |
| `DEVICE_IDS`            | `uwb-tag-001`                        | Comma-separated devices broadcast on the WebSocket |
| `ADAPTER_<NAME>_API_KEY` | _unset_                             | Outbound credential for the adapter named `<NAME>` in `ADAPTER_URLS` (uppercased, non-alphanumerics → `_`). Mount from a `Secret`. Sent on every `GET /measurement/{device_id}`. See [`adapters.md`](adapters.md#outbound-api-key-engine-external-adapter) |
| `ADAPTER_<NAME>_API_KEY_HEADER` | `X-API-Key`                  | Header name carrying the token above. Use `Authorization` for bearer-style auth (value must include the `Bearer ` prefix) |
| `ADAPTER_<NAME>_TIMEOUT` | `1.0`                               | Per-adapter HTTPX timeout in seconds. Raise for high-latency cloud backends |

### wifi-positioning

| Variable           | Default                          | Notes |
|--------------------|----------------------------------|-------|
| `WIFI_CONFIG_PATH` | `/app/config/wifi-config.json`   | Path to the per-venue **bindings** file: tunables (`tx_power`, `path_loss_n`, `algorithm`, smoothing), the `id → BSSIDs` map, the persistent `calibration_samples`, and per-AP overrides. In docker compose, mounted from `dev/wifi-config.json` (or `dev/wifi-config.local.json` when present). In Kubernetes, mounted from a writable PVC because the calibration tool writes samples and overrides back at runtime. See [`blueprint-vs-bindings.md`](blueprint-vs-bindings.md#deploying-to-kubernetes). |
| `LAYOUT_PATH`      | unset                            | Optional path to the placement-editor **blueprint** JSON. When set, anchor positions are taken from `rooms[0].anchors` (where `technology == "wifi"`) and joined to the bindings file by anchor `id`. Unset → legacy mode where the bindings file must carry positions inline. See [`blueprint-vs-bindings.md`](blueprint-vs-bindings.md). |

The split into blueprint + bindings is a deliberate architectural choice: blueprints are portable across clusters and never contain secrets, bindings are per-venue and never committed. Skim [`blueprint-vs-bindings.md`](blueprint-vs-bindings.md) before configuring a real venue.

### mock-positioning

Synthetic random-walk adapter. No external configuration file; bounds and motion parameters come from environment variables. Implements the same adapter contract as `wifi-positioning`, so the engine treats them uniformly.

| Variable      | Default | Notes |
|---------------|---------|-------|
| `SOURCE`      | `mock`  | Tag set on every measurement (surfaces in `sources[]` northbound) |
| `WIDTH_M`     | `20.0`  | Room width along x (metres); positions are clamped to `[0, WIDTH_M]` |
| `DEPTH_M`     | `30.0`  | Room depth along z |
| `HEIGHT_M`    | `3.0`   | Room height along y |
| `STEP_M`      | `0.3`   | Random-walk step per poll (metres). Larger values produce more visible motion in the demo |
| `ACCURACY_M`  | `1.5`   | Fixed accuracy reported on every measurement |
| `CONFIDENCE`  | `0.6`   | Fixed confidence reported on every measurement |
| `RNG_SEED`    | `0`     | Set non-zero for reproducible trajectories in tests / recordings |

### rest-adapter

Generic, schema-driven translator from a vendor REST positioning API onto the engine's adapter contract. One pod per vendor; the schema is loaded at runtime through `PUT /schema` (see [`integrating-a-vendor-rest-api.md`](integrating-a-vendor-rest-api.md)).

| Variable        | Default                       | Notes |
|-----------------|-------------------------------|-------|
| `SCHEMA_FILE`   | `/app/data/schema.json`       | Persistent path for the loaded schema. Mount a PVC here; the testbed dashboard writes through `PUT /schema` |

Vendor-specific env vars (base URL override, credentials, path-template parameters) are referenced *by name* from inside the schema, so the adapter pod needs `WITTRA_API_KEY`, `WITTRA_ORG_ID`, etc. (or your vendor's equivalents) mounted from a Kubernetes `Secret`. The schema itself contains no credentials and is safe to keep in plain text / a `ConfigMap`.

### mock-wittra

Toy fake of the Wittra cloud REST API. Demo / CI only, never deployed alongside the real adapter.

| Variable                 | Default      | Notes                                  |
|--------------------------|--------------|----------------------------------------|
| `MOCK_WITTRA_ORG_ID`     | `demo-org`   | Expected Basic-auth username           |
| `MOCK_WITTRA_API_KEY`    | `demo-key`   | Expected Basic-auth password           |
| `MOCK_WITTRA_PROJECT_ID` | `demo-prj`   | Required project segment in the URL    |

### placement-editor

| Variable      | Default                       | Notes |
|---------------|-------------------------------|-------|
| `LAYOUT_FILE` | `/app/data/layout.json`       | Path the editor reads from and writes to. Mount the same artefact (volume / ConfigMap-backed PVC) on the engine and demo so changes flow through |

The editor's drag-drop UI is not implemented yet (`v0.0.1` is a scaffold). The HTTP surface is stable: `GET /api/layout`, `PUT /api/layout`, `GET /health`. Auth is not wired in for the scaffold, production deployments MUST front it with a Keycloak-protected ingress and the realm role `placement-admin` until the service grows its own JWT middleware (planned).

### positioning-demo

Runtime configuration is injected through `/usr/share/nginx/html/env-config.js`, served `Cache-Control: no-cache`. The image's `entrypoint.sh` regenerates this file from container env vars at every pod start, so a Secret / ConfigMap update only needs a `kubectl rollout restart`. The image build itself does not bake any of these values in.

Full variable list (names, required vs optional, sensitivity, defaults) lives in [`../services/positioning-demo/env.contract.yaml`](https://github.com/Jacobbista/5g-northbound/blob/main/services/positioning-demo/env.contract.yaml). Edit the contract, not this section, when adding a variable; the deploy portal reads the contract to render the operator form.

## Health probes

Every service exposes `GET /health` returning `200 {"status": "ok"}` with no authentication. Use it for both `readinessProbe` and `livenessProbe`. Initial delays should account for the startup work: floor plan loading, JWKS fetch, AP map parsing.

## Registering an asset

Assets live in the gateway's **Asset Identity Map**, a writable JSON store the gateway is the authority for (`GET/PUT /assets`). Unlike the old device registry, it is mutated at runtime, not edited-and-restarted.

### Entry shape

```json
{
  "asset_id":       "pkg-4471",
  "positioning_id": "wittra-tag-01",
  "source":         "wittra",
  "kind":           "pallet",
  "org":            "fiskarheden",
  "label":          "Timber bundle 01"
}
```

Full field reference and the schema (`schema/asset.schema.json`) are in [`data-contracts.md`](data-contracts.md#asset-identity-map). The two contracts that must hold: `positioning_id` == the vendor-native device id, and `source` == the adapter's `ADAPTER_NAME`.

### How it is consumed

| Environment | Source                                                                                  |
|-------------|------------------------------------------------------------------------------------------|
| compose     | [`dev/assets.json`](https://github.com/Jacobbista/5g-northbound/blob/main/dev/assets.json) seed → persisted to the writable store on first boot |
| Kubernetes  | `ASSET_SEED_FILE` (ConfigMap) seeds a **PVC** at `ASSET_STORE_FILE` once; thereafter the store is the source of truth |

Register or update an asset at runtime with `PUT /assets` (the placement-editor proxies it via `/api/assets`), no restart. The demo discovers the tenant's assets via `GET /assets`. Because the store is a PVC, runtime changes survive restart and upgrade.

## Adding a new adapter to a running cluster

1. Deploy the adapter (Deployment + ClusterIP Service) in the same namespace as the engine. Adapters that contain vendor code or NDA material ship as private images with an `imagePullSecret`.
2. Append the adapter's Service URL to the engine's `ADAPTER_URLS` (edit the engine ConfigMap or environment).
3. Restart the engine pod to pick up the new list. The engine reads `ADAPTER_URLS` at startup; a `checksum/config` annotation on the engine Deployment automates the rolling restart on ConfigMap change.

The adapter contract is documented in full in [`adapters.md`](adapters.md).

## Local development

The host-level quick start (`docker compose up --build`, port table, CAMARA call example) lives in the top-level [README](https://github.com/Jacobbista/5g-northbound/blob/main/README.md). This document covers the producer-side contract: images, environment variables, ConfigMap shape, health probes. Anything that differs between *what the image expects* and *how a local compose run wires it up* is intentional, the compose file is one consumer of this contract; Kubernetes is the other.
