# Repository structure

Quick orientation guide. For architecture, contracts and deployment shape see
[`docs/`](docs/); for code conventions see [`AGENTS.md`](AGENTS.md).

## Tier 1 - Production services (ship to the testbed)

These seven folders each build one OCI image, registered as
`ghcr.io/<org>/5g-nf-platform/<service>:<tag>` by `.github/workflows/build.yml`.
Every folder contains a `Dockerfile`, a `tests/` suite, and (for Python
services) `requirements.txt` + `pyproject.toml`. The `<flavor>-<role>` naming
convention is defined in [`AGENTS.md`](AGENTS.md#component-naming-and-roles).

| Folder                | Image              | Role                                                              |
|-----------------------|--------------------|-------------------------------------------------------------------|
| `services/camara-gateway/`     | camara-gateway     | Northbound CAMARA REST API + JWT validation                       |
| `services/positioning-engine/` | positioning-engine | Fusion + position service, polls adapters, serves WebSocket       |
| `services/location-app/`   | location-app   | MEC app: consumes the northbound CAMARA API (talks to camara-gateway only) |
| `services/placement-editor/`   | placement-editor   | Operator UI to author the blueprint + per-vendor bindings         |
| `services/wifi-adapter/`   | wifi-adapter   | WiFi RSSI → position adapter (consumes scans from the edge agent) |
| `services/vendor-adapter/`       | vendor-adapter       | Schema-driven adapter for vendor clouds (Wittra et al.)      |
| `services/synthetic-adapter/`  | synthetic-adapter  | Adapter with a synthetic source (waypoint walker); testbed demo device + contract reference |

## Tier 2 - Mocks

A test-double of an external system, so `docker compose up` works without real
vendor accounts. Not an adapter (does not speak `/measurement`); it stands in
for a source that `vendor-adapter` consumes.

| Folder              | Image            | Doubles                                                | Published to ghcr |
|---------------------|------------------|---------------------------------------------------------|-------------------|
| `mocks/mock-vendor/`      | mock-vendor      | A vendor cloud (Wittra API shape) when no real vendor credentials exist | no - local `make demo` only; compose builds it from source |

## Tier 3 - Third-party in compose (public images)

Brought in directly, no folder, no build.

| Service     | Image                                    | Role                                |
|-------------|------------------------------------------|-------------------------------------|
| `keycloak`  | `quay.io/keycloak/keycloak:24.0`         | IdP for JWT issuance (realm `5g-testbed`) |

## Tier 4 - Edge / out-of-cluster

Code that runs OUTSIDE the cluster. Not a container.

| Path                              | Runtime              | Deploy mechanism                                |
|-----------------------------------|----------------------|-------------------------------------------------|
| `edge/wifi-scanner/`              | Python on Raspberry Pi | `deploy.sh` SSHes to the Pi and copies + enables a systemd unit |

## Tier 5 - Non-buildable folders (no service, no image)

| Folder              | Contents                                                              |
|---------------------|-----------------------------------------------------------------------|
| `dev/`              | Static fixtures mounted as volumes (`floor-plan.json`, `keycloak-realm.json`, `wifi-config.json`, `assets.json`) |
| `docs/`             | Architecture, data contracts, adapters, deployment notes              |
| `spec/`             | The CAMARA private-asset profile: OpenAPI overlays + AsyncAPI over the pinned base |
| `.github/workflows/`| CI: `test.yml` runs each service's pytest matrix; `checks.yml` runs env/compose/profiled-spec/leak checks; `build.yml` publishes images on tag |

## Root files

| File                              | Role                                                        |
|-----------------------------------|-------------------------------------------------------------|
| `deploy/compose/docker-compose.yml` | Local dev stack - wires all nine services on one bridge net |
| `Makefile`                        | Common dev verbs (`make demo`, `make test`, etc.)           |
| `AGENTS.md`                       | Entry point: conventions for contributors + AI assistants   |
| `CLAUDE.md`                       | Fallback pointer to `AGENTS.md`                             |
| `README.md`                       | Project overview                                            |
| `STRUCTURE.md`                    | This file                                                   |

## Configuration model (where env vars live)

Three distinct layers; each service uses one or two of them:

1. **Runtime browser config** (`window.__ENV__` from `env-config.js`, served
   with `Cache-Control: no-cache`). Used by both frontends. In production the
   file is generated at container start by an `entrypoint.sh` from env vars,
   so a k8s `Secret` rotation requires only a pod restart.

2. **Backend env vars** (read by `pydantic-settings.BaseSettings`). Used by
   every Python service. In compose, injected via `environment:` or
   `env_file:`. In k8s, mounted from `Secret` / `ConfigMap`.

3. **Build-time Vite `.env`** (compiled into the JS bundle). Used by
   `location-app` for fallback defaults that survive a container with no
   runtime `env-config.js`. Avoid for anything that varies per deploy - those
   belong in layer (1).

Per-service env contracts live in each folder as `env.contract.yaml` (see any
service folder for the exact required / optional / sensitive shape). The
intent is for a future deploy portal to discover these manifests, render a
form, and emit both compose `.env` files and k8s `Secret` + `ConfigMap`
manifests.
