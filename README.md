# 5G Northbound: CAMARA location for private assets

[![Tests](https://github.com/Jacobbista/5g-northbound/actions/workflows/test.yml/badge.svg)](https://github.com/Jacobbista/5g-northbound/actions/workflows/test.yml) [![Checks](https://github.com/Jacobbista/5g-northbound/actions/workflows/checks.yml/badge.svg)](https://github.com/Jacobbista/5g-northbound/actions/workflows/checks.yml) [![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE) [![companion: KELT](https://img.shields.io/badge/companion-KELT-24292f.svg)](https://github.com/Jacobbista/kelt)

[![CAMARA Device Location](https://img.shields.io/badge/CAMARA%20Device%20Location-r3.2-1f6feb.svg)](services/camara-gateway/spec/) [![OpenAPI Overlay](https://img.shields.io/badge/OpenAPI-Overlay%201.0-6ba539.svg)](spec/private-profile/) [![AsyncAPI](https://img.shields.io/badge/AsyncAPI-3.0-e6417a.svg)](spec/private-profile/asyncapi-stream.yaml)

An open-source reference implementation of a
**[private-asset profile](spec/private-profile/README.md)** of the
[CAMARA Device Location API](https://camaraproject.org/), for private
industrial 5G networks that track assets, such as tools, pallets and
forklifts, instead of cellular subscribers.

Positions come from sources the venue runs (WiFi, UWB, a vendor's positioning
cloud), are fused at the edge, and are served through the CAMARA retrieval,
verification and streaming interfaces. The stack implements the position
paper *Private Networks, Public APIs: Exposing Hybrid Positioning through
CAMARA in Industrial 6G* (RISE, 6GHYPE4Ind). The companion repository
[`kelt`](https://github.com/Jacobbista/kelt) provides the private 5G testbed,
the identity provider and the Kubernetes deployment.

## The profile

The profile changes CAMARA Device Location in six places. The contract and its
reasoning are in [`spec/private-profile/README.md`](spec/private-profile/README.md).

| Point | Change |
|-------|--------|
| Identity | `assetId` identifies the device. A phone number or IP address is refused with `422 UNSUPPORTED_IDENTIFIER`. |
| Delivery | A position stream (`/positions/stream`) beside `retrieve`. |
| Authorisation | Two-legged tokens scoped by organisation: the venue owns the network, the assets and the applications, so there is no end-user consent. |
| Dimension | `altitude` and `verticalAccuracy` when a source measures height, and `horizontalAccuracy` below CAMARA's 1 m radius floor. |
| Provenance | `source` and `kind`: the technology and the asset class behind a position. |
| Time | `lastLocationTime` is the latest time the position is known to hold, from each source's declared reporting model. `maxAge` is judged on it. |

The gateway implements the rest of the r3.2 contract unchanged: `maxSurface`,
verification results and the CAMARA error codes.

## Running it

```bash
make demo    # builds and starts the stack with docker compose
make         # lists the other targets
```

| Service | URL | |
|---------|-----|---|
| `camara-gateway` | http://localhost:8087 | CAMARA API |
| `location-app` | http://localhost:3002 | browser application, log in as `testuser` / `testpass` |
| `placement-editor` | http://localhost:3003 | venue editor |
| `positioning-engine` | http://localhost:8081 | REST and WebSocket |
| `wifi-adapter` | http://localhost:8089 | |
| `synthetic-adapter` | http://localhost:8090 | |
| `vendor-adapter` | http://localhost:8092 | bound to the Wittra example schema |
| `mock-vendor` | http://localhost:8091 | stands in for the Wittra cloud |
| Keycloak | http://localhost:8180 | `admin` / `changeme`, realm `5g-testbed` |

Keycloak imports the realm on first start, which takes about 30 s. The gateway
validates tokens by default. `SKIP_AUTH=true make demo` turns that off for a
local run.

Four assets are seeded from [`dev/assets.json`](dev/assets.json):

| Asset | Source | Behaviour in the demo |
|-------|--------|------------------------|
| `pkg-4471` | `wittra`, through `vendor-adapter` and `mock-vendor` | moves from the start |
| `robot-2` | `wifi` and `wittra` | located by its `wittra` capability, fused with `wifi` when scans arrive |
| `forklift-7` | `synthetic` | walks once placed on the plan in the location-app |
| `tool-880` | `wifi` | located once a WiFi scan is posted for `wifi-asset-01` |

```bash
TOKEN=$(make -s token)
curl -s -X POST http://localhost:8087/location-retrieval/v0.5/retrieve \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"device":{"assetId":"pkg-4471"}}' | jq
```

`make token` returns an operator token, which sees every organisation. A
consumer client such as `camara-api-demo` carries an `org` claim and sees only
that organisation's assets.

## Tests

`make test` runs every service's suite, the cross-service contract tests and
the profile freshness check, then prints one summary. No suite needs the stack
running. `make smoke` calls `retrieve` against a running stack.

## Documentation

[`docs/`](docs/README.md) is the documentation, published at
https://jacobbista.github.io/5g-northbound/. Start with the
[overview](docs/overview.md). [`STRUCTURE.md`](STRUCTURE.md) maps the
repository, and [`AGENTS.md`](AGENTS.md) holds the conventions for
contributors.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). The CAMARA
OpenAPI documents under `services/camara-gateway/spec/` are Apache 2.0 from the
[CAMARA Project](https://camaraproject.org/).
