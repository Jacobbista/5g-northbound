# API reference

Every HTTP route of every service, as the running code declares it. The
bodies are in [data contracts](data-contracts.md), the semantics in the page
each row links to. Each FastAPI service serves its OpenAPI document on
`/openapi.json` and an interactive view on `/docs`.

| Service | Local port (`make demo`) |
|---------|--------------------------|
| camara-gateway | 8087 |
| positioning-engine | 8081 |
| wifi-adapter | 8089 |
| synthetic-adapter | 8090 |
| mock-vendor | 8091 |
| vendor-adapter | 8092 |
| location-app | 3002 |
| placement-editor | 3003 |

## camara-gateway

Access: **none**, a token with the `camara-location-read` role (**read**), or
such a token without an `org` claim (**operator**). A read token with an `org`
claim sees only that organisation's assets
([profile, authorisation](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/README.md#4-authorisation-2-legged-organisation-scoped)).

| Route | Access | Content |
|-------|--------|---------|
| `GET /health` | none | liveness |
| `GET /contract` | none | the environment contract |
| `GET /contracts`, `GET /contracts/{name}` | none | the published contract files ([contracts](contracts.md)) |
| `POST /location-retrieval/v0.5/retrieve` | read | CAMARA Location Retrieval |
| `POST /location-verification/v3/verify` | read | CAMARA Location Verification |
| `WS /positions/stream` | read | the position stream. The token travels as the subprotocol `bearer.jwt, <jwt>` |
| `GET /assets` | read | the asset map ([asset registry](asset-registry.md)) |
| `PUT /assets` | operator | replace the asset map |
| `GET /assets/discoverable` | operator | devices not yet onboarded |
| `GET /assets/{assetId}/details` | read | the asset with its fused position, strategy and sources |
| `PUT`, `DELETE /assets/{assetId}/placement` | read | place or remove a synthetic asset ([adapters](adapters.md#placement)) |
| `GET /device-diagnostics/v0/{assetId}` | read | device telemetry ([profile extensions](profile-extensions.md)) |
| `GET /capabilities` | read | what the deployment can do now |
| `GET /adapters` | read | name, state and declared capabilities of each adapter |
| `GET /anchors/calibration` | read | fitted WiFi parameters per anchor, without BSSIDs |
| `GET /blueprint` | read | the venue blueprint, read-only |

Errors use the CAMARA envelope `{status, code, message}`, and every response
carries an `x-correlator` header. The stream closes with `4401` on a missing or
invalid token and `1011` when the engine is unavailable.

## positioning-engine

Reachable only inside the cluster, without authentication.

| Route | Content |
|-------|---------|
| `GET /health`, `GET /contract` | liveness, environment contract |
| `GET /position/{positioningId}?source=` | the fused position of one positioning id, in WGS84. `404` without a fix, `503` without a georeference |
| `WS /ws/positions` | the broadcast the gateway turns into `/positions/stream` |
| `GET`, `PUT /blueprint` | the venue blueprint ([blueprint and bindings](blueprint-vs-bindings.md)) |
| `GET /adapters` | the registry with health and counters |
| `POST /adapters`, `DELETE /adapters/{name}` | register or heartbeat, deregister ([adapter registry](adapter-registry.md)) |
| `GET /devices` | the device lists of the adapters that advertise `devices` |

## Adapters

Every adapter serves the adapter contract ([adapters](adapters.md)):

| Route | Content |
|-------|---------|
| `GET /health` | liveness |
| `GET /ready` | readiness, `503` with the reason |
| `GET /contract` | the environment contract |
| `GET /measurement/{positioningId}` | one measurement, `404` without a fix |
| `GET /devices` | the devices the source knows, with the `devices` capability |

Routes beyond the contract:

| Adapter | Route | Content |
|---------|-------|---------|
| wifi-adapter | `POST /ingest/wifi-scan` | a scan from an edge scanner |
| wifi-adapter | `GET`, `PUT /bindings` | the bindings, BSSIDs included |
| wifi-adapter | `POST /calibration/capture`, `GET`/`DELETE /calibration/capture/{id}`, `GET /calibration/state`, `DELETE /calibration/samples`, `DELETE /calibration/samples/{id}`, `POST /calibration/derive`, `POST /calibration/apply` | the calibration survey ([calibration](blueprint-vs-bindings.md#calibration)) |
| wifi-adapter | `GET /calibration/params` | fitted parameters per anchor, without BSSIDs |
| vendor-adapter | `GET`, `PUT /schema` | the vendor schema ([integrating a vendor REST API](integrating-a-vendor-rest-api.md)) |
| vendor-adapter | `GET /contract/schema` | the JSON Schema of the vendor schema document |
| vendor-adapter | `GET /discover` | the vendor's device list, `?raw=1` for the records as received |
| vendor-adapter | `GET /diagnostics/{positioningId}` | device telemetry, with the `diagnostics` capability |
| synthetic-adapter | `PUT`, `DELETE /devices/{positioningId}/placement` | place or remove a synthetic device |

mock-vendor answers `GET /health` and, on any other path, the vendor API its
schema describes ([mock-vendor](https://github.com/Jacobbista/5g-northbound/blob/main/mocks/mock-vendor/README.md)).

## placement-editor

Behind the operator's access gate. The routes under `/api` forward to the
service named ([placement-editor](https://github.com/Jacobbista/5g-northbound/blob/main/services/placement-editor/README.md)).

| Route | Forwards to |
|-------|-------------|
| `GET /health`, `GET /contract` | liveness, environment contract |
| `GET`, `PUT /api/layout` | positioning-engine `/blueprint` |
| `GET`, `POST`, `PUT`, `DELETE /api/wifi/calibration/{path}` | wifi-adapter `/calibration/{path}` |
| `GET`, `PUT /api/wifi/bindings` | wifi-adapter `/bindings` |
| `GET /api/vendor/discover`, `GET /api/vendor/schema` | vendor-adapter `/discover`, `/schema` |
| `GET /api/capabilities` | positioning-engine `/adapters` |
| `GET /env-config.js` | runtime frontend settings |

## location-app

nginx serves the application, `GET /contract` (the environment contract,
written at build) and `GET /env-config.js`.
