# Integrating a vendor REST API

`vendor-adapter` connects a vendor's positioning cloud to the engine without
code. A schema document tells it where the vendor's API is, how to
authenticate, and which fields of the vendor's response hold the position. The
worked example is the Wittra UWB cloud,
[`examples/wittra-schema.json`](https://github.com/Jacobbista/5g-northbound/blob/main/services/vendor-adapter/examples/wittra-schema.json).

| The vendor offers | Integration |
|-------------------|-------------|
| a REST endpoint returning the current position of a device, with Basic, Bearer or header authentication | `vendor-adapter` with a schema |
| an MQTT feed or webhooks | declared in the schema grammar (`transport`), not implemented |
| an SDK, signed requests, OAuth refresh | a separate adapter in a private repository |

## Identifiers

| Identifier | Where it lives | Rule |
|------------|----------------|------|
| `assetId` | the gateway's asset map | chosen by the organisation |
| `positioningId` | a capability of the asset | equals the vendor's device id: the adapter puts it in the vendor URL unchanged |
| `source` | a capability of the asset | equals the adapter's `ADAPTER_NAME`, which is how the engine routes to it |

## The schema document

| Field | Meaning |
|-------|---------|
| `vendor` | the vendor's name, reported as `source` on each measurement |
| `transport` | `rest`, the only one implemented |
| `baseUrl` | `{"env": NAME}`: the variable holding the API root |
| `path` | the device URL template, with `{device_id}` and the names in `pathVars` |
| `pathVars` | each name taken from an environment variable |
| `auth` | `none`, `basic`, `bearer` or `header`, with credentials named by environment variable |
| `cacheTtl` | seconds a vendor response is reused, since the engine polls about once a second |
| `requestTimeout` | seconds before a vendor call is abandoned |
| `mapping` | where each measurement field is in the vendor's response |
| `discover` | optional: the vendor's device list |
| `diagnostics` | optional: extra device telemetry, see [profile extensions](profile-extensions.md) |

The schema holds no credential, only the names of the variables that carry
them, so it can be committed and shared. `GET /contract` on a running adapter
lists the variables the loaded schema needs. The full grammar is served at
`GET /contract/schema`.

A mapping entry is `{"const": value}` or `{"path": "a.b.0.c"}`, where the path
may index lists and a negative index counts from the end. A path entry takes
`default`, `format: "iso8601"` to turn an ISO time into epoch seconds, and a
`transform`: `linear` (`scale * value + offset`) or `bool` (true for the listed
values).

```json
"mapping": {
  "frame":      { "const": "wgs84" },
  "latitude":   { "path": "latest.data.location.value.latitude" },
  "longitude":  { "path": "latest.data.location.value.longitude" },
  "confidence": { "path": "latest.data.location.value.accuracy" },
  "z":          { "path": "latest.data.location.value.height" },
  "timestamp":  { "path": "latest.data.location.timestamp", "format": "iso8601" },
  "lastSeen":   { "path": "lastSeen", "format": "iso8601" }
}
```

- **`frame`** selects the pair: `wgs84` takes `latitude` and `longitude`,
  `venue` takes `x` and `y` in metres from the floor plan's lower-left corner.
  A record whose pair does not resolve is no fix.
- **`timestamp`** is required: the time of the fix.
- **`accuracy`** is a radius in metres. Read a real payload before mapping it.
  The Wittra field named `accuracy` is a score between 0 and 1, so the example
  maps it to `confidence` and leaves `accuracy` unmapped. The engine then uses
  the nominal accuracy of the declared `accuracy_class`.
- **`z`** is the height above the venue floor. Map it only when the vendor
  measures height. A `linear` transform converts another reference.
- **`lastSeen`** is when the device last communicated with the vendor, which
  differs from the fix time for a still device. The live Wittra cloud leaves
  it null on every device, so mapping it does not guarantee it arrives.
  `GET /contract` counts the payloads where a mapped field stays null.

Point the device URL at the vendor's current-state resource. A history
endpoint can round coordinates for storage: the Wittra history returns four
decimals, about 11 m, while `GET /devices/{id}` returns full precision.

## Declaring how the source reports

The schema says where the data is. `ADAPTER_CAPABILITIES` says what it means:
`source`, `kinds`, `frame`, `accuracy_class`, `z`, `reporting` and
`reportingInterval` (see [adapters](adapters.md#what-an-adapter-declares)).
Declare them from the vendor's documentation and from real payloads.

The adapter checks the schema against the declaration when it loads one, at
start and on `PUT /schema`, and refuses a schema that cannot carry it:

| Declaration | Requires |
|-------------|----------|
| `reporting: on_motion` | a `lastSeen` mapping: the last communication confirms the last fix |
| `reporting: periodic` or `on_motion` | a `reportingInterval` |
| `z: true` | a `z` mapping |
| `z: false` | no `z` mapping |

A refused schema is not applied. At start the pod stays unready and `/ready`
names the contradiction. `PUT /schema` answers `422` with the list under
`detail.declaration`, and the live schema stays as it was.

The adapter also compares the declaration with every payload and reports on
`GET /contract` under `declaration.observed`:

- `unresolved`: for each mapped field, the payloads that left it null. A
  `lastSeen` that never resolves rules out `on_motion`.
- `intervalExceeded`: two reports of one device further apart than
  `reportingInterval`.
- `movedWithoutFix`: for `on_motion`, a position that changed without a new fix
  time, which contradicts the declaration.

The counters restart when a schema is applied.

## Deploying an integration

1. **Credentials.** Put the vendor credentials in a Kubernetes `Secret` and map
   them to the variables the schema names.

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

2. **Read real records.** With a schema that has only the connection fields and
   a `discover` path, `GET /discover?raw=1` returns the vendor's device records
   unchanged. Write the mapping against those field names. The raw records can
   carry sensitive data, so keep this endpoint behind operator access.

3. **Store the schema in a ConfigMap** mounted at `SCHEMA_FILE`, and restart the
   deployment to change it. `PUT /schema` applies a schema to a running pod for
   trials. On a read-only mount it answers `persisted: false`, and the ConfigMap
   applies again at the next restart.

4. **Register with the engine.** Set `POSITIONING_ENGINE_URL`, `ADAPTER_NAME`
   (the `source` of the assets, `wittra` here), `ADAPTER_BASE_URL` and
   `ADAPTER_CAPABILITIES`. The adapter registers itself.

5. **Add the assets** to the gateway's asset map, with the vendor device id as
   `positioningId`:

   ```json
   {
     "assetId": "pkg-4471",
     "kind": "pallet",
     "org": "acme",
     "capabilities": [{ "source": "wittra", "positioningId": "<vendor device id>" }]
   }
   ```

   See [asset registry](asset-registry.md). Devices the vendor lists can also
   be onboarded from `GET /assets/discoverable`.

## The device list

A `discover` block describes the vendor's device list: `path`, `pathVars`,
`listPath` (where the array is in the response, empty when the response is the
array), `pagination` (`none`, or `page` with page and size parameters and the
path of the total), and a `mapping` with `vendorDeviceId` required and
`label`, `latitude`, `longitude`, `z` and `deviceType` optional. It feeds two
things.

**Anchor import in the placement editor.** `GET /discover` returns the list
filtered by `filter.requirePath` (the Wittra example keeps devices with a fixed
location). The editor shows the devices on the room at their vendor position
and imports them as anchors, keyed by vendor device id, so a later import
updates them.

**Asset onboarding.** `GET /devices` returns the unfiltered list in the adapter
contract's shape, and `classify` sorts it:

- `assetWhen` (a match is an asset, everything else infrastructure) or
  `infrastructureWhen` (the reverse). With `assetWhen`, a device type the
  schema does not know is infrastructure and is not offered for onboarding.
- `sourceClassRules` and `sourceClassDefault` set the positioning technology.

A predicate matches when `requirePath` resolves to a value and, if given,
`path` equals `equals`. Classify only what the vendor's record states. The
Wittra example sets the role from `deviceType == "tag"`. It sets no
`sourceClass`, because the device list does not say which radio a device
carries.

## Running it locally

`make demo` starts `mock-vendor`, which reads the same schema as
`vendor-adapter` and answers with synthetic devices on the schema's paths and
behind its authentication. Changing the schema changes both.

```bash
curl -s http://localhost:8092/measurement/wittra-tag-01 | jq
curl -s -X POST http://localhost:8087/location-retrieval/v0.5/retrieve \
  -H "Authorization: Bearer $(make -s token)" -H "Content-Type: application/json" \
  -d '{"device":{"assetId":"pkg-4471"}}' | jq
```

## Failure behaviour

| Situation | `GET /measurement` | Effect |
|-----------|--------------------|--------|
| no schema loaded | `404` | the engine skips the source |
| a variable the schema names is unset | `404`, logged | the engine skips the source |
| the vendor answers `404`, an error, or is unreachable | `404`, logged | the engine skips the source without backing off |
| the record has no position | `404` | the engine skips the source |
| a response within `cacheTtl` | the cached measurement | no vendor call |

An asset with no position from any source answers
`422 LOCATION_RETRIEVAL.UNABLE_TO_LOCATE`. `GET /discover` answers `404` when
the schema has no `discover` block and `503` when the vendor list cannot be
read.
