# Repository Conventions

Conventions for contributors and AI assistants working in this repository. Architecture, data contracts, deployment shape, and the adapter contract live under [`docs/`](docs/), and the CAMARA private-asset profile under [`spec/private-profile/`](spec/private-profile/) - read those first; this file covers only how to write code that fits in cleanly.

## Layout

The repo is organised by tier (see [`STRUCTURE.md`](STRUCTURE.md) for the full map):

- `services/` - production images shipped to the testbed
- `mocks/` - compose-only test-doubles of external systems (`mock-vendor`)
- `edge/` - code that runs outside the cluster (Pi WiFi scanner)
- `deploy/` - compose stack + k8s manifests + env contracts
- `dev/`, `docs/`, `.github/` - fixtures, docs, CI

Each service folder is self-contained: its own `Dockerfile`, `requirements.txt` / `pyproject.toml`, `tests/`. Cross-service contracts cross the network, never a Python import. See [`docs/deployment.md`](docs/deployment.md) for the build and publish flow.

## Component naming and roles

Every component is named `<flavor>-<role>`. The **role** (suffix) says where it sits in the flow; the **flavor** (prefix) qualifies it. One adjective prefix, `mock-`, marks a test-double of an external system. The pipeline diagrams in [`docs/architecture.md`](docs/architecture.md) and [`docs/overview.md`](docs/overview.md) use these names.

Flow, northbound (source → app):

```
sources ─▶ adapters ─▶ engine ─▶ gateway ─▶ app
                          ▲
              editor authors the blueprint they read
```

**Roles (suffix)**

| Suffix | Role | Flow position |
|--------|------|---------------|
| `-adapter` | Speaks the adapter contract (`GET /measurement/{id}` → `Measurement`) to the engine | ingest |
| `-engine` | Fuses adapter measurements into a position | core |
| `-gateway` | Exposes the northbound CAMARA API | egress |
| `-app` | Consumes the northbound API (MEC application) | consumer |
| `-editor` | Operator authoring UI, off the runtime data path | tooling |

**Adapter flavors (prefix)**

An adapter is defined by the contract it speaks, not by where its data comes from. The prefix names the source flavor - who produces the fix:

| Name | Source | Who computes the fix |
|------|--------|----------------------|
| `wifi-adapter` | WiFi RSSI from the edge scanner | this stack (RSSI multilateration) |
| `synthetic-adapter` | generated, no hardware | this stack (waypoint walker; testbed demo device + contract reference) |
| `vendor-adapter` | an external third-party positioning system | the third party; the adapter relays their fixes |

`vendor-adapter` is the bridge to a positioning system this stack does not run: a commercial RTLS cloud, a partner service, any external source that computes its own fixes. The third party owns the positioning; the adapter relays the result. One image serves every such system; a per-vendor schema (path, auth, field mapping) selects and translates one. A new vendor is a new schema, not new code.

**Transport is a schema dimension, not a name axis**

The engine-facing contract is always pull: the engine calls `GET /measurement/{id}`. How `vendor-adapter` obtains data from its source is separate, declared in the schema:

- `rest` - the adapter pulls the vendor API on demand (pull-through).
- `mqtt` - the adapter subscribes to the vendor broker, caches the latest fix, and serves it from cache. (future transport)

A new transport is a new schema value plus a source-side handler in the same image; the component name and the engine contract do not change.

**The `mock-` prefix**

Reserved for a test-double of an external system, used in `docker compose` so the stack runs without real credentials. It is not an adapter (does not speak `/measurement`); it stands in for a source that a real adapter consumes, and lives left of the adapter line.

| Name | Doubles |
|------|---------|
| `mock-vendor` | A vendor's source. Generated from the same schema `vendor-adapter` consumes, so it mirrors that vendor's shape and transport |

## Python (FastAPI) conventions

- One router file per logical domain. No business logic in routers; delegate to a service module.
- All request and response bodies are Pydantic models with `model_config = ConfigDict(extra="ignore")`.
- Configuration from environment variables via `pydantic_settings.BaseSettings`. No hardcoded URLs, secrets, or credentials in application code. Every service declares its environment surface in `env.contract.yaml` next to the code; `make env-check` validates the running compose stack against those contracts.
- Service dependencies are injected through FastAPI `Depends(...)`. Routes do not instantiate services.
- `camara-gateway` raises `CamaraError(status, code, message)` and lets a central exception handler render the CAMARA envelope. Other services use `HTTPException` directly. Never return a 200 response with an error body.
- No comments explaining what code does. Add a short comment only when a constraint is non-obvious (e.g. why a number was chosen, why an order matters).

## Tests

- Tests live in `tests/` at the service root, not inside `app/`.
- `pytest` with `httpx.AsyncClient(ASGITransport)` for route tests; the app runs in-process. No test requires `docker compose` to be running, a live Kubernetes cluster, or any external HTTP endpoint.
- Mock external HTTP with `respx` (already a dev dependency where needed).
- CI runs each service's test suite independently in a matrix; a failure in one service does not block another's image build.

## Frontend (location-app)

- Runtime configuration is read in `src/config.js` from `window.__ENV__` first, then `import.meta.env`. The image build does not bake environment values in.
- Tests use `vitest` + `@testing-library/react`. Unit tests only - no E2E in CI.
- `nginx.conf` MUST serve `index.html` for unknown routes (SPA fallback) and serve `/env-config.js` with `Cache-Control: no-cache`.

## Constraints

- **JWT validation in `camara-gateway` is mandatory for all CAMARA endpoints.** `/health` is exempt; `SKIP_AUTH=true` is a development override only.
- The CAMARA OpenAPI documents under [`services/camara-gateway/spec/`](services/camara-gateway/spec/) are pinned to the meta-release recorded in `spec/VERSION`. Treat them as source of truth; do not hand-edit. To bump the pin: refetch from upstream at the new commit and update `VERSION`.
- The adapter contract (`GET /measurement/{device_id}` → `Measurement`) is the only stable surface between the engine and any positioning source. Changing it requires updating every adapter implementation. See [`docs/adapters.md`](docs/adapters.md).
- The engine-gateway contract (`GET /position/{device_id}` → `EnginePosition`, in WGS84) is geometry-agnostic on the gateway side. The engine owns coordinate conversion; the gateway does not project or rotate.
- Do not add `gps_origin` to the production `floor-plan.json` ConfigMap until a real GPS reference for the lab has been measured. The engine degrades gracefully (`latitude: 0, longitude: 0` with a warning) when it is absent.
- `location-app` is a MEC application - it talks to the CAMARA gateway only. It must not call the engine, Keycloak admin APIs, or any internal cluster service.
- Vendor SDKs, NDA material, and proprietary RTLS code do not enter this repository. They ship as private adapter images implementing the public HTTP contract.

## Local development quick reference

```bash
make demo                          # full stack (wraps `docker compose -f deploy/compose/docker-compose.yml up --build`)
pytest                             # per-service, from its folder under services/ or mocks/
npm test                           # in services/location-app/ or services/placement-editor/frontend/
```

Per-service environment variables and ConfigMap shape are documented in [`docs/deployment.md`](docs/deployment.md).
