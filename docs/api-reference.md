# API reference

One-row-per-endpoint index for every HTTP route in this repository. Auth and error envelopes are documented in [`data-contracts.md`](data-contracts.md); this page is a lookup table.

Live OpenAPI docs (FastAPI):

| Service              | URL                                                |
|----------------------|----------------------------------------------------|
| `camara-gateway`     | http://localhost:8087/docs · http://localhost:8087/openapi.json |
| `positioning-engine` | http://localhost:8081/docs · http://localhost:8081/openapi.json |
| `wifi-positioning`   | http://localhost:8089/docs · http://localhost:8089/openapi.json |
| `mock-positioning`   | http://localhost:8090/docs · http://localhost:8090/openapi.json |
| `placement-editor`   | http://localhost:3003/docs · http://localhost:3003/openapi.json |

`positioning-demo` is a static SPA, no HTTP surface.

## camara-gateway

Auth: `Authorization: Bearer <jwt>` with realm role `camara-location-read` on every route except `/health`. `SKIP_AUTH=true` bypasses validation for dev only.

| Method · path                                          | Returns                      | Notes                                                                  |
|--------------------------------------------------------|------------------------------|------------------------------------------------------------------------|
| `GET    /health`                                       | `{"status":"ok"}`            | Liveness; no auth                                                      |
| `GET    /contract`                                     | env contract (JSON)          | No auth. This service's `env.contract.yaml` as JSON (schema only, sensitive values redacted). See [Conventions](#conventions-across-services) |
| `POST   /location-retrieval/v0.5/retrieve`             | `Location` (CAMARA)          | CAMARA Device Location Retrieval r3.2. `device.assetId` (private-asset profile) |
| `POST   /location-verification/v3/verify`              | `VerifyLocationResponse`     | CAMARA Device Location Verification r3.2                               |
| `GET    /assets`                                       | `{"assets":[…]}`             | **Vendor extension**: the caller's tenant assets (Asset Identity Map), `org`-filtered |
| `PUT    /assets`                                       | `{"status":"ok",…}`          | **Vendor extension**: replace the asset map (operator; conforms to `schema/asset.schema.json`) |
| `GET    /assets/{assetId}/details`                     | `{…,"telemetry":…}`          | **Vendor extension**: asset entry + engine telemetry. `telemetry: null` when offline; `404` for a missing or cross-tenant id |
| `GET    /capabilities`                                 | `{"adapters","sources","kinds"}` | **Vendor extension**: live adapter capabilities + the tenant's asset sources/kinds |
| `GET    /anchors/calibration`                          | `{"anchors":[…]}`            | **Vendor extension**: real per-AP RF (`tx_power_ref_dbm`, `path_loss_n`) proxied from wifi-positioning. No BSSIDs. Empty when `WIFI_POSITIONING_URL` unset |
| `GET    /adapters`                                     | `{"adapters":[…]}`           | **Vendor extension**: engine `/adapters` health snapshot proxied for the demo. Empty list when the engine is unreachable |
| `GET    /blueprint`                                    | blueprint JSON               | **Vendor extension**: read-only proxy of the engine's blueprint so the demo (MEC: gateway only) can render the venue. `404` when the engine has none |
| `WS     /positions/stream?token=<jwt>`                 | stream of position payloads  | **Vendor extension**: forwards the engine's `/ws/positions` broadcast to authenticated browser clients. Token is supplied as a query parameter because browsers cannot set `Authorization` on a WebSocket handshake. Closes with code 4401 on auth failure, 1011 on upstream failure |

Error envelope (all non-health routes): `{ "status": <int>, "code": <string>, "message": <string> }`.

## positioning-engine

No auth (cluster-internal). Mounts:

| Method · path                          | Returns            | Notes                                                                            |
|----------------------------------------|--------------------|----------------------------------------------------------------------------------|
| `GET    /health`                       | `{"status":"ok"}`  | Liveness                                                                         |
| `GET    /position/{positioning_id}?source=` | `EnginePosition` | Routes by `?source=` (adapter whose `ADAPTER_NAME` matches); else `DEVICE_MAP`; else fan out to all adapters + fuse. `404` when no adapter has a fix (legitimate "offline") |
| `GET    /blueprint`                     | blueprint JSON     | The engine is the blueprint authority. Returns the persisted venue blueprint (raw layout.json shape); `404` when none authored yet |
| `PUT    /blueprint`                     | `{"status":"ok",…}` | Replace + persist the blueprint, re-derive `gps_origin` live. No auth (ClusterIP, internal); write control is the placement-editor's front-door gate. See [`blueprint-vs-bindings.md`](blueprint-vs-bindings.md) |
| `GET    /adapters`                     | `{"adapters":[…]}` | Registry snapshot per adapter: `name`, `base_url`, `kind`, `registered_via`, `last_seen_s_ago`, `fail_count`, `in_cooldown`, `cooldown_seconds_remaining`, `state` (`live`/`unreachable`/`stale`). Also proxied by the gateway |
| `POST   /adapters`                     | `{"status":"ok",…}` | Self-registration / heartbeat: `{name, base_url, kind}` upsert. See [`adapter-registry.md`](adapter-registry.md) |
| `DELETE /adapters/{name}`              | `{"status":"ok",…}` | Deregister on adapter shutdown |
| `WS     /ws/positions`                 | stream of `{device_id, latitude, longitude, altitude_m, accuracy_m, timestamp}` | Broadcast loop driven by `DEVICE_IDS` and `WEBSOCKET_INTERVAL_MS`. `device_id` is the `positioning_id`; the gateway enriches it to asset shape downstream |

## Adapter contract (consumed by the engine)

Every adapter pod implements:

| Method · path                          | Returns            | Notes                                                                            |
|----------------------------------------|--------------------|----------------------------------------------------------------------------------|
| `GET    /health`                       | `{"status":"ok"}`  | Liveness                                                                         |
| `GET    /measurement/{device_id}`      | `Measurement`      | Returns one measurement in the adapter's chosen `frame` (`local` or `wgs84`); `404` if no measurement |

`wifi-positioning` also exposes:

| Method · path                          | Returns         | Notes                                                                  |
|----------------------------------------|-----------------|------------------------------------------------------------------------|
| `POST   /ingest/wifi-scan`             | `202 Accepted`  | Edge client pushes a single scan ({bssid, rssi}[]) here                |

`mock-positioning` exposes only the contract endpoints, no ingest path (data is synthesised internally).

`rest-adapter` also exposes admin endpoints for runtime schema management:

| Method · path                          | Returns                          | Notes                                                                  |
|----------------------------------------|----------------------------------|------------------------------------------------------------------------|
| `GET    /schema`                       | schema JSON                      | `404` when no schema is loaded                                         |
| `PUT    /schema`                       | `{"status":"ok","vendor":"…"}`   | Replace + persist the schema, clear the cache. See [`integrating-a-vendor-rest-api.md`](integrating-a-vendor-rest-api.md) |

`mock-wittra` is the demo-only fake Wittra cloud, not an adapter; it implements one path: `GET /v1/organizations/{org}/projects/{prj}/devices/{device_id}` returning Wittra-shaped JSON behind HTTP Basic auth.

## placement-editor

No auth wired in the scaffold (`v0.0.1`). Production: front with a Keycloak-protected ingress and the realm role `placement-admin`.

| Method · path                          | Returns                                    | Notes                                          |
|----------------------------------------|--------------------------------------------|------------------------------------------------|
| `GET    /health`                       | `{"status":"ok"}`                          | Liveness                                       |
| `GET    /api/layout`                   | blueprint JSON                             | Proxies the engine's `GET /blueprint` (the editor is a blueprint client, no local file). `404` when none authored yet |
| `PUT    /api/layout`                   | `{"status":"ok",…}`                        | Proxies the engine's `PUT /blueprint`. Unknown fields preserved verbatim |
| `GET    /`                             | placeholder HTML                           | Drag-drop UI not yet implemented               |

## Conventions across services

- All Python services: FastAPI, multi-stage `python:3.11-slim` Dockerfile, non-root user (uid 1001), `uvicorn` as PID 1 on port `8080` internally.
- Health endpoints (`/health`) are always unauthenticated and return `{"status":"ok"}` with HTTP 200. `/health` is liveness; services that load business config at startup also expose `/ready` (503 until that config loads) for the k8s readiness probe.
- The six configurable services (camara-gateway, positioning-engine, wifi-positioning, rest-adapter, placement-editor, positioning-demo) expose **`GET /contract`** (unauthenticated, no dependency on business config so it answers even on a misconfigured pod). The mocks do not. It returns the service's `env.contract.yaml` as JSON - `{service, kind, external_origin, description, env:{required, recommended, optional}}` - describing which environment variables it expects. Schema only: it never returns a runtime value, and sensitive entries drop their `default`/`example`. positioning-demo (static nginx) serves the same shape from a `contract.json` baked at build. A deploy dashboard reads `/contract` from the live pod to drive a config wizard; the **blueprint** (`layout.json`) is *not* part of the contract - that is shared venue data on a PVC, see [`blueprint-vs-bindings.md`](blueprint-vs-bindings.md).
- Schemas validate request and response bodies; unknown fields are silently dropped (`ConfigDict(extra="ignore")`) except in `placement-editor` where `extra="allow"` lets the layout schema evolve without backend changes.
- Time fields are RFC 3339 UTC strings (`...Z` suffix). Unix epoch seconds are used only on the adapter contract (`Measurement.timestamp`).
- Distances are metres, angles WGS84 decimal degrees.
