# Machine-readable contracts

Every contract this stack publishes is a versioned file, fetchable over HTTP two
ways. Both take the same repo-relative `<path>` (the table below).

**Fetch the latest - GitHub Pages CDN** (no rate limit, works from anywhere):

```
https://jacobbista.github.io/5g-northbound/<path>
# e.g. https://jacobbista.github.io/5g-northbound/schema/hop-log.schema.json
```

**Pin an immutable version - raw at a release tag:**

```
https://raw.githubusercontent.com/Jacobbista/5g-northbound/<tag>/<path>
# e.g. https://raw.githubusercontent.com/Jacobbista/5g-northbound/v0.9.0/spec/private-profile/generated/location-retrieval.profiled.yaml
```

Prefer Pages to fetch; pin a tag via raw when you integrate (the contract may
evolve). `raw.githubusercontent.com` rate-limits anonymous requests, so behind a
shared egress IP use Pages or an authenticated request. The
`github.com/.../blob/...` link is an HTML page, never the file.

**Fetch from a running gateway - self-describing at runtime:**

```
GET https://<gateway>/contracts                 # index of the baked contracts
GET https://<gateway>/contracts/<name>          # one contract, e.g. device-diagnostics.schema.json
```

The gateway bakes the consumer-facing contracts into its image and serves them
with no auth, so an integrator reads them from the gateway it already talks to,
pinned to the deployed image, with no external fetch. This is authoritative for a
live integration (it matches the running behaviour); Pages and raw are the public
mirror for anyone without a running gateway. Each service also serves its env
contract this way at `GET /contract`. See
[self-describing contracts](superpowers/specs/2026-09-03-self-describing-contracts-design.md).

## Who governs which surface

Not every contract here answers to the same authority. Establish which of these
a field belongs to before changing its name.

**1. CAMARA surfaces.** The request and response bodies of
`POST /location-retrieval/v0.5/retrieve` and `/location-verification/v3/verify`,
the error envelope, paths and query parameters, and the fields the profile
overlays add inside those bodies. Governed by the pinned DeviceLocation r3.2
documents and by
[CAMARA Commonalities](https://github.com/camaraproject/Commonalities/blob/main/documentation/CAMARA-API-Design-Guide.md),
which makes lowerCamelCase mandatory for JSON properties and kebab-case for
paths.

**2. Everything else this project names.** The extension endpoints published
beside CAMARA (`/assets*`, `/anchors/calibration`, `/capabilities`, `/adapters`,
`/device-diagnostics/v0/{assetId}`, `/positions/stream`), the core diagnostics
vocabulary, and the contracts between this stack's own services (the adapter
contract `GET /measurement/{id}`, the engine contract `GET /position/{id}`, the
adapter registry, `/devices`, `/discover`, `/diagnostics`). No standard governs
any of them: Commonalities mandates a convention for CAMARA-defined attributes
and is silent on added ones. The project therefore declares one, below, and
applies it to all of them. The reason is not that outsiders read them; it is
that a name carrying its own unit is a worse name wherever it appears, and two
conventions inside one stack cost a translation layer that buys nothing.

**3. Operator documents and data at rest.** The Asset Identity Map, the venue
blueprint, the WiFi bindings, the vendor schema, the env contracts.
Configuration, not APIs. A key rename here is a data migration of ConfigMaps and
volumes. Each document keeps its own convention and must be coherent with itself
and with anything it references: the vendor schema follows the vocabulary
because its diagnostics mapping keys must match a core name exactly, while the
blueprint references nothing and is left alone. Two documents carry a second
authority as well, because the same shape is also a request or response body:
the asset map is the body of `GET/PUT /assets`, the blueprint of the engine's
`GET/PUT /blueprint`.

**4. Foreign data carried without interpretation.** The contents of the
`vendorSpecific` bag, and the keys an operator invents inside their own
document: the `pathVars` names substituted into their own path template, and any
non-core diagnostics mapping name. Nothing here interprets them, so no
convention applies and they are carried as authored.

**Anchoring is not spelling.** Binding a field to an external standard fixes its
*definition*. The core vocabulary says `battery` means what OMA LwM2M defines at
object 3, resource 9: integer, percent, 0 to 100. LwM2M identifies that resource
by numeric id and labels it "Battery Level"; it defines no JSON field name, so
`battery` is this project's name for a borrowed definition. The pointer to the
source lives in the `standard` field of
`spec/private-profile/diagnostics-vocabulary.json`.

### The convention

- **Field names are lowerCamelCase.** `assetId`, `positioningId`,
  `lastCommunicationTime`, `observedAt`.
- **The name states the quantity, not the unit.** `accuracy`, not `accuracy_m`.
  CAMARA does the same with `radius` ("Distance from the center in meters").
- **The unit is declared, not implied.** `x-unit` on the schema property, with
  the prose in `description`. OpenAPI and JSON Schema have no unit facility and
  `format` describes the type, so without this the unit survives only as prose a
  generator drops. Pydantic models carry it through
  `json_schema_extra={"x-unit": "m"}`, so it reaches each service's
  `/openapi.json`.

```yaml
accuracy:
  type: number
  format: double
  x-unit: m
  description: Horizontal 1-sigma uncertainty radius.
```

  Where the unit is not conventional for the quantity, the declaration is what
  carries it: `txPowerRef` with `x-unit: dBm`. A quantity with no unit takes a
  name that says so: `pathLossExponent`, since the `n` was a symbol.

**One surface crosses over gradually.** `POST /ingest/wifi-scan` takes its
identifier as `positioningId` and still accepts the superseded `device_id`. Its
client is the scanner running on edge hardware, outside the images this
repository builds and outside a deploy window, so it cannot be moved in step
with the services. A scan that uses the old name is served, and the response
carries a `warning` naming the replacement. The adapter already knows which
device sent the scan, so it reports the fact per device on `GET /devices` as
`supersededIngestField`, and logs it once per device rather than once per scan.
The old name is removed once no device reports it.

## The contracts

Take each `<path>` and prefix it with a base above.

| Contract | `<path>` | Governed by | What |
|----------|----------|------|------|
| CAMARA base - retrieval | `services/camara-gateway/spec/location-retrieval.yaml` | CAMARA | Pinned upstream OpenAPI (do not edit) |
| CAMARA base - verification | `services/camara-gateway/spec/location-verification.yaml` | CAMARA | Pinned upstream OpenAPI |
| Profile overlay - retrieval | `spec/private-profile/overlay-retrieval.yaml` | CAMARA | OpenAPI Overlay delta (assetId, source/altitude) |
| Profile overlay - verification | `spec/private-profile/overlay-verification.yaml` | CAMARA | OpenAPI Overlay delta |
| **Profiled spec - retrieval** | `spec/private-profile/generated/location-retrieval.profiled.yaml` | CAMARA | Base + overlay applied; **the pinnable self-contained contract** |
| **Profiled spec - verification** | `spec/private-profile/generated/location-verification.profiled.yaml` | CAMARA | Base + overlay applied |
| Streaming (AsyncAPI) | `spec/private-profile/asyncapi-stream.yaml` | this project | `/positions/stream` channel + message |
| Asset map schema | `schema/asset.schema.json` | this project + operator data | Asset Identity Map entries (`GET/PUT /assets`); an asset binds ≥1 positioning capability, fused |
| Blueprint schema | `schema/layout.schema.json` | operator data | Venue geometry (`layout.json`) |
| Hop-log schema | `schema/hop-log.schema.json` | this project | Per-hop latency log line ([latency-instrumentation.md](latency-instrumentation.md)) |
| Device diagnostics (OpenAPI) | `spec/private-profile/device-diagnostics.yaml` | this project | `GET /device-diagnostics/v0/{assetId}` extension resource ([profile-extensions.md](profile-extensions.md)) |
| Device diagnostics schema | `schema/device-diagnostics.schema.json` | this project | Diagnostics payload (motion, link quality, accuracy provenance) |
| Profile extensions (OpenAPI) | `spec/private-profile/extensions.yaml` | this project | Management + extension endpoints: `/assets`, `/assets/discoverable`, `/assets/{id}/details`, `/anchors/calibration` |

Per-service **env contracts** (`services/<svc>/env.contract.yaml`) and **adapter
contracts** (`services/<svc>/adapter.contract.yaml`) follow the same pattern. The
env contract is served live, as JSON, at each service's `GET /contract`, and that
endpoint is the authoritative one: the committed YAML is its build-time source.

On the vendor-adapter the response has two halves. The variables the binary
itself reads come from the YAML. The variables the VENDOR needs are named by the
active schema, so they are derived from it at request time - this image is
generic and holds no vendor's names. The same response carries `configured`,
`vendor` and `schema_source` (`none` / `mounted` / `runtime`), so a caller can
tell an unbound instance from a bound one, and `mapping.unmapped`, which lists
the mapping fields this binary supports that the loaded document does not map.

The vendor-adapter additionally serves `GET /contract/schema` (JSON Schema of
the operator-authored vendor document). That is adapter config, not a profile
contract: it is not listed in the table above and is not baked into the gateway
image.
