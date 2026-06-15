# Documentation

This index groups the docs by what you are trying to do. Pick the path that matches your task and follow it top to bottom. Each page links forward to the next page in its path, and back to this index.

## Paths

### 1. I just cloned this and want to understand what it is

1. [`architecture.md`](architecture.md). One screen of diagrams: services, request flow, adapter routing, coordinate frames.
2. [`../CLAUDE.md`](../CLAUDE.md). Repository conventions: Python and FastAPI style, test rules, frontend rules, security constraints.

After these two you can read any other doc without surprise.

### 2. I want to run the stack on my laptop

1. [`../README.md`](../README.md) Quick start (you are reading the index, the root README has the `make demo` flow). The full stack runs in `docker compose`. No cluster needed.
2. [`../README.md#configuration`](../README.md#configuration) explains where the three env layers live (compose env, frontend `env-config.js`, vendor `.env`) and points at `make env-check` for discovering which variables each service expects.

### 3. I want to deploy to a Kubernetes cluster

1. [`deployment.md`](deployment.md). Image set, CI/CD flow, the [step-by-step testbed deployment walkthrough](deployment.md#deploying-to-the-testbed), per-service environment variables, ConfigMap and Secret shapes, health probes.
2. [`blueprint-vs-bindings.md`](blueprint-vs-bindings.md). How venue config splits into a portable blueprint (geometry, committable placeholder) and a per-venue bindings file (BSSIDs and MACs, never committed).

The manifests themselves live in the companion repository [`kelt`](https://github.com/Jacobbista/kelt). This repo defines the contract those manifests consume.

### 4. I want to add a positioning source

1. [`adapters.md`](adapters.md). The HTTP contract every adapter implements, the engine wiring, a minimal Python skeleton.
2. If your source is a vendor with a REST API, read [`integrating-a-vendor-rest-api.md`](integrating-a-vendor-rest-api.md) before writing code. The schema-driven `rest-adapter` may already cover your case.
3. [`adapter-registry.md`](adapter-registry.md). How adapters self-register with the engine, heartbeat, and surface `live` / `unreachable` / `stale` - the model that makes adapters edge-deployable.

### 5. I want to deploy the WiFi edge scanner to a Raspberry Pi

1. [`../edge/wifi-scanner/README.md`](../edge/wifi-scanner/README.md). Files in the scanner package, runtime environment variables, and the `deploy.sh` one-shot installer that ssh-deploys `scanner.py`, `scanner.service`, and `/etc/positioning-scanner.env` to the Pi.
2. [`blueprint-vs-bindings.md`](blueprint-vs-bindings.md). The Pi pushes scans with real BSSIDs. The matching `id -> BSSIDs` mapping lives in the bindings file. If your scans come back as `422 no known access points`, the bindings file is the place to fix it.

The whole flow is restart-on-change. Edit `.env` in `edge/wifi-scanner/`, run `./deploy.sh`, watch `journalctl -u scanner -f` on the Pi.

### 6. I want to author the building layout (rooms, walls, anchors)

1. Open the placement editor at `http://localhost:3003` while `make demo` is running.
2. [`blueprint-vs-bindings.md`](blueprint-vs-bindings.md). The four-step authoring flow and how the blueprint moves between editor, demo, and cluster.
3. [`georeferencing.md`](georeferencing.md). How the local metric frame anchors to the world: datum subtleties, tile-provider registration drift, the N-point calibration workflow with residuals, and the `calibrated_against` provenance fields. Read this before comparing coordinates against a vendor cloud or another map.

### 7. I am building a CAMARA client (or another consumer)

1. [`data-contracts.md`](data-contracts.md). Exact wire formats: CAMARA northbound endpoints, vendor extensions, engine REST, adapter contract, device registry, floor plan, placement-editor API, SMF session info.
2. [`api-reference.md`](api-reference.md). One row per endpoint across every service. Quick lookup once you know the data contracts.

### 8. I want to change how positions get fused

1. [`fusion-strategies.md`](fusion-strategies.md). Candidate fusion algorithms (weighted average, Kalman, outlier rejection, gating), selection environment variables, test plan, implementation shape.

## File map

| File                                                       | What it covers                                                                                                                |
|------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| [`architecture.md`](architecture.md)                       | System overview, topology, sequence, routing diagrams. 3GPP-to-CAMARA mapping. Coordinate frame and the frame-conversion path |
| [`api-reference.md`](api-reference.md)                     | One row per endpoint across every service                                                                                     |
| [`data-contracts.md`](data-contracts.md)                   | Exact wire formats                                                                                                            |
| [`blueprint-vs-bindings.md`](blueprint-vs-bindings.md)     | Venue config: portable blueprint plus per-venue bindings                                                                      |
| [`georeferencing.md`](georeferencing.md)                   | Local metric frame ↔ world anchoring: datums, tile drift, N-point calibration, provenance fields                              |
| [`adapter-registry.md`](adapter-registry.md)               | Adapter self-registration, heartbeat/TTL, engine-as-authority, live/unreachable/stale                                          |
| [`adapters.md`](adapters.md)                               | Writing a positioning adapter                                                                                                 |
| [`integrating-a-vendor-rest-api.md`](integrating-a-vendor-rest-api.md) | Wrapping a vendor REST API with the schema-driven `rest-adapter`                                                              |
| [`fusion-strategies.md`](fusion-strategies.md)             | Fusion algorithms and how to switch between them                                                                              |
| [`deployment.md`](deployment.md)                           | Images, environment variables, ConfigMap and Secret shapes, health probes                                                     |
| [`../edge/wifi-scanner/README.md`](../edge/wifi-scanner/README.md) | Deploying the Raspberry Pi WiFi scanner to a device                                                                           |

## Conventions

The docs follow these rules so they stay readable:

- One job per file. If two files cover the same topic, the second one links to the first instead of repeating it.
- Plain language. No jargon when a normal word fits. No buzzwords that do not add information.
- Every cross-reference is a real link, never a vague pointer.
- The root [`README.md`](../README.md) is the entry point; this file is the map; every other doc is a leaf.
