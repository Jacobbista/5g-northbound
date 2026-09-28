# vendor-adapter

Connects a vendor's REST positioning cloud to the positioning engine. The image
is generic: a schema document names the vendor's URLs, authentication and
field mapping, and the adapter translates each response into the adapter
contract. The guide is
[docs/integrating-a-vendor-rest-api.md](../../docs/integrating-a-vendor-rest-api.md).

## Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /measurement/{positioningId}` | the adapter contract, see [docs/adapters.md](../../docs/adapters.md) |
| `GET /devices` | the vendor's device list in the adapter contract's shape, for onboarding |
| `GET /discover` | the vendor's device list for the placement editor. `?raw=1` returns the vendor records unchanged |
| `GET /diagnostics/{positioningId}` | on-demand vendor telemetry |
| `GET /schema`, `PUT /schema` | the loaded schema. `PUT` applies a schema live, and answers `422` when it contradicts the declared capabilities |
| `GET /contract` | the variables the image and the loaded schema need, the declaration and its payload counters |
| `GET /contract/schema` | the JSON Schema of the schema document |
| `GET /health`, `GET /ready` | liveness, and readiness once a consistent schema is loaded |

## Configuration

`SCHEMA_FILE` (default `/app/data/schema.json`) is the schema read at start.
The variables the schema names (base URL, account, credentials) come from the
environment. Registration uses `POSITIONING_ENGINE_URL`, `ADAPTER_NAME`,
`ADAPTER_BASE_URL` and `ADAPTER_CAPABILITIES`. The full list is in
[env.contract.yaml](env.contract.yaml), served at `GET /contract`.

## Tests

```bash
pytest
```
