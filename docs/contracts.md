# Machine-readable contracts

Every contract this stack publishes is a versioned file in the (public) repo,
fetchable over HTTP. Fetch the **raw** URL - the `github.com/.../blob/...` link
is an HTML page, not the file.

```
https://raw.githubusercontent.com/Jacobbista/5g-northbound/<ref>/<path>
```

`<ref>` is `main` for the latest, or a **release tag to pin an immutable
version** (e.g. `v0.9.0`). Pin a tag when you integrate; the contract may evolve
on `main`.

Two worked URLs:

```
# hop-log schema (latest)
https://raw.githubusercontent.com/Jacobbista/5g-northbound/main/schema/hop-log.schema.json
# profiled OpenAPI, pinned to a release
https://raw.githubusercontent.com/Jacobbista/5g-northbound/v0.9.0/spec/private-profile/generated/location-retrieval.profiled.yaml
```

## The contracts

Prefix each `<path>` with the raw base above.

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

Per-service **env contracts** (`services/<svc>/env.contract.yaml`) and **adapter
contracts** (`services/<svc>/adapter.contract.yaml`) follow the same pattern. The
env contract is also served live, as JSON, at each service's `GET /contract`.
