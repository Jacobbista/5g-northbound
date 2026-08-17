# CAMARA private-asset profile

A profile of the CAMARA Device Location family for **private industrial
networks tracking assets, not subscribers**. This repository is the
open-source reference implementation. The motivation and gap analysis are in
the position paper *"Private Networks, Public APIs: Exposing Hybrid
Positioning through CAMARA in Industrial 6G"* (Eriksson et al., RISE,
6GHYPE4Ind).

The pinned upstream CAMARA OpenAPI documents under
[`../../services/camara-gateway/spec/`](../../services/camara-gateway/spec/)
are the source of truth and are **not hand-edited**. This profile is an
**overlay** on top of that stock surface.

## Formal specification

The schema deltas are a machine-readable [OpenAPI Overlay](https://spec.openapis.org/overlay/v1.0.0.html)
(OpenAPI Initiative, 1.0.0) applied to the pinned base - the base is never
edited:

- [`overlay-retrieval.yaml`](overlay-retrieval.yaml) - adds `assetId` to `Device`,
  removes the public-network identifiers, adds `source`/`kind`/`altitude`/
  `verticalAccuracy` to `Location`.
- [`overlay-verification.yaml`](overlay-verification.yaml) - the same asset-identity
  delta (the verification response is already `TRUE`/`FALSE`/`PARTIAL` in the base).

`make profile-spec` applies them and writes the profiled OpenAPI documents to
[`generated/`](generated/). Those files are committed so a client can pin a
single self-contained contract; CI regenerates them and fails if they drift from
the base + overlays (any Overlay tool, e.g. Redocly, produces the same result).
The authored contribution is still the base (pinned) plus these overlays.

The streaming channel is a WebSocket, outside OpenAPI's scope, so it is
formalised separately as [AsyncAPI 3.0](https://www.asyncapi.com/):

- [`asyncapi-stream.yaml`](asyncapi-stream.yaml) - the `/positions/stream` channel,
  the asset-shaped position-event message schema, and the token-in-query auth.

Together the overlays (request/response) and the AsyncAPI document (streaming)
cover the profile's whole wire surface. What stays in this document is only what
is **not** schema: the behavioural conformance -
`maxAge`, `maxSurface`, and the error codes (see
[Conformance](#conformance-with-the-base-camara-contract)) - which is semantics,
expressed in prose here exactly as CAMARA itself expresses it in its OpenAPI
descriptions.

## Why a profile

CAMARA was designed for public mobile networks: the operator is both the
source of the fix and the arbiter of identity and consent. Industrial
deployments break both assumptions. The tracked entities are assets (UWB tags,
tools, pallets, forklifts) with no MSISDN/IMSI/NAI; positioning is non-3GPP
(UWB/WiFi/GNSS fused at the edge) and independent of the core; and the factory
owns the network, the assets, and the apps, so three-legged consent collapses.

The data model already travels (a fix is a time-stamped circle/polygon, no
field names the underlying technology). Three concrete gaps remain. This
profile bridges them with modest, backwards-shaped extensions.

### Private-profile, not drop-in public CAMARA

This gateway is deliberately a **private-asset profile**, not a verbatim public
CAMARA endpoint: it accepts `assetId` (and the `networkAccessIdentifier` asset
alias) but rejects `phoneNumber`/MSISDN and IP identifiers - there is no
subscriber path. That matches the paper's "asset identity is first-class, do not
borrow the MSISDN slot".

Rejecting a public identifier is a design decision, not a shortcut. *Accepting*
`phoneNumber` is trivial; *serving* a fix for it would need network-based
positioning (a 3GPP source computing the UE position from radio measurements).
This profile positions **non-cellular assets** fused at the edge, so a public
identifier has no source behind it - it would only ever return "no fix". The
paper's "one surface for public and private" is a property of the
provider-agnostic data model; a public half is a separate, source-gated
integration, out of scope here.

## Extensions

### 1. Asset identity (gap 1)

The CAMARA `device` object carries a first-class **`assetId`**:

```json
{ "device": { "assetId": "pkg-4471" } }
```

- `assetId` is the canonical identifier. No MSISDN/IMSI/IP path exists.
- `networkAccessIdentifier` is accepted only as an optional **alias** using the
  asset scheme `<asset_id>@<org>.assets` (e.g. `pkg-4471@acme.assets`),
  for consumers constrained to a stock CAMARA field.
- A request carrying a public-network identifier (`phoneNumber`, `ipv4Address`,
  `ipv6Address`) is rejected with `422 UNSUPPORTED_IDENTIFIER`, not a generic
  error. The profile is **response-compatible** with a stock CAMARA client (the
  response validates against the base schema) but **request-incompatible** by
  design: it will not resolve a subscriber identifier.

The gateway resolves `assetId` through the **Asset Identity Map** to a
`positioning_id` (engine routing) + tenant `org` + `kind`/`source` metadata.
No subscriber lookup. Schema: [`../../schema/asset.schema.json`](../../schema/asset.schema.json).

The map is authored over the network - `GET /assets`, `PUT /assets` on the
gateway, PVC-backed - exactly as the engine authors the blueprint via
`GET/PUT /blueprint`. Never a mounted file at runtime.

### 2. Source metadata + altitude (gaps 1/2)

The `Location` response gains optional fields (omitted when absent):

| field | meaning |
|-------|---------|
| `source` | positioning modality (`wittra`/`wifi`/`fiveg`/`gnss`/`synthetic`) - a UWB fix is trusted differently from a WiFi fix at the same radius |
| `kind` | asset class (`uwb-tag`/`tool`/`pallet`/`forklift`/…) |
| `altitude` | fused vertical position (m); multi-floor / stacked storage that CAMARA's 2D Circle drops |
| `verticalAccuracy` | vertical 1-sigma (m), when available |

### 3. Streaming delivery (gap 2)

Pull `POST /location-retrieval/v0.5/retrieve` stays the contract. A streaming
channel is offered **alongside** it for moving assets (forklifts, tools):
`ws[s]://<gateway>/positions/stream?token=<jwt>`. The gateway enriches the
engine's broadcast into **asset-shaped events** (`assetId` + `source`/`kind`/
`org` + lat/lon/accuracy/altitude), and drops any positioning id with no
registered asset behind it - the same no-raw-id rule as the pull path.
Org-scoped, like the pull path. Formalised as AsyncAPI:
[`asyncapi-stream.yaml`](asyncapi-stream.yaml).

### 4. Authorisation: 2-legged, org-scoped (gap 3)

No three-legged consent: in a factory the operator owns network + assets + apps,
so the consent leg has no counterpart - an asset is not an OAuth subject and
cannot log in or consent. Two orthogonal axes describe the model.

**Authentication (how the caller proves itself).** The CAMARA consumer is a
machine using the OAuth2 `client_credentials` grant (2-legged): the token
represents the calling application, not a user. This keeps the stock CAMARA "get
a token, send `Bearer`" pattern - only the token is client-scoped rather than
user-scoped. Reducing further to a single fully-internal caller (1-legged mTLS
or an enterprise key, no token server) is possible but is not used here: it
would drop OAuth2 and lose the ability to distinguish multiple consumers.

**Authorisation (what a proven caller may see).** Two layers: the realm role
`camara-location-read` is the coarse capability (may it read location at all);
the `org` claim is the tenant scope, joined against each asset's `org` so a
consumer sees only its tenant's assets - on retrieve/verify, `GET /assets`,
`GET /capabilities`, and the stream. A cross-tenant asset reads as 404 (no
existence leak).

A token with no `org` claim sees everything. This is a **deliberate fail-open
bypass for the operator/admin token** (the dashboard's own, intentionally
un-scoped), not a default for consumers: every consumer client MUST carry an
`org`, guaranteed at mint time. The trade-off is explicit - a consumer client
misconfigured without the claim falls back to operator scope rather than failing
closed, so consumer minting must always set `org`.

**Who owns what.** KELT provisions the IAM (Keycloak realm, per-consumer OIDC
clients, roles, and the `org` attribute on each principal); this gateway is the
enforcement point (validate the JWT, check the role, join `org` against the
Asset Identity Map). The gateway is flow-agnostic - it checks role + `org`, not
how the token was minted - so a human-facing UI on the 3-legged PKCE flow is
served by the same policy. The profile *defines* the CAMARA consumer as
2-legged; the 3-legged path exists only for browser UIs, not for the API
consumer.

**Granularity is org-level.** Restricting a consumer to a subset of assets
*within* an org (e.g. a third-party tooling-vendor cloud that should see only
the tools it services) is a finer authorisation layer - compatible with CAMARA,
motivated by the paper's third-party trust boundary, but built on neither side
and not security-hardened. It is **named future work**, not a gap: the org
boundary is a complete, deliberate scope. Adversarial multi-tenant isolation
(token forgery, side channels, resource isolation) is likewise implemented at
the functional level and not security-assessed in this work.

## Conformance with the base CAMARA contract

Beyond the extensions above, the gateway honours the stock request parameters
and error semantics of the pinned r3.2 contract. The profile follows the
standard fully, not in part: a parameter CAMARA defines is either implemented or
named as out of scope, never silently ignored.

### Freshness: `maxAge`

`maxAge` (seconds) bounds how old an accepted fix may be, measured against the
fix's own `lastLocationTime`:

- **absent** - any age is acceptable; the fix is returned with its
  `lastLocationTime`.
- **`N`** - a fix older than `N` seconds cannot be served. When even a freshly
  fetched fix is older than `N`, the request fails with
  `422 LOCATION_RETRIEVAL.UNABLE_TO_FULFILL_MAX_AGE` (the `LOCATION_VERIFICATION.*`
  code on verify).
- **`0`** - a fresh calculation is requested; the cache is bypassed and the live
  source is queried. The sources are pull-based (the gateway fetches the latest
  vendor/engine fix; it cannot force a new computation), so `0` returns the
  freshest fix available rather than failing on non-zero age.

A small position cache backs this: the last fix per `(positioning_id, source)`
is reused only while it still satisfies the request's `maxAge` (or, absent one,
`LOCATION_CACHE_TTL_S`, default 5 s). Freshness is judged by `lastLocationTime`,
so a single age metric drives both cache reuse and the `maxAge` contract - a
stale fix is never served as current.

### Area size: `maxSurface`

`maxSurface` (m²) bounds the accepted area. The reported circle has area
`π·radius²`; when it exceeds `maxSurface` the request fails with
`422 LOCATION_RETRIEVAL.UNABLE_TO_FULFILL_MAX_SURFACE`. The gateway cannot make a
fix more precise than its source reports, so this is a reject-if-too-coarse
check, as the spec intends.

### Verification result

`POST /location-verification/v3/verify` classifies using the fix's own
**uncertainty circle** (centre + accuracy radius) against the queried area:
`TRUE` when it lies fully inside, `FALSE` when fully outside, `PARTIAL` when it
straddles the boundary. For `PARTIAL`, `matchRate` (1-99) is the percentage of
the fix circle that falls inside the area.

### Error codes

CAMARA-generic codes are bare; API-specific codes are namespaced with the API,
per Commonalities. Every response (success or error) carries an `x-correlator`
header, echoed from the request or minted when absent.

| HTTP | `code` | When |
|------|--------|------|
| 401 | `UNAUTHENTICATED` | missing / invalid / expired token |
| 403 | `PERMISSION_DENIED` | token lacks the `camara-location-read` role |
| 404 | `IDENTIFIER_NOT_FOUND` | unknown `assetId`, or a cross-tenant one (no existence leak) |
| 422 | `MISSING_IDENTIFIER` | no `device`, or no identifier in it |
| 422 | `UNSUPPORTED_IDENTIFIER` | a public-network identifier was supplied |
| 422 | `LOCATION_{RETRIEVAL,VERIFICATION}.UNABLE_TO_LOCATE` | no fix for the asset |
| 422 | `LOCATION_{RETRIEVAL,VERIFICATION}.UNABLE_TO_FULFILL_MAX_AGE` | no fix fresh enough for `maxAge` |
| 422 | `LOCATION_RETRIEVAL.UNABLE_TO_FULFILL_MAX_SURFACE` | area larger than `maxSurface` |
| 502 | `BAD_GATEWAY` | engine reachable but returned 5xx |
| 503 | `UNAVAILABLE` | engine unreachable |

One deliberate simplification: a malformed or out-of-range request body returns
`400 INVALID_ARGUMENT` rather than distinguishing `OUT_OF_RANGE`; both are valid
CAMARA 400 codes.

## Status

| Extension / behaviour | State |
|-----------|-------|
| `assetId` identity + Asset Identity Map (`GET/PUT /assets`) | implemented |
| Public identifiers rejected (`UNSUPPORTED_IDENTIFIER`) | implemented |
| `source` / `kind` / `altitude` / `verticalAccuracy` on `Location` | implemented |
| Streaming channel (asset-shaped `/positions/stream`, org-scoped) | implemented |
| 2-legged `org`-scoped authz (retrieve/verify/assets/capabilities/stream) | implemented (per-consumer Keycloak clients = KELT) |
| `maxAge` freshness + position cache | implemented |
| `maxSurface` area bound | implemented |
| Verification `TRUE` / `FALSE` / `PARTIAL` with `matchRate` | implemented |
| Per-asset (sub-org) authorisation | future work |

## Ownership (northbound ↔ KELT)

This repo owns the schemas, the resolution logic, the `GET/PUT /assets`
endpoint, and the profile. The KELT testbed owns the production asset registry
data (dashboard, persisted on a PVC), per-consumer Keycloak clients, the `org`
claim wiring, and the private-network setting (Open5GS core, MEC).
