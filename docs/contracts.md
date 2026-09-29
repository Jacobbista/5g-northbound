# Machine-readable contracts

Every contract of the stack is a versioned file in this repository. This page
lists them, says who governs each surface, and states the naming convention.

## Fetching a contract

| Source | URL | Use |
|--------|-----|-----|
| a running gateway | `GET /contracts` (index), `GET /contracts/{name}` | the contracts of the deployed image, without authentication |
| GitHub Pages | `https://jacobbista.github.io/5g-northbound/<path>` | the latest version, without rate limit |
| a release tag | `https://raw.githubusercontent.com/Jacobbista/5g-northbound/<tag>/<path>` | a fixed version to pin |

`<path>` is the repository path in the table below. The running gateway
matches the deployed behaviour. Pages and tags serve readers without a
gateway. `raw.githubusercontent.com` limits anonymous requests, and a
`github.com/.../blob/...` link returns an HTML page, not the file.

## The contracts

| Contract | `<path>` | Governed by | Served by the gateway |
|----------|----------|-------------|-----------------------|
| CAMARA retrieval, base | `services/camara-gateway/spec/location-retrieval.yaml` | CAMARA, pinned r3.2 | no |
| CAMARA verification, base | `services/camara-gateway/spec/location-verification.yaml` | CAMARA, pinned r3.2 | no |
| Profile overlays | `spec/private-profile/overlay-retrieval.yaml`, `overlay-verification.yaml` | CAMARA and this profile | no |
| **Profiled retrieval** | `spec/private-profile/generated/location-retrieval.profiled.yaml` | CAMARA and this profile | yes |
| **Profiled verification** | `spec/private-profile/generated/location-verification.profiled.yaml` | CAMARA and this profile | yes |
| Position stream (AsyncAPI) | `spec/private-profile/asyncapi-stream.yaml` | this project | yes |
| Extensions (OpenAPI) | `spec/private-profile/extensions.yaml` | this project | yes |
| Device diagnostics (OpenAPI) | `spec/private-profile/device-diagnostics.yaml` | this project | yes |
| Device diagnostics body | `schema/device-diagnostics.schema.json` | this project | yes |
| Diagnostics vocabulary | `spec/private-profile/diagnostics-vocabulary.json` | this project | yes |
| Accuracy classes | `spec/private-profile/accuracy-class-vocabulary.json` | this project | yes |
| Asset map | `schema/asset.schema.json` | this project, operator data | yes |
| Hop log line | `schema/hop-log.schema.json` | this project | yes |
| Blueprint | `schema/layout.schema.json` | operator data | no |
| Adapter measurement | `schema/adapter-measurement.schema.json` | this project | no |
| Adapter announcement | `schema/adapter-announcement.schema.json` | this project | no |
| Adapter devices | `schema/adapter-devices.schema.json` | this project | no |
| Engine position | `schema/engine-position.schema.json` | this project | no |

The profiled documents are the ones to pin: base and overlays applied, in one
file ([profile](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/README.md#formal-specification)).
The four engine schemas are generated from the engine's models by
`make contract-schemas`, and the engine's tests fail when a committed copy
differs. The gateway serves the files a CAMARA consumer integrates against,
and not the ones between internal services.

Each service also serves its environment contract on `GET /contract`
([format](https://github.com/Jacobbista/5g-northbound/blob/main/deploy/contracts/README.md)).
The vendor-adapter's answer adds the variables its loaded vendor schema names,
the schema binding (`configured`, `vendor`, `schema_source`, `transport`), the
coverage of the mapping, and the declared source behaviour with what the
payloads show against it
([integrating a vendor REST API](integrating-a-vendor-rest-api.md#declaring-how-the-source-reports)).
Its `GET /contract/schema` is the JSON Schema of the vendor schema document.

## Who governs which surface

The authority over a name differs by surface. A field is placed in one of
four kinds before its name is discussed.

1. **CAMARA surfaces.** The retrieval and verification bodies, the error
   envelope, paths, query parameters, and the fields the overlays add inside
   those bodies. Governed by the pinned CAMARA documents and by the
   [CAMARA API design guide](https://github.com/camaraproject/Commonalities/blob/main/documentation/CAMARA-API-Design-Guide.md),
   which requires lowerCamelCase properties and kebab-case paths.
2. **What this project names.** The extension endpoints, the stream, the
   diagnostics vocabulary, and the contracts between the stack's own services:
   the adapter contract, the engine position, the adapter registry,
   `/devices`, `/discover`, `/diagnostics`. No standard governs them, and the
   convention below applies.
3. **Operator documents.** The asset map, the blueprint, the WiFi bindings, the
   vendor schema, the environment contracts. A key rename here is a data
   migration. Each document keeps its own convention, consistent with itself
   and with what it references: the vendor schema follows the diagnostics
   vocabulary because its mapping keys must match core names, while the
   blueprint references nothing and keeps its snake_case keys. The asset map
   and the blueprint are also request and response bodies, of `/assets` and
   `/blueprint`.
4. **Foreign data carried as received.** The content of `vendorSpecific`, and
   the names an operator chooses inside a document: `pathVars` names and
   diagnostics mapping names outside the core. Nothing interprets them.

Tying a field to an external standard fixes its definition, not its spelling.
`battery` means what OMA LwM2M defines at object 3, resource 9. LwM2M names no
JSON field, so `battery` is this profile's name, and the vocabulary's
`standard` entry records the source. A definition this profile makes itself
says so: the accuracy classes carry a `provenance` field stating that their
boundaries are the profile's own, since omlox has no classes and 3GPP TR 38.855
sets targets for public networks.

## Naming convention

- **Field names are lowerCamelCase:** `assetId`, `positioningId`,
  `lastCommunicationTime`.
- **The name states the quantity, not the unit:** `accuracy`, not
  `accuracy_m`, as CAMARA's `radius` is in metres.
- **The unit is declared** in the schema as `x-unit`, with prose in
  `description`. The Pydantic models carry it through
  `json_schema_extra={"x-unit": "m"}` into each service's `/openapi.json`.
  A quantity without a unit is named for what it is: `pathLossExponent`.
- **Times are RFC 3339 UTC** on every surface the gateway publishes. Epoch
  seconds appear only on the internal contracts, from the adapters to the
  engine and the gateway.

```yaml
accuracy:
  type: number
  format: double
  x-unit: m
  description: Horizontal one-sigma error radius.
```

One surface renames with a transition. `POST /ingest/wifi-scan` takes
`positioningId` and still accepts the older `device_id`, since its client runs
on edge devices outside the release cycle. A scan with the old name is served
with a `warning` in the response, `GET /devices` marks the device with
`supersededIngestField`, and the adapter logs it once per device. The old name
is removed when no device reports it.
