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

## Five kinds of surface, five different authorities

Not every contract here answers to the same authority, and conflating them
leads to arguing about a naming convention on a surface that no standard
governs. Before changing a field name, establish which of these it belongs to.

**1. CAMARA surfaces.** The request and response bodies of
`POST /location-retrieval/v0.5/retrieve` and `/location-verification/v3/verify`,
the error envelope, paths and query parameters. Governed by the pinned
DeviceLocation r3.2 documents and by
[CAMARA Commonalities](https://github.com/camaraproject/Commonalities/blob/main/documentation/CAMARA-API-Design-Guide.md),
which makes lowerCamelCase mandatory for JSON properties, kebab-case for paths.
The profile overlays add fields *inside* these bodies (`source`, `kind`,
`altitude`, `verticalAccuracy`), so those additions answer to the same rule.

**2. Profile extension surfaces.** HTTP and WebSocket APIs this project
invented and publishes as part of the profile: `/assets`,
`/assets/discoverable`, `/assets/{id}/details`, `/anchors/calibration`,
`/capabilities`, `/adapters`, `/device-diagnostics/v0/{assetId}`, and the
`/positions/stream` channel. No CAMARA specification defines them, and
Commonalities is silent on provider extensions: it mandates a convention for
CAMARA-defined attributes and says nothing about added ones. The convention
here is therefore a choice this project makes and must state, not a rule it
inherits.

### The convention this project declares for kind 2

Since no standard governs these surfaces, the project states its own rule, and
it is the one CAMARA uses next door so a consumer meets one convention across
the profile:

- **Field names are lowerCamelCase**, matching kind 1 and the CAMARA API Design
  Guide. `assetId`, `positioningId`, `lastLocationTime`, `observedAt`.
- **The name states the quantity, not the unit.** `accuracy`, not `accuracy_m`;
  `altitude`, not `altitude_m`. CAMARA does the same with `radius` ("Distance
  from the center in meters"), and the profile overlay already adds `altitude`
  unsuffixed inside the CAMARA `Location`.
- **The unit is declared, not implied.** Carry it in an `x-unit` extension on
  the schema property, with the prose in `description`. OpenAPI and JSON Schema
  have no unit facility and `format` describes the type, so without this the
  unit survives only as prose a generator drops. This is already how
  `spec/private-profile/diagnostics-vocabulary.json` declares units, where the
  core field is `accuracy` with `"unit": "m"`.

```yaml
accuracy:
  type: number
  format: double
  x-unit: m
  description: Horizontal 1-sigma uncertainty radius.
```

  Unknown `x-` extensions are ignored by tooling, so declaring one breaks no
  consumer. Where the unit is not conventional for the quantity the declaration
  is what carries it: `txPowerRef` with `x-unit: dBm` is only safe because the
  unit is stated. A quantity with no unit at all takes a name that says so:
  `path_loss_n` becomes `pathLossExponent`, since the `n` was a symbol, not a
  unit.
- **Foreign vocabulary bags are carried verbatim.** The keys inside
  `diagnostics` and `vendorSpecific` are kind 5 and keep their source spelling, so a
  kind-2 object may contain a snake_case bag by design. That boundary is the
  one exception, and it is what makes the anchoring to LwM2M and omlox real.

### Coherence is per contract, not global uniformity

Kinds 3, 4 and 5 are not required to adopt the kind-2 convention, but each
document must be coherent with itself and with whatever it references. Two
consequences worth stating, because both were missed once:

- **A document that references the vocabulary follows the vocabulary.** The
  vendor schema is kind 4 and could stay snake_case on its own, except that its
  diagnostics mapping keys must match a core vocabulary name exactly or the
  field is demoted into the extension bag. Once those keys are camelCase the
  document's own grammar follows them, otherwise one object holds both spellings.
  The keys an operator invents inside it, the `pathVars` names substituted into
  their own path template and any non-core mapping name, stay entirely theirs.
- **A document that references nothing keeps its own convention.** The blueprint
  is kind 3 and 4, has no kind-2 twin and no vocabulary references, so it is
  coherent as it stands and is left alone. Renaming it would be uniformity for
  its own sake.

**3. Internal contracts.** Between this stack's own processes, never seen by an
API consumer: the engine's `GET /position/{positioning_id}`, the adapter
contract `GET /measurement/{positioning_id}`, the adapter registry, and each
service's `GET /contract`. Names here are implementation labels. They can change
without touching the profile, and no external standard reaches them.

**4. Data at rest and operator documents.** The Asset Identity Map, the
blueprint, the vendor schema document, the env contracts. These are
configuration, not APIs. A key rename here is a data migration of ConfigMaps and
volumes, not an API change, and is planned as such. Two of them carry a second
kind as well, because the same shape is also a request or response body: the
asset map is the body of `GET/PUT /assets` (kind 2), the blueprint of the
engine's `GET/PUT /blueprint` (kind 3). A change to either is both an API change
and a migration.

**5. Foreign data carried without interpretation.** The contents of the
`vendorSpecific` bag inside `diagnostics`: values an integrator mapped that this
profile does not define. Their keys are chosen by whoever wrote the vendor
schema, they are not comparable across vendors, and nothing here interprets
them. They are passed through as authored, so no convention applies. This is the
one exception to the rule above, and it is narrow: it covers a bag's contents,
never a field this project names.

**What kind 5 is not.** Anchoring a field to an external standard fixes its
*definition*, not its spelling. The core vocabulary says `battery` means what
OMA LwM2M defines at object 3, resource 9: integer, percent, range 0 to 100.
LwM2M identifies that resource by numeric id and labels it "Battery Level"; it
defines no JSON field name at all, so `battery` is this project's name for a
definition borrowed from elsewhere. The pointer to the source lives in the
`standard` field of `spec/private-profile/diagnostics-vocabulary.json`, which is
where a definition reference belongs. Core vocabulary names are therefore kind 2
and follow the convention below.

### The convention this project declares for kind 2

Since no standard governs these surfaces, the project states its own rule, and
it is the one CAMARA uses next door so a consumer meets one convention across
the profile:

- **Field names are lowerCamelCase**, matching kind 1 and the CAMARA API Design
  Guide. `assetId`, `positioningId`, `lastLocationTime`, `observedAt`.
- **The name states the quantity, not the unit.** `accuracy`, not `accuracy_m`;
  `altitude`, not `altitude_m`. CAMARA does the same with `radius` ("Distance
  from the center in meters"), and the profile overlay already adds `altitude`
  unsuffixed inside the CAMARA `Location`.
- **The unit is declared, not implied.** Carry it in an `x-unit` extension on
  the schema property, with the prose in `description`. OpenAPI and JSON Schema
  have no unit facility and `format` describes the type, so without this the
  unit survives only as prose a generator drops. This is already how
  `spec/private-profile/diagnostics-vocabulary.json` declares units, where the
  core field is `accuracy` with `"unit": "m"`.

```yaml
accuracy:
  type: number
  format: double
  x-unit: m
  description: Horizontal 1-sigma uncertainty radius.
```

  Unknown `x-` extensions are ignored by tooling, so declaring one breaks no
  consumer. Where the unit is not conventional for the quantity the declaration
  is what carries it: `txPowerRef` with `x-unit: dBm` is only safe because the
  unit is stated. A quantity with no unit at all takes a name that says so:
  `path_loss_n` becomes `pathLossExponent`, since the `n` was a symbol, not a
  unit.
- **Foreign vocabulary bags are carried verbatim.** The keys inside
  `diagnostics` and `vendorSpecific` are kind 5 and keep their source spelling, so a
  kind-2 object may contain a snake_case bag by design. That boundary is the
  one exception, and it is what makes the anchoring to LwM2M and omlox real.

**3. Internal contracts.** Between this stack's own processes, never seen by an
API consumer: the engine's `GET /position/{positioning_id}`, the adapter
contract `GET /measurement/{positioning_id}`, the adapter registry, and each
service's `GET /contract`. Names here are implementation labels. They can change
without touching the profile, and no external standard reaches them.

**4. Data at rest and operator documents.** The Asset Identity Map, the
blueprint, the vendor schema document, the env contracts. These are
configuration, not APIs. A key rename here is a data migration of ConfigMaps and
volumes, not an API change, and is planned as such. Two of them carry a second
kind as well, because the same shape is also a request or response body: the
asset map is the body of `GET/PUT /assets` (kind 2), the blueprint of the
engine's `GET/PUT /blueprint` (kind 3). A change to either is both an API change
and a migration.

**5. Vocabularies anchored to a foreign standard.** The keys inside
`diagnostics`: `battery` from OMA LwM2M object 3/0/9, `last_seen` from the omlox
`timestamp_generated`, `accuracy` from omlox, `moving` derived from the omlox
speed, plus the `vendorSpecific` bag. Their names come from the standard they are
anchored to, which is the entire argument for having a core vocabulary. They are
not this project's to normalise. See
[profile-extensions.md](profile-extensions.md#core-vocabulary).

## The contracts

Take each `<path>` and prefix it with a base above.

| Contract | `<path>` | Kind | What |
|----------|----------|------|------|
| CAMARA base - retrieval | `services/camara-gateway/spec/location-retrieval.yaml` | 1 | Pinned upstream OpenAPI (do not edit) |
| CAMARA base - verification | `services/camara-gateway/spec/location-verification.yaml` | 1 | Pinned upstream OpenAPI |
| Profile overlay - retrieval | `spec/private-profile/overlay-retrieval.yaml` | 1 | OpenAPI Overlay delta (assetId, source/altitude) |
| Profile overlay - verification | `spec/private-profile/overlay-verification.yaml` | 1 | OpenAPI Overlay delta |
| **Profiled spec - retrieval** | `spec/private-profile/generated/location-retrieval.profiled.yaml` | 1 | Base + overlay applied; **the pinnable self-contained contract** |
| **Profiled spec - verification** | `spec/private-profile/generated/location-verification.profiled.yaml` | 1 | Base + overlay applied |
| Streaming (AsyncAPI) | `spec/private-profile/asyncapi-stream.yaml` | 2 | `/positions/stream` channel + message |
| Asset map schema | `schema/asset.schema.json` | 2 + 4 | Asset Identity Map entries (`GET/PUT /assets`); an asset binds ≥1 positioning capability, fused |
| Blueprint schema | `schema/layout.schema.json` | 3 + 4 | Venue geometry (`layout.json`) |
| Hop-log schema | `schema/hop-log.schema.json` | 3 | Per-hop latency log line ([latency-instrumentation.md](latency-instrumentation.md)) |
| Device diagnostics (OpenAPI) | `spec/private-profile/device-diagnostics.yaml` | 2 | `GET /device-diagnostics/v0/{assetId}` extension resource ([profile-extensions.md](profile-extensions.md)) |
| Device diagnostics schema | `schema/device-diagnostics.schema.json` | 2 + 5 | Diagnostics payload (motion, link quality, accuracy provenance) |
| Profile extensions (OpenAPI) | `spec/private-profile/extensions.yaml` | 2 | Management + extension endpoints: `/assets`, `/assets/discoverable`, `/assets/{id}/details`, `/anchors/calibration` |

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
