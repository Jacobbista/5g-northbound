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
| Asset map schema | `schema/asset.schema.json` | Asset Identity Map entries (`PUT /assets`) |
| Blueprint schema | `schema/layout.schema.json` | Venue geometry (`layout.json`) |
| Hop-log schema | `schema/hop-log.schema.json` | Per-hop latency log line ([latency-instrumentation.md](latency-instrumentation.md)) |
| Device diagnostics (OpenAPI) | `spec/private-profile/device-diagnostics.yaml` | `GET /device-diagnostics/v0/{assetId}` extension resource ([profile-extensions.md](profile-extensions.md)) |
| Device diagnostics schema | `schema/device-diagnostics.schema.json` | Diagnostics payload (motion, link quality, accuracy provenance) |

Per-service **env contracts** (`services/<svc>/env.contract.yaml`) and **adapter
contracts** (`services/<svc>/adapter.contract.yaml`) follow the same pattern. The
env contract is also served live, as JSON, at each service's `GET /contract`.
