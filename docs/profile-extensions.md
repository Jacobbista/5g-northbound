# Profile extensions

The gateway serves the two CAMARA APIs and, beside them, endpoints of its own.
The CAMARA responses follow the profiled specifications, and a client that
knows only CAMARA reads them unchanged. Everything else sits on separate
resources with their own published contracts. The gateway tests check that
every route the gateway serves is published and every published route is
served, and that stream messages conform to the AsyncAPI document.

## Surfaces

Data outside CAMARA is grouped in a named container, never added as loose
fields to a CAMARA body: a separate resource at its own path, or a named
object inside a shared message (`diagnostics` in the stream).

| Surface | Contract | Content |
|---------|----------|---------|
| `GET`, `PUT /assets` | `extensions.yaml`, `schema/asset.schema.json` | the asset map ([asset registry](asset-registry.md)) |
| `GET /assets/discoverable` | `extensions.yaml` | devices the sources report that are not yet assets |
| `GET /assets/{assetId}/details` | `extensions.yaml` | the asset with its fused position, strategy and sources |
| `PUT`, `DELETE /assets/{assetId}/placement` | `extensions.yaml` | the start point of a synthetic asset, in the frame of its room |
| `GET /device-diagnostics/v0/{assetId}` | `device-diagnostics.yaml`, `schema/device-diagnostics.schema.json` | device telemetry, fetched from the source on request |
| `diagnostics` in the position stream | `asyncapi-stream.yaml` | telemetry the source sends with each fix |
| `GET /capabilities` | `extensions.yaml` | what the deployment can do now, from the adapters' declarations and the asset map |
| `GET /adapters` | `extensions.yaml` | name, state and declared capabilities of each adapter |
| `GET /anchors/calibration` | `extensions.yaml` | fitted WiFi parameters per anchor |
| `GET /blueprint` | `extensions.yaml`, `schema/layout.schema.json` | the venue blueprint, read-only |

The contract files are under `spec/private-profile/` and `schema/`
([contracts](contracts.md)). The body of each surface is in
[data contracts](data-contracts.md).

## Diagnostics vocabulary

Diagnostics carry a small **core** with fixed names and units, and a
`vendorSpecific` object for everything else. A consumer reads the core the
same way for every vendor. `vendorSpecific` holds values as the vendor sends
them, is not comparable across vendors, and is not authoritative.

A field enters the core when an external standard defines it and a consumer
of this profile uses it. The profile adopts the definition and unit, gives the
field its own name, and records the source in the vocabulary's `standard`
entry: LwM2M identifies battery level by the numeric resource 3/0/9 and names
no JSON field, so `battery` is this profile's name for that definition. The
`vendorSpecific` object corresponds to the `properties` object that omlox uses
for everything outside its own core.

| Core field | Standard | Type and unit |
|------------|----------|---------------|
| `battery` | OMA LwM2M 3/0/9 | number, percent 0 to 100 |
| `lastCommunicationTime` | omlox `timestamp_generated` | RFC 3339 UTC |
| `accuracy` | omlox `accuracy` | number, metres |
| `moving` | derived | boolean |

The vocabulary is
[`spec/private-profile/diagnostics-vocabulary.json`](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/diagnostics-vocabulary.json),
version 2.0.0, and the gateway serves it at
`GET /contracts/diagnostics-vocabulary.json`. The vendor-adapter reads the same
file to route the fields its schema maps.

**Routing.** A field the vendor schema maps under a core name is published at
the top of `diagnostics`. Any other mapped name goes under `vendorSpecific`.
The schema's mapping (`format`, `transform`) brings a value to the core unit,
and the vendor-adapter publishes a core time in RFC 3339 whatever form the
vendor gives it. A field that does not resolve for a record is left out.

**`moving`** is true when the omlox `speed` exceeds 0.15 m/s, a constant of the
vocabulary. A vendor that reports its own moving state maps it to `moving`
directly. A vendor that reports neither has no `moving`. The Wittra example maps
the vendor's `motion` string, which is not a core name, so it arrives under
`vendorSpecific`.

**Delivery.** Each core field has a default tier: `moving` travels in the
stream with each fix, the others are fetched on request from
`/device-diagnostics`. The vendor schema chooses per field
([integrating a vendor REST API](integrating-a-vendor-rest-api.md#the-schema-document)).

**Growth.** A field stays in `vendorSpecific` until it recurs across vendors
and a consumer needs it. Promoting it into the core is a new version of the
vocabulary. The name of a device is not a diagnostics field: it travels with
onboarding, as the asset's `label`.
