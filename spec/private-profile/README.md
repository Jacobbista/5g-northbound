# CAMARA private-asset profile

A profile of the CAMARA Device Location APIs for private industrial networks
that locate assets, not subscribers. This repository is its reference
implementation. The motivation and gap analysis are in the position paper
*"Private Networks, Public APIs: Exposing Hybrid Positioning through CAMARA in
Industrial 6G"* (Eriksson et al., RISE, 6GHYPE4Ind).

## Formal specification

The CAMARA documents are pinned, unedited, in
[`services/camara-gateway/spec/`](../../services/camara-gateway/spec/):
meta-release r3.2, commit `bc17ceeb4ee34929d5f65b8851d99d4dda4c5af1`. The
profile changes them through [OpenAPI Overlay 1.0.0](https://spec.openapis.org/overlay/v1.0.0.html)
documents:

- [`overlay-retrieval.yaml`](overlay-retrieval.yaml) adds `assetId` to
  `Device`, removes `phoneNumber`, `ipv4Address` and `ipv6Address`, and adds
  `source`, `kind`, `horizontalAccuracy`, `altitude` and `verticalAccuracy` to
  `Location`.
- [`overlay-verification.yaml`](overlay-verification.yaml) applies the same
  identity change to verification.

`make profile-spec` applies them and writes the profiled documents to
[`generated/`](generated/). The generated files are committed so that a client
can pin one self-contained document, and CI fails when they differ from base
plus overlays.

The position stream is a WebSocket, described in AsyncAPI 3.0 by
[`asyncapi-stream.yaml`](asyncapi-stream.yaml). The endpoints beside CAMARA are
in [`extensions.yaml`](extensions.yaml) and
[`device-diagnostics.yaml`](device-diagnostics.yaml), described in
[profile extensions](../../docs/profile-extensions.md). Every published file
and how to fetch it: [contracts](../../docs/contracts.md).

This document holds what the schemas do not: the meaning of the extensions,
the authorisation model and the behaviour required by the base contract.

## Scope

CAMARA was designed for public mobile networks, where the tracked device is a
subscriber, the operator computes its position, and the subscriber consents.
In a private industrial network three things differ:

1. The tracked entity is an asset, such as a tag, a tool or a pallet, with no
   MSISDN, IMSI or NAI.
2. Positions come from non-3GPP sources fused at the edge (UWB, WiFi, GNSS),
   independently of the core network.
3. One organisation owns the network, the assets and the applications, so the
   consent leg of three-legged OAuth has no counterpart.

The CAMARA data model carries over: a position is a timed area, and no field
names the technology behind it. The profile keeps the response shape and
changes identity, metadata, delivery and authorisation.

A public-network identifier has no source behind it here: serving a position
for a `phoneNumber` would need network-based positioning of a UE, which this
profile does not include. The profile therefore accepts responses a stock
CAMARA client can read, and refuses the requests of such a client.

## Extensions

### 1. Asset identity

The `device` object carries an `assetId`:

```json
{ "device": { "assetId": "pkg-4471" } }
```

- `networkAccessIdentifier` is accepted as an alias in the form
  `<assetId>@<org>.assets`, such as `pkg-4471@acme.assets`, for a client
  limited to the stock fields. Any other NAI identifies nothing.
- `phoneNumber`, `ipv4Address` or `ipv6Address` in the request answers
  `422 UNSUPPORTED_IDENTIFIER`.

The gateway resolves the `assetId` in the asset map to its capabilities, each a
`source` and a `positioningId`, and to its organisation
([asset registry](../../docs/asset-registry.md)). The map is written over
`PUT /assets` on the gateway, schema
[`schema/asset.schema.json`](../../schema/asset.schema.json).

### 2. Location metadata

`Location` gains optional fields, absent when unknown:

| Field | Meaning |
|-------|---------|
| `source` | the source of the asset's primary capability, as its adapter registers it |
| `kind` | the asset class |
| `horizontalAccuracy` | horizontal error in metres as the sources report it, without the 1 m floor of `area.radius`. Treated as one sigma when fixes are fused |
| `altitude` | height above the WGS84 ellipsoid in metres, the datum of latitude and longitude as in W3C Geolocation and 3GPP TS 23.032: the surveyed ellipsoidal height of the venue origin plus the measured height above the floor. Present only when both exist |
| `verticalAccuracy` | one-sigma error of the measured height in metres, from the sources or from the source's declared nominal value, without the error of the origin survey. Present only with `altitude` |

`altitude` covers several floors and stacked storage, which the 2D circle of
CAMARA cannot express.

### 3. Position stream

Retrieval stays the contract. For moving assets a stream is offered beside it,
`ws[s]://<gateway>/positions/stream`. The token travels in the
`Sec-WebSocket-Protocol` header as `bearer.jwt, <jwt>`, since a browser cannot
set `Authorization` on a WebSocket and a token does not belong in a URL
(RFC 6750, section 5.3). Each message lists one entry per asset, with
`assetId`, `source`, `kind`, `org`, the position and its times. A positioning
id with no asset behind it is not sent. The stream is filtered by
organisation like the other surfaces.

### 4. Authorisation: 2-legged, organisation-scoped

**Authentication.** A CAMARA consumer is an application using the OAuth 2.0
`client_credentials` grant. The token represents the application, as in stock
CAMARA, and each consumer has its own client.

**Authorisation.** Two layers. The realm role `camara-location-read` allows
reading positions at all. The token's `org` claim scopes the consumer to the
assets whose `org` matches, on retrieval, verification, the asset surfaces,
`/capabilities`, the diagnostics and the stream. An asset of another
organisation answers `404`, as a missing one does.

A token without an `org` claim is the operator's and sees every organisation.
Every consumer client therefore carries an `org`, set when the client is
created: a consumer client without one would receive operator scope.

Writes to shared state belong to the operator. `PUT /assets` and
`GET /assets/discoverable`, which lists devices of every organisation, answer
`403 PERMISSION_DENIED` to a token with an `org` claim.

**Responsibilities.** KELT provisions the identity provider: the realm, one
client per consumer, the roles and the `org` attribute. The gateway enforces:
it validates the token, checks the role and matches `org` against the asset
map. It does not depend on how the token was obtained, so a browser
application signing in with the authorisation code flow is served by the same
rules.

**Granularity.** The scope is the organisation. Restricting a consumer to a
subset of an organisation's assets, such as a service provider that maintains
only the tools, is not part of the profile. Isolation between organisations is
implemented at the functional level and has not been assessed for security.

## Conformance with the base contract

Each request parameter of the pinned r3.2 contract is implemented as below.

### Freshness: `maxAge`

CAMARA treats the moment a device is located and the moment its position is
computed as one event. A private source that reports on motion separates them:
a still asset keeps its last fix, and its later communications confirm that
the fix still holds. The profile resolves this with a declaration. Each source
declares how it reports (`reporting`: `on_request`, `periodic` or `on_motion`,
with a `reportingInterval`,
[adapters](../../docs/adapters.md#reporting-and-reportinginterval)).
`lastLocationTime` is the **established time**, the latest time at which the
position is known to hold. For a source that reports on motion it is the later
of the fix time and the last communication. For a fused position it is the
earliest among the contributions.

A client reading a `lastLocationTime` of ten seconds ago for an asset whose fix
is three days old concludes that the asset was there ten seconds ago. The
declaration makes that conclusion true.

`maxAge`, in seconds, is judged on the established time:

- **absent**: any age is accepted.
- **`N`**: a position established more than `N` seconds ago is not served.
- **`0`**: only a position as recent as its sources can provide is served.
  That holds always for a source that computes on request, and within one
  `reportingInterval` for the others. A source that declares no model is never
  current. The gateway asks the engine on every request with `0`.

An unsatisfied request answers `422 LOCATION_RETRIEVAL.UNABLE_TO_FULFILL_MAX_AGE`,
or the `LOCATION_VERIFICATION` code on verification.

The gateway keeps the last position per `(positioningId, source)`. An entry is
reused while it was fetched less than `LOCATION_CACHE_TTL_S` ago, 5 s by
default, and only when it satisfies the request's `maxAge`.

### Area: `maxSurface`

The response is a circle, and `maxSurface` in square metres bounds its area
`π·radius²`. A larger circle answers
`422 LOCATION_RETRIEVAL.UNABLE_TO_FULFILL_MAX_SURFACE`. `radius` is the
horizontal accuracy raised to the 1 m minimum of CAMARA's `Circle`.

### Verification

`POST /location-verification/v3/verify` takes a circular area. The gateway
compares it with the position's uncertainty circle, centre and horizontal
accuracy without the 1 m floor: `TRUE` when the circle lies inside the area,
`FALSE` when outside, `PARTIAL` when it crosses the boundary. With `PARTIAL`,
`matchRate` (1 to 99) is the percentage of the circle inside the area.

### Errors

Generic codes are bare and API codes carry the API name, as Commonalities
defines. Every response carries an `x-correlator` header, echoed from the
request or generated.

| HTTP | `code` | When |
|------|--------|------|
| 400 | `INVALID_ARGUMENT` | a malformed body or parameter |
| 401 | `UNAUTHENTICATED` | missing, invalid or expired token |
| 403 | `PERMISSION_DENIED` | the token lacks `camara-location-read` |
| 404 | `IDENTIFIER_NOT_FOUND` | unknown `assetId`, or one of another organisation |
| 422 | `MISSING_IDENTIFIER` | no `device`, or no identifier in it |
| 422 | `UNSUPPORTED_IDENTIFIER` | a public-network identifier |
| 422 | `LOCATION_{RETRIEVAL,VERIFICATION}.UNABLE_TO_LOCATE` | no source has a position for the asset |
| 422 | `LOCATION_{RETRIEVAL,VERIFICATION}.UNABLE_TO_FULFILL_MAX_AGE` | no position recent enough for `maxAge` |
| 422 | `LOCATION_RETRIEVAL.UNABLE_TO_FULFILL_MAX_SURFACE` | the circle is larger than `maxSurface` |
| 502 | `BAD_GATEWAY` | the engine answered with an error |
| 503 | `UNAVAILABLE` | the engine is unreachable, not configured, or the venue has no georeference |

`400 INVALID_ARGUMENT` covers out-of-range values too. `OUT_OF_RANGE` is not
used.

## Status

| Extension or behaviour | State |
|------------------------|-------|
| `assetId` identity and the asset map | implemented |
| Public identifiers refused | implemented |
| `source`, `kind`, `horizontalAccuracy`, `altitude`, `verticalAccuracy` | implemented |
| Position stream, organisation-scoped | implemented |
| 2-legged organisation-scoped authorisation | implemented. Consumer clients are provisioned by KELT |
| `maxAge` on the established time, position cache | implemented |
| `maxSurface` | implemented |
| Verification with `TRUE`, `FALSE`, `PARTIAL` and `matchRate` | implemented |
| Authorisation below the organisation | not part of the profile |

## Responsibilities

This repository owns the profile, the schemas, the resolution logic and the
asset map endpoints. The KELT testbed owns the production asset map data, the
consumer clients and their `org` claims, and the private network: the Open5GS
core and the MEC platform.
