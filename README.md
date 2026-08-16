# 5G Northbound - CAMARA private-asset location

[![Tests](https://github.com/Jacobbista/5g-northbound/actions/workflows/test.yml/badge.svg)](https://github.com/Jacobbista/5g-northbound/actions/workflows/test.yml) [![Checks](https://github.com/Jacobbista/5g-northbound/actions/workflows/checks.yml/badge.svg)](https://github.com/Jacobbista/5g-northbound/actions/workflows/checks.yml) [![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE) [![companion: KELT](https://img.shields.io/badge/companion-KELT-24292f.svg)](https://github.com/Jacobbista/kelt)

[![CAMARA Device Location](https://img.shields.io/badge/CAMARA%20Device%20Location-r3.2-1f6feb.svg)](services/camara-gateway/spec/) [![OpenAPI Overlay](https://img.shields.io/badge/OpenAPI-Overlay%201.0-6ba539.svg)](spec/private-profile/) [![AsyncAPI](https://img.shields.io/badge/AsyncAPI-3.0-e6417a.svg)](spec/private-profile/asyncapi-stream.yaml)

Open-source reference implementation of a **[private-asset profile](spec/private-profile/README.md)** of the [CAMARA Device Location API](https://camaraproject.org/), for private industrial 5G networks that track **assets** - tools, pallets, forklifts - rather than cellular subscribers.

CAMARA was designed for public networks, where the operator both produces the fix and arbitrates who the device is and who may ask. A factory owns the network, the assets, and the applications, and its assets carry no phone number. This stack keeps the CAMARA surface and bridges that mismatch: non-3GPP sources (WiFi, UWB, vendor RTLS) are fused at the edge and served through the standard retrieval, verification, and streaming interfaces. It is the engineering realisation of the position paper *"Private Networks, Public APIs: Exposing Hybrid Positioning through CAMARA in Industrial 6G"* (RISE, 6GHYPE4Ind), and the companion of the testbed repository [`kelt`](https://github.com/Jacobbista/kelt), which provides the private 5G network and the IAM.

## The profile

The full contract and its rationale live in [`spec/private-profile/README.md`](spec/private-profile/README.md). In short, it extends stock CAMARA Device Location at five points:

| Point | What the profile does |
|-------|-----------------------|
| **Identity** | `assetId` is first-class; a public identifier (`phoneNumber`, IP) is rejected with `422 UNSUPPORTED_IDENTIFIER` |
| **Delivery** | a streaming channel (`/positions/stream`) beside the pull `retrieve` endpoint |
| **Authorisation** | 2-legged, `org`-scoped - no three-legged consent, since network, assets, and apps are one owner |
| **Dimension** | optional `altitude` + `verticalAccuracy` on the fix |
| **Provenance** | optional `source` + `kind` - the technology and asset class behind the fix |

On top of the extensions the gateway honours the base r3.2 contract fully - `maxAge` freshness, `maxSurface`, and the namespaced CAMARA error codes.

## Architecture at a glance

**Sense → fuse → expose.** Each positioning source is an **adapter** speaking one HTTP contract (`GET /measurement/{id}`). The **positioning-engine** pulls and fuses their measurements in a venue-local frame; the **camara-gateway** binds them to asset identities and exposes them over CAMARA. A new source is a new adapter - the engine and the gateway never change. The stack runs unchanged from a laptop to Kubernetes (manifests in [`kelt`](https://github.com/Jacobbista/kelt)).

See [`docs/architecture.md`](docs/architecture.md) for the request flow, adapter routing, and coordinate frames.

## Quick start

```bash
make demo    # docker compose up --build; run `make` alone for every target
```

Once running:

| Service              | URL                     | Notes                                          |
|----------------------|-------------------------|------------------------------------------------|
| `camara-gateway`     | http://localhost:8087   | CAMARA Location API (host 8080 reserved)        |
| `positioning-demo`   | http://localhost:3002   | 3D browser application (Keycloak login)         |
| `placement-editor`   | http://localhost:3003   | Operator UI + `/api/layout`                      |
| `positioning-engine` | http://localhost:8081   | Engine REST + WebSocket on `:8082`              |
| `wifi-positioning`   | http://localhost:8089   | Reference adapter (RSSI multilateration)         |
| `mock-positioning`   | http://localhost:8090   | Reference adapter (waypoint walker)              |
| `rest-adapter`       | http://localhost:8092   | Schema-driven vendor translator (Wittra demo)    |
| `mock-wittra`        | http://localhost:8091   | Demo-only fake of the Wittra cloud REST API      |
| Keycloak             | http://localhost:8180   | `admin` / `changeme`; realm `5g-testbed`         |

Keycloak imports the `5g-testbed` realm on first boot (~30 s). The gateway
enforces JWT auth by default; the browser demo logs in via Keycloak PKCE as
`testuser` / `testpass`. For a throwaway run without auth: `SKIP_AUTH=true make demo`.

### Calling the CAMARA API

```bash
# Operator token (sees every tenant). A per-consumer client (camara-api-demo)
# would instead carry an `org` claim and see only its tenant's assets.
TOKEN=$(curl -s -X POST \
  http://localhost:8180/realms/5g-testbed/protocol/openid-connect/token \
  -d "grant_type=client_credentials&client_id=camara-gateway&client_secret=changeme" \
  | jq -r .access_token)

curl -s -X POST http://localhost:8087/location-retrieval/v0.5/retrieve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device":{"assetId":"forklift-7"}}' | jq
```

The tracked entity is an **asset**, addressed by `assetId` - not a phone number.
The stack seeds three demo assets in [`dev/assets.json`](dev/assets.json) (the
first-boot seed for the Asset Identity Map, then authored over `GET/PUT /assets`):

- `forklift-7` → source `mock` (`mock-positioning`). Walks the room, no setup needed.
- `tool-880` → source `wifi` (`wifi-positioning`). **Offline** until a real WiFi scan is ingested - the expected end-to-end shape, not a bug.
- `pkg-4471` → source `wittra` (`rest-adapter` → `mock-wittra`). Moves immediately; the worked example for vendor integration.

Asset structure, authoring, seeding, and tenancy: [`docs/asset-registry.md`](docs/asset-registry.md).

## Validation

**Automated.** `make test` runs every service's suite and prints a single pass/fail roundup at the end - a failing suite dumps its output inline, and the run exits non-zero if any suite fails. No suite needs docker compose running. You can also run `pytest` (a Python service folder) or `npm test` (a frontend one) directly.

**Manual, end to end.** `make demo`, open http://localhost:3002, log in via Keycloak (`testuser` / `testpass`), and confirm the seeded assets render on the venue. `make smoke` is the backend-only check: it fetches a token and calls `retrieve` for a couple of assets.

## Documentation

The guided index is [`docs/README.md`](docs/README.md) - grouped by reader intent, starting from [`docs/overview.md`](docs/overview.md). The folder tree is mapped in [`STRUCTURE.md`](STRUCTURE.md); repository conventions (code style, tests, security) in [`CLAUDE.md`](CLAUDE.md).

## Configuration

Runtime configuration lives in the compose file (backend env), the gitignored `env-config.js` files (browser), and per-service `.env` files (vendor/edge secrets). Each service declares its surface in an `env.contract.yaml`; `make env-check` validates the running stack against them. Details: [`docs/deployment.md`](docs/deployment.md).

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) (the CAMARA OpenAPI documents vendored under `services/camara-gateway/spec/` are also Apache 2.0, from the [CAMARA Project](https://camaraproject.org/)).
