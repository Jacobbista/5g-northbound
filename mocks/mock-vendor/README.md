# mock-vendor

Schema-driven double of a vendor positioning cloud. It reads the **same schema**
[`vendor-adapter`](../../services/vendor-adapter/) consumes and serves responses
that satisfy it, so a fresh `make demo` exercises the vendor integration end to
end without a real vendor account or external connectivity.

It is not tied to any one vendor: mount a different schema and it emits that
vendor's shape, on that vendor's URL paths, behind that vendor's auth. The
committed demo uses the Wittra example schema.

Production deployments point `vendor-adapter` at the real vendor cloud and never
run this image.

## How it works

The schema describes how `vendor-adapter` *parses* a vendor response into a
`Measurement` (dotted paths, list indices). mock-vendor does the inverse: it
*builds* a response the schema resolves back to the injected values.

| Schema field | mock-vendor behaviour |
|--------------|-----------------------|
| `path` | The telemetry URL it serves. `{device_id}` (and any `path_vars`) are matched out of the request. |
| `mapping` | The telemetry body is built so each mapping path resolves to a synthetic value (walking lat/lon, accuracy, height, timestamp). |
| `discover.path` + `discover.mapping` | The device-list URL. Emits one mobile asset and one fixed-position node, with the `device_type` each `classify` branch keys off, so onboarding sees both an asset and an infrastructure candidate. |
| `auth` | Enforced as declared (`basic` / `bearer` / `header` / `none`), against the env the schema references. |
| `path_vars` | A request must address the account those env vars name, else `404`. |
| `transport` | Only `rest` is served. A schema with another transport returns `501`. |

The reported position is a slow walk around a fixed init point; the value is a
placeholder - a mock drives the real ingest pipeline, it is not geographically
meaningful.

## Configuration

| Variable       | Default                    | Notes                                          |
|----------------|----------------------------|------------------------------------------------|
| `SCHEMA_FILE`  | `/app/config/schema.json`  | The vendor schema to serve (mount the same one `vendor-adapter` uses). |

The account values and credentials the schema references come from the env vars
its `path_vars` / `auth` blocks name (for the Wittra example: `WITTRA_ORG_ID`,
`WITTRA_PROJECT_ID`, `WITTRA_API_KEY`).

## Trying it locally

```bash
# The path + auth come from the mounted schema (Wittra example shown):
curl -u demo-org:demo-key \
  'http://localhost:8091/v4/organizations/demo-org/projects/demo-prj/data?deviceId=pkg-4471&dataType=location' \
  | jq .
```

The compose stack wires this service as the upstream for `vendor-adapter`, both
reading the same schema file. See
[`docs/integrating-a-vendor-rest-api.md`](../../docs/integrating-a-vendor-rest-api.md)
for the full chain.
