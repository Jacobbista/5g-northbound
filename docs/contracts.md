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

## The contracts

Take each `<path>` and prefix it with a base above.

| Contract | `<path>` | What |
|----------|----------|------|
| CAMARA base - retrieval | `services/camara-gateway/spec/location-retrieval.yaml` | Pinned upstream OpenAPI (do not edit) |
| CAMARA base - verification | `services/camara-gateway/spec/location-verification.yaml` | Pinned upstream OpenAPI |
| Profile overlay - retrieval | `spec/private-profile/overlay-retrieval.yaml` | OpenAPI Overlay delta (assetId, source/altitude) |
| Profile overlay - verification | `spec/private-profile/overlay-verification.yaml` | OpenAPI Overlay delta |
| **Profiled spec - retrieval** | `spec/private-profile/generated/location-retrieval.profiled.yaml` | Base + overlay applied; **the pinnable self-contained contract** |
| **Profiled spec - verification** | `spec/private-profile/generated/location-verification.profiled.yaml` | Base + overlay applied |
| Streaming (AsyncAPI) | `spec/private-profile/asyncapi-stream.yaml` | `/positions/stream` channel + message |
| Asset map schema | `schema/asset.schema.json` | Asset Identity Map entries (`GET/PUT /assets`); an asset binds ≥1 positioning capability, fused |
| Blueprint schema | `schema/layout.schema.json` | Venue geometry (`layout.json`) |
| Hop-log schema | `schema/hop-log.schema.json` | Per-hop latency log line ([latency-instrumentation.md](latency-instrumentation.md)) |
| Device diagnostics (OpenAPI) | `spec/private-profile/device-diagnostics.yaml` | `GET /device-diagnostics/v0/{assetId}` extension resource ([profile-extensions.md](profile-extensions.md)) |
| Device diagnostics schema | `schema/device-diagnostics.schema.json` | Diagnostics payload (motion, link quality, accuracy provenance) |
| Profile extensions (OpenAPI) | `spec/private-profile/extensions.yaml` | Management + extension endpoints: `/assets`, `/assets/discoverable`, `/assets/{id}/details`, `/anchors/calibration` |

Per-service **env contracts** (`services/<svc>/env.contract.yaml`) and **adapter
contracts** (`services/<svc>/adapter.contract.yaml`) follow the same pattern. The
env contract is also served live, as JSON, at each service's `GET /contract`.
The vendor-adapter additionally serves `GET /contract/schema` (JSON Schema of
the operator-authored vendor document). That is adapter config, not a profile
contract: it is not listed in the table above and is not baked into the gateway
image.
