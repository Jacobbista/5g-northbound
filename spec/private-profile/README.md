# CAMARA private-asset profile

A profile of the CAMARA Device Location family for **private industrial
networks tracking assets, not subscribers**. This repository is the
open-source reference implementation. The motivation and gap analysis are in
the position paper *"Private Networks, Public APIs: Exposing Hybrid
Positioning through CAMARA in Industrial 6G"* (RISE, 6GHYPE4Ind), included at
the repo root as `6GHYPE___SNCNW.pdf`.

The pinned upstream CAMARA OpenAPI documents under
[`../../services/camara-gateway/spec/`](../../services/camara-gateway/spec/)
are the source of truth and are **not hand-edited**. This profile is an
**overlay**: it documents the extensions the gateway implements on top of the
stock surface.

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
CAMARA endpoint. It accepts `assetId` (the extension) and the stock
`networkAccessIdentifier` as an asset alias, but **does not** accept
`phoneNumber`/MSISDN or IP identifiers - there is no subscriber path. That is
the right call for a factory tracking assets, and matches the paper's "asset
identity is first-class, do not borrow the MSISDN slot" decision.

The paper also envisions "a single API surface [that] can serve both public
and private". That is a **conceptual** property of the provider-agnostic data
model, not something this deployment can run, and the distinction matters:

- *Accepting* `phoneNumber` is trivial (it is a field on the device object).
- *Serving* a fix for it needs **network-based positioning** - an LMF computing
  the UE position from RAN measurements. This testbed has no LMF (Open5GS ships
  none) and the RAN is a closed commercial femtocell (BTI nCell F2240) that
  exposes no positioning measurements (no LPP/NRPPa). Network positioning is
  therefore out of scope on this hardware.

`phoneNumber` is therefore not accepted: a public identifier with no source
would return "no fix", an empty shell. The surface that runs end to end is the
private-asset profile.

The public half is a future integration gated on a positioning source - an LMF
plus a RAN that exposes measurements. Reaching it is a component swap rather
than a rearchitecture (a RAN with an LMF, open-RAN, or a simulator that exposes
positioning) and slots into the experimental-NF plan (`nf-platform-dev-plan`).
On the current hardware - a closed commercial femtocell with no positioning
measurements - it is out of scope. Were such a source present, the public half
would carry `phoneNumber` backed by it; the testbed limitation is recorded under
the KELT repo's `known-issues/` (no RAN-based positioning).

Note on roles, to avoid confusion: the gateway plays the **exposure** role
(NEF-like) and the engine plays the **positioning** role (LMF-like) for
non-3GPP sources - by design, this is the paper's thesis, not a missing NF. A
separate experimental-NF effort (free5GC NEF + LMF stub) is orthogonal to this
CAMARA-asset story and lives in its own plan.

## Extensions

### 1. Asset identity (gap 1)

The CAMARA `device` object carries a first-class **`assetId`**:

```json
{ "device": { "assetId": "pkg-4471" } }
```

- `assetId` is the canonical identifier. No MSISDN/IMSI/IP path exists.
- `networkAccessIdentifier` is accepted only as an optional **alias** using the
  asset scheme `<asset_id>@<org>.assets` (e.g. `pkg-4471@fiskarheden.assets`),
  for consumers constrained to a stock CAMARA field.

The gateway resolves `assetId` through the **Asset Identity Map** to a
`positioning_id` (engine routing) + tenant `org` + `kind`/`source` metadata.
No subscriber lookup. Schema: [`../../schema/asset.schema.json`](../../schema/asset.schema.json).

The map is authored over the network — `GET /assets`, `PUT /assets` on the
gateway, PVC-backed — exactly as the engine authors the blueprint via
`GET/PUT /blueprint`. Never a mounted file at runtime.

### 2. Source metadata + altitude (gaps 1/2)

The `Location` response gains optional fields (omitted when absent):

| field | meaning |
|-------|---------|
| `source` | positioning modality (`wittra`/`wifi`/`fiveg`/`gnss`/`mock`) — a UWB fix is trusted differently from a WiFi fix at the same radius |
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
(Org-scoped filtering arrives with the 2-legged authz work.)

### 4. Authorisation: 2-legged, org-scoped (gap 3)

No three-legged consent: in a factory the operator owns network + assets +
apps. Enterprise-issued tokens carry an `org` claim; the gateway joins it
against the asset's `org` so a consumer sees only its tenant's assets - on
retrieve/verify, `GET /assets`, `GET /capabilities`, and the stream. A
cross-tenant asset reads as 404 (no existence leak). The realm role
(`camara-location-read`) is reused; `org` is an orthogonal tenant dimension.

A token with no `org` claim sees everything. This is a **deliberate fail-open
bypass for the operator/admin token** (the dashboard's own token, intentionally
un-scoped) - not a default for consumers. Every consumer client MUST carry an
`org` claim, guaranteed at mint time (one per-consumer Keycloak client, KELT's
job). The trade-off is explicit: a consumer client misconfigured without the
claim falls back to operator scope rather than failing closed, so consumer
minting must always set `org`.

## Status

| Extension | State |
|-----------|-------|
| `assetId` identity + Asset Identity Map (`GET/PUT /assets`) | implemented |
| `source` / `kind` / `altitude` on `Location` | implemented |
| Streaming channel (asset-shaped `/positions/stream`) | implemented (org-scoped) |
| 2-legged `org`-scoped authz (retrieve/verify/assets/capabilities/stream) | implemented (per-consumer Keycloak clients = KELT) |

## Ownership (northbound ↔ KELT)

This repo owns the schemas, the resolution logic, the `GET/PUT /assets`
endpoint, and the profile. The KELT testbed owns the production asset registry
data (dashboard, persisted on a PVC), per-consumer Keycloak clients, the `org`
claim wiring, and the private-network setting (Open5GS core, MEC).
