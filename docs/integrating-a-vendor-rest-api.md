# Integrating a vendor's REST positioning API

This guide walks through plugging a third-party RTLS / positioning cloud into the stack via the [`rest-adapter`](../services/rest-adapter/) image. The worked example is Wittra; the same flow applies to any vendor whose public REST API returns a polished positioning fix per device.

## When this is the right pattern

| Vendor exposes …                                                                  | Path                                       |
|----------------------------------------------------------------------------------|--------------------------------------------|
| `GET` per-device position over REST, JSON body, simple auth (Basic / Bearer / API-Key) | **`rest-adapter` + schema file**          |
| Live MQTT topic per device or organisation                                       | Future `mqtt-adapter` (out of scope here)  |
| HTTP webhook into our cluster                                                    | Future `webhook-adapter` (out of scope)    |
| Proprietary SDK, NDA traffic, signed requests, OAuth refresh                     | Private per-vendor image; same engine contract |

The Wittra REST API recommends MQTT for sensor data, but REST is enough for a demo / MVP integration and proves the gateway is vendor-agnostic.

## Architecture in one picture

```
  +-------------+                  +------------------+                    +--------------------+
  |  engine     |  GET /measurement/{device_id}        |     +---- HTTPS GET (Basic auth) ---->|  Wittra cloud      |
  |             |--------------------------------------|---->| rest-adapter (this image)        |  (api.wittra.se)   |
  +-------------+                                      |     +----------------------------------+--------------------+
        ^                                              |                ^
        |  Measurement                                 |                |  schema.json (PUT at runtime
        +----------------------------------------------+                |  by the testbed dashboard)
```

The engine sees the rest-adapter as just another adapter URL in `ADAPTER_URLS`. Switching from `mock-wittra` (dev) to `api.wittra.se` (prod) is a single env-var change.

## Operator workflow

1. **Provision Secrets.** Create a Kubernetes `Secret` carrying the vendor credentials, for Wittra: `organisationId`, `apiKey`, `projectId`.

   ```bash
   kubectl -n positioning create secret generic wittra-credentials \
     --from-literal=org-id=<...> --from-literal=api-key=<...> --from-literal=project-id=<...>
   ```

2. **Deploy the adapter.** One `Deployment` per vendor, image `ghcr.io/jacobbista/5g-northbound/rest-adapter:<tag>`, with the persistent schema PVC at `/app/data/` and the Secret keys mapped to env:

   ```yaml
   env:
     - name: WITTRA_BASE_URL
       value: "https://api.wittra.se"
     - name: WITTRA_ORG_ID
       valueFrom: { secretKeyRef: { name: wittra-credentials, key: org-id } }
     - name: WITTRA_PROJECT_ID
       valueFrom: { secretKeyRef: { name: wittra-credentials, key: project-id } }
     - name: WITTRA_API_KEY
       valueFrom: { secretKeyRef: { name: wittra-credentials, key: api-key } }
   ```

3. **Load the schema.** From the testbed dashboard's **Vendor integrations** view (or by `PUT`ing it from a `curl` in dev):

   ```bash
   curl -X PUT http://rest-adapter-wittra:8080/schema \
     -H "Content-Type: application/json" \
     -d @wittra-schema.json
   ```

   The pod persists the schema to the PVC, so subsequent restarts boot configured.

4. **Wire the engine.** Append the new adapter to `ADAPTER_URLS` and pin the affected device IDs in `DEVICE_MAP`:

   ```yaml
   env:
     - name: ADAPTER_URLS
       value: "wittra=http://rest-adapter-wittra:8080,wifi=http://wifi-positioning:8080"
     - name: DEVICE_MAP
       value: "wittra-tag-01=wittra,wifi-asset-01=wifi"
   ```

5. **Add to the device registry.** Append a `{phoneNumber, deviceId, label}` entry to the gateway's `devices.json` (committed in this repo as `dev/devices.json` for the demo; backed by a ConfigMap in production) so the device appears in the demo UI and CAMARA `Location` lookups work.

## Schema fields, briefly

```json
{
  "vendor": "wittra",
  "default_base_url": "https://api.wittra.se",
  "base_url_env": "WITTRA_BASE_URL",
  "path": "/v4/organizations/{org_id}/projects/{project_id}/devices/{device_id}/telemetry",
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
    "latitude":   { "path": "location.value.latitude" },
    "longitude":  { "path": "location.value.longitude" },
    "accuracy_m": { "path": "location.value.accuracy", "default": 5.0 },
    "confidence": { "const": 0.5 },
    "y":          { "path": "location.value.height", "default": 0.0 },
    "timestamp":  { "path": "location.timestamp", "format": "iso8601" }
  },
  "discover": {
    "path": "/v4/organizations/{org_id}/projects/{project_id}/devices",
    "list_path": "data",
    "path_vars": {
      "org_id":     { "env": "WITTRA_ORG_ID" },
      "project_id": { "env": "WITTRA_PROJECT_ID" }
    },
    "pagination": {
      "type": "page",
      "page_param": "page",
      "size_param": "size",
      "page_size": 100,
      "total_path": "total"
    },
    "mapping": {
      "vendor_device_id": { "path": "id" },
      "label":            { "path": "name" },
      "latitude":         { "path": "location.value.latitude" },
      "longitude":        { "path": "location.value.longitude" },
      "height_m":         { "path": "location.value.height", "default": 0 }
    }
  }
}
```

- **Credentials never live in the schema.** Only `{ "env": "VAR_NAME" }` references. The schema can be committed to a public repo or pasted into a UI without leaking anything.
- **`mapping.accuracy_m`** pulls from `location.value.accuracy` in v4 (radius in metres), falling back to a 5.0 const when the vendor omits it. Older v1 Wittra responses used `payload.location.accuracy` as a `[0, 1]` score; if you point the schema at a v1 cloud, map that field to `confidence` instead.
- **`format: "iso8601"`** parses the timestamp string to a Unix epoch float so the engine can reason about staleness.
- **`cache_ttl_s`** keeps us off the vendor's rate limit: the engine polls at ~1 Hz, the adapter caches each response for the TTL.

### Optional `discover` block (vendor sync in the placement editor)

When a vendor exposes a "list all devices" endpoint, declaring a `discover` block lets the placement editor pull the device list and propose anchor positions instead of forcing manual placement. The block is independent from the per-device telemetry path: same auth + base URL, different endpoint + mapping.

| Field                | Meaning                                                                                                            |
|----------------------|--------------------------------------------------------------------------------------------------------------------|
| `path`               | List endpoint. Same `{var}` substitution as the top-level `path`.                                                  |
| `list_path`          | JSON dotted path to the array inside the response body. Empty (`""`) means the body itself is the array.           |
| `path_vars`          | Per-variable `{env: NAME}` resolution, same shape as the top-level.                                                |
| `pagination.type`    | `"none"` (one GET) or `"page"` (1-indexed page+size query params, walk until accumulated count reaches `total_path`). |
| `mapping`            | Per-entry field map. `vendor_device_id` is required; `label`, `latitude`, `longitude`, `height_m` are optional.    |

Vendors with no positions exposed simply omit `latitude`/`longitude`/`height_m`. The editor lists those devices with a "place manually" warning instead of dropping them somewhere arbitrary. Vendors with no list endpoint omit the `discover` block; the editor falls back to fully manual placement for that technology.

The full HTTP surface is `GET /discover` on the rest-adapter, proxied by the placement editor at `GET /api/vendor/discover`. The editor's "↻ sync vendor" toolbar button drives the flow end to end.

## Local dev: end-to-end with `mock-wittra`

`make demo` brings up [`mock-wittra`](../mocks/mock-wittra/), the rest-adapter, and the rest of the stack. The compose file pre-loads the example schema and points the adapter at the mock:

```bash
make demo

# Quick sanity check
curl http://localhost:8092/health
curl http://localhost:8092/measurement/wittra-tag-01 | jq .

# Full CAMARA chain (gateway → engine → rest-adapter → mock-wittra)
curl -X POST http://localhost:8087/location-retrieval/v0.5/retrieve \
  -H "Authorization: Bearer dev-token" \
  -H "Content-Type: application/json" \
  -d '{"device":{"phoneNumber":"+390119876543"}}'
```

`mock-wittra` is **not** included in production deployments. It exists so a fresh clone of the repo can demonstrate the full chain without an internet round-trip.

## Failure modes worth knowing

| What happens                                                  | What the engine sees                                            |
|---------------------------------------------------------------|-----------------------------------------------------------------|
| Schema missing (operator forgot to load it)                   | `404` from `/measurement/...` → engine treats as "no fix"; no cooldown |
| Credentials env var unset on the pod                          | `404` from `/measurement/...` (logged); same as above           |
| Vendor returns `404` (no current fix)                         | `404`; no cooldown                                              |
| Vendor returns `5xx` repeatedly                               | `404` (from the adapter, after logging); engine `HttpAdapter` cooldown still applies one layer up |
| Vendor unreachable / TLS failure                              | `404`; engine cooldown after 3 fails                            |
| Cache hit within TTL                                          | Cached `Measurement`; no vendor call                            |
| `discover` block absent in schema                             | `GET /discover` returns `404`; editor's sync panel shows "vendor has no discover block" |
| `discover` block present but vendor list endpoint unreachable | `GET /discover` returns `503`; editor's sync panel surfaces the error and stays empty |

In every case the gateway downstream behaves correctly: a CAMARA `retrieve` for a device with no current fix returns a `NOT_FOUND` envelope rather than a stale or made-up position.
