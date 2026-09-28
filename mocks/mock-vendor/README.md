# mock-vendor

A stand-in for a vendor positioning cloud, used by `make demo` so the vendor
integration runs without a vendor account. It is built from source by compose
and never published or deployed.

It reads the same schema document as `vendor-adapter` and builds responses
that the schema resolves back to synthetic values:

| Schema field | Behaviour |
|--------------|-----------|
| `path` | the device URL it serves |
| `mapping` | each mapped path holds a synthetic value: a walking position, accuracy, height, fix time |
| `discover` | the device list URL, with one mobile device and one fixed device so onboarding sees an asset and infrastructure |
| `auth` | enforced as declared, against the variables the schema names |
| `pathVars` | a request must address the account those variables name, otherwise `404` |
| `transport` | only `rest`. Another transport answers `501` |

The walk starts from a fixed point with no geographic meaning.

`SCHEMA_FILE` (default `/app/config/schema.json`) is the schema to serve. The
account and credentials come from the variables the schema names, for the
Wittra example `WITTRA_ORG_ID`, `WITTRA_PROJECT_ID` and `WITTRA_API_KEY`.

```bash
curl -s -u demo-org:demo-key \
  http://localhost:8091/v4/organizations/demo-org/projects/demo-prj/devices/wittra-tag-01 | jq
```
