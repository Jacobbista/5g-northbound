# Repository structure

Quick orientation guide. For architecture, contracts and deployment shape see
[`docs/`](docs/); for code conventions see [`CLAUDE.md`](CLAUDE.md).

## Tier 1 - Production services (ship to the testbed)

These six folders each build one OCI image, registered as
`ghcr.io/<org>/5g-nf-platform/<service>:<tag>` by `.github/workflows/build.yml`.
Every folder contains a `Dockerfile`, a `tests/` suite, and (for Python
services) `requirements.txt` + `pyproject.toml`.

| Folder                | Image              | Role                                                              |
|-----------------------|--------------------|-------------------------------------------------------------------|
| `services/camara-gateway/`     | camara-gateway     | Northbound CAMARA REST API + JWT validation                       |
| `services/positioning-engine/` | positioning-engine | Fusion + position service, polls adapters, serves WebSocket       |
| `services/positioning-demo/`   | positioning-demo   | MEC frontend (talks to camara-gateway only)                       |
| `services/placement-editor/`   | placement-editor   | Operator UI to author the blueprint + per-vendor bindings         |
| `services/wifi-positioning/`   | wifi-positioning   | WiFi RSSI → position adapter (consumes scans from the edge agent) |
| `services/rest-adapter/`       | rest-adapter       | Schema-driven REST adapter for vendor clouds (Wittra et al.)      |

## Tier 2 - Mocks (compose-only, never in the testbed)

Stand-in services that let `docker compose up` work without real hardware or
vendor accounts. They DO build images, but those images stay local.

| Folder              | Image            | Replaces                                                |
|---------------------|------------------|---------------------------------------------------------|
| `mocks/mock-positioning/` | mock-positioning | UWB / 5G adapter when no real RTLS is connected         |
| `mocks/mock-wittra/`      | mock-wittra      | Wittra API v4 when no real Wittra org credentials exist |

## Tier 3 - Third-party in compose (public images)

Brought in directly, no folder, no build.

| Service     | Image                                    | Role                                |
|-------------|------------------------------------------|-------------------------------------|
| `keycloak`  | `quay.io/keycloak/keycloak:24.0`         | IdP for JWT issuance + introspection |
| `mock-smf`  | `python:3.11-slim` + `dev/mock_smf.py`   | Session validation stub             |

## Tier 4 - Edge / out-of-cluster

Code that runs OUTSIDE the cluster. Not a container.

| Path                              | Runtime              | Deploy mechanism                                |
|-----------------------------------|----------------------|-------------------------------------------------|
| `edge/wifi-scanner/`              | Python on Raspberry Pi | `deploy.sh` SSHes to the Pi and copies + enables a systemd unit |

## Tier 5 - Non-buildable folders (no service, no image)

| Folder              | Contents                                                              |
|---------------------|-----------------------------------------------------------------------|
| `dev/`              | Static fixtures mounted as volumes (`floor-plan.json`, `keycloak-realm.json`, `wifi-config.json`, `mock_smf.py`) |
| `docs/`             | Architecture, data contracts, adapters, deployment notes              |
| `.github/workflows/`| CI: `test.yml` runs each service's pytest matrix; `build.yml` publishes images on tag |

## Root files

| File                              | Role                                                        |
|-----------------------------------|-------------------------------------------------------------|
| `deploy/compose/docker-compose.yml` | Local dev stack - wires all ten services on one bridge net |
| `Makefile`                        | Common dev verbs (`make demo`, `make test`, etc.)           |
| `CLAUDE.md`                       | Conventions for contributors + AI assistants                |
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
   `positioning-demo` for fallback defaults that survive a container with no
   runtime `env-config.js`. Avoid for anything that varies per deploy - those
   belong in layer (1).

Per-service env contracts live in each folder as `env.contract.yaml` (see any
service folder for the exact required / optional / sensitive shape). The
intent is for a future deploy portal to discover these manifests, render a
form, and emit both compose `.env` files and k8s `Secret` + `ConfigMap`
manifests.
