# vendor-adapter

Schema-driven adapter that translates one vendor's REST response into the engine's `Measurement` shape. Operators load the schema at runtime via `PUT /schema`; no per-vendor code lives in this image.

This is the generic path used for any vendor RTLS cloud whose own output is already a polished positioning fix (Wittra, Quuppa, and so on). Polling REST exposes that fix to the engine without rewriting the algorithm. When the engine is configured with a single such adapter, fusion is a no-op passthrough.

## Status

`v0.1.0` - the `rest` transport (polling), schema persistence, in-process TTL cache, four auth schemes, dotted-path mapping with linear transforms. The `mqtt` and `webhook` transports are schema-declared extension points, not yet implemented.

## HTTP surface

| Method · path                       | Returns                          | Notes                                                                 |
|-------------------------------------|----------------------------------|-----------------------------------------------------------------------|
| `GET  /health`                      | `{"status":"ok",…}`              | Reports `schema_loaded` + the loaded `vendor` name                    |
| `GET  /contract`                    | env contract JSON                | Unauthenticated. Variable names, no values. Answers with no schema loaded |
| `GET  /contract/schema`             | JSON Schema of `Schema`          | Unauthenticated. Shape of `PUT /schema` / the ConfigMap document. Not the loaded instance |
| `GET  /schema`                      | schema JSON                      | `404` when no schema is loaded yet                                    |
| `PUT  /schema`                      | `{"status":"ok","vendor":"…"}`   | Replace + persist the schema. Clears the in-process cache             |
| `GET  /measurement/{device_id}`     | `Measurement`                    | Engine contract. `404` if no schema, vendor 404, or vendor unreachable |

Live OpenAPI docs at `http://localhost:8092/docs` (compose port).

## Schema shape

```json
{
  "vendor": "wittra",
  "default_base_url": "https://api.wittra.se",
  "base_url_env": "WITTRA_BASE_URL",
  "path": "/v1/organizations/{org_id}/projects/{project_id}/devices/{device_id}",
  "path_vars": {
    "org_id":     { "env": "WITTRA_ORG_ID" },
    "project_id": { "env": "WITTRA_PROJECT_ID" }
  },
  "auth": {
    "scheme": "basic",
    "username": { "env": "WITTRA_ORG_ID" },
    "password": { "env": "WITTRA_API_KEY" }
  },
  "cache_ttl_s": 5.0,
  "request_timeout_s": 5.0,
  "mapping": {
    "frame":      { "const": "wgs84" },
    "latitude":   { "path": "payload.location.latitude" },
    "longitude":  { "path": "payload.location.longitude" },
    "accuracy_m": { "const": 5.0 },
    "confidence": { "path": "payload.location.accuracy", "default": 0.5 },
    "y":          { "path": "payload.location.height", "default": 0.0 },
    "timestamp":  { "path": "timestamp", "format": "iso8601" }
  }
}
```

| Section          | Purpose                                                                                                       |
|------------------|---------------------------------------------------------------------------------------------------------------|
| `vendor`         | Surfaces in `Measurement.source` so the engine can route on it                                                |
| `default_base_url` | Used when `base_url_env` is unset. `base_url_env` lets the testbed point at a staging cloud without editing the schema |
| `path`           | Path template. `{device_id}` plus every key in `path_vars`                                                    |
| `path_vars`      | Each var pulls its value from the env var named in its `env` field                                            |
| `auth.scheme`    | `none` / `basic` / `bearer` / `header`. Credentials never live in the schema - only the env-var names         |
| `cache_ttl_s`    | TTL of the in-process response cache. Engine polls at ~1 Hz; vendors usually do not want that fast            |
| `request_timeout_s` | httpx timeout when calling the vendor                                                                      |
| `mapping`        | One spec per `Measurement` field. Each spec is either `{ "const": value }` or `{ "path": "dotted.path", "default": …, "transform": …, "format": "iso8601" }` |

`transform.type = "linear"` (`scale * x + offset`) is the only transform supported today. `format = "iso8601"` converts an ISO timestamp string to a Unix epoch float. List indices in paths use digits (`a.b.0.c`).

`mapping.frame` may be `"wgs84"` (`latitude` and `longitude` carry the coordinates) or `"local"` (the values carried by the `latitude` and `longitude` specs are written into `x` and `z` respectively).

## Operator workflow

1. Deploy the adapter pod with the persistent schema PVC mounted at `/app/data/`.
2. Open the testbed dashboard's **Vendor integrations** view, paste the schema JSON, save. The dashboard `PUT`s it to `/schema`; the pod persists it to the PVC and clears its cache.
3. Configure the credentials as a Kubernetes `Secret` (`WITTRA_API_KEY`, `WITTRA_ORG_ID`, …) and mount its keys into the adapter pod's env. Restart the pod (or rolling update) to pick up new env values; schema changes themselves do not require a restart.
4. Append the adapter to the engine's `ADAPTER_URLS` (e.g. `wittra=http://vendor-adapter-wittra:8080`) and to `DEVICE_MAP` for the affected devices. Engine restart (or `kubectl rollout restart deployment/positioning-engine`) picks them up.

## Configuration

| Variable        | Default                       | Notes                                                                                   |
|-----------------|-------------------------------|-----------------------------------------------------------------------------------------|
| `SCHEMA_FILE`   | `/app/data/schema.json`       | Where the schema is read at boot and written by `PUT /schema`. Mount a PVC here in K8s  |

Other env vars (vendor base URL, credentials, path vars) are not adapter-level - they are referenced by name from inside the schema. The pod fails closed when a referenced env var is missing: `GET /measurement/…` returns `404` and the engine treats that as "no fix" for the cycle.

## Local development

The compose stack ships a [`mock-vendor`](../../mocks/mock-vendor/) toy service that serves Wittra-shaped JSON without an account, plus a bind-mounted example schema. `make demo` is enough to see the full chain (engine → vendor-adapter → mock-vendor) producing a CAMARA `Location` for `+390119876543` (the Wittra demo device).

```bash
curl http://localhost:8092/health
# {"status":"ok","schema_loaded":true,"vendor":"wittra"}

curl http://localhost:8092/measurement/wittra-tag-01 | jq .
# {"source":"wittra","frame":"wgs84","latitude":45.06…,"longitude":7.65…,"accuracy_m":5.0, …}
```

Replace the example schema at runtime to experiment without restarting the pod:

```bash
curl -X PUT http://localhost:8092/schema \
  -H "Content-Type: application/json" \
  -d @vendor-adapter/examples/wittra-schema.json
```

## What this image does NOT do

- **`mqtt` / `webhook` transports.** The engine-facing contract is always pull (`GET /measurement/{id}`); the source-side transport is a schema dimension (`transport:`). The `mqtt` transport subscribes to the vendor broker, caches the latest fix, and serves it from cache; `webhook` receives pushes. Both are the same image, selected by the schema, and are not yet implemented. Only `rest` (pull-through) ships today.
- **Vendor SDKs / proprietary code.** This image is generic on purpose. Anything that needs an SDK or NDA-bound code ships as a separate private image implementing the same `GET /measurement/{device_id}` contract.
- **OAuth refresh, signed requests, paginated cursors.** Vendors that need these get a thin per-vendor image.

## See also

- [`docs/integrating-a-vendor-rest-api.md`](../docs/integrating-a-vendor-rest-api.md) - operator-facing guide
- [`docs/adapters.md`](../docs/adapters.md) - adapter contract this image satisfies
- [`mock-vendor/`](../../mocks/mock-vendor/) - local Wittra cloud fake used by the demo
