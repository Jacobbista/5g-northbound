# Repository structure

What each folder holds. How the system works is in [`docs/`](docs/), the
conventions for contributors in [`AGENTS.md`](AGENTS.md).

## Services

Each folder under `services/` builds one image,
`ghcr.io/jacobbista/5g-northbound/<service>`, and holds its `Dockerfile`, its
tests and its `env.contract.yaml`. Names follow `<flavor>-<role>`
([naming](AGENTS.md#component-naming-and-roles)).

| Folder | Role |
|--------|------|
| `services/camara-gateway/` | the CAMARA API, the asset map, authorisation. `spec/` holds the pinned CAMARA base specifications |
| `services/positioning-engine/` | per positioning id: routing to the adapter, placement in the venue, fusion, conversion to WGS84. Holds the blueprint and the adapter registry |
| `services/wifi-adapter/` | position from WiFi scans posted by edge devices |
| `services/vendor-adapter/` | position from a vendor cloud, configured by a schema |
| `services/synthetic-adapter/` | synthetic walking devices for demonstrations |
| `services/placement-editor/` | operator tool for the blueprint and the WiFi calibration |
| `services/location-app/` | browser application consuming the CAMARA API |

## Other code

| Folder | Content |
|--------|---------|
| `mocks/mock-vendor/` | a vendor cloud stand-in driven by the vendor-adapter's schema, built only by `make demo` |
| `edge/wifi-scanner/` | the scanner that runs on an edge device and posts WiFi scans to wifi-adapter |
| `deploy/compose/` | the local stack started by `make demo`: the services above, mock-vendor and Keycloak |
| `deploy/k8s/` | the namespace and an example manifest |
| `deploy/contracts/` | the environment contract format and the generated sensitivity manifest |
| `deploy/tools/` | contract checks, schema export, profile overlay, test runner |

## Contracts and data

| Folder | Content |
|--------|---------|
| `spec/private-profile/` | the private-asset profile: OpenAPI overlays on the CAMARA base, the extensions, the stream AsyncAPI, the vocabularies, and the generated profiled specifications |
| `schema/` | JSON Schemas of the asset map, the blueprint, the adapter wire format, the engine position, the diagnostics and the hop log, with examples |
| `dev/` | placeholder fixtures for the local stack: assets, WiFi bindings, Keycloak realm |
| `docs/` | the documentation, published with MkDocs |

## Root files

| File | Content |
|------|---------|
| `Makefile` | `make demo`, `make test` and the other commands (`make help`) |
| `AGENTS.md` | conventions for contributors and coding agents. `CLAUDE.md` points to it |
| `mkdocs.yml` | the documentation site |
| `LICENSE`, `NOTICE` | licence and attributions |
