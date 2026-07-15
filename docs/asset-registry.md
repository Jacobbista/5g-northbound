# Asset registry

The **Asset Identity Map** is the list of tracked things the platform knows
about — a UWB tag, a tool, a pallet, a forklift. It is the private-asset
equivalent of a subscriber directory, except an asset has no phone number: it
is identified by a business id the enterprise chooses (`pkg-4471`,
`forklift-7`).

The gateway is the authority for this registry, exactly as the engine is for
the blueprint. You read it with `GET /assets`, replace it with `PUT /assets`,
and it persists to a PVC-backed store. **At runtime it is never a mounted
file** — mounting one has shadowed live state before. The committed
`dev/assets.json` is a dev seed only.

## Structure

The contract is [`schema/asset.schema.json`](https://github.com/Jacobbista/5g-northbound/blob/main/schema/asset.schema.json)
(version `2`, pinned in `schema/VERSION`). One entry per asset:

| Field            | Req | Type / values                                        | Meaning |
|------------------|-----|------------------------------------------------------|---------|
| `asset_id`       | ✅  | `^[A-Za-z0-9._:-]{1,128}$`                            | First-class CAMARA id (`device.assetId`). A business id, **not** a phone number |
| `positioning_id` | ✅  | `^[A-Za-z0-9._:-]{1,128}$`                            | Internal id the engine routes on (`/position/{positioning_id}`) |
| `kind`           | ✅  | `uwb-tag` \| `tool` \| `pallet` \| `forklift` \| `asset` \| `ue` | Asset class, surfaced as profile `kind` |
| `source`         | ✅  | `wittra` \| `wifi` \| `fiveg` \| `gnss` \| `mock`    | Positioning modality / adapter, surfaced as profile `source` |
| `org`            | ✅  | `^[a-z0-9-]{1,64}$`                                   | Tenant. Joined against the token `org` claim — a consumer sees only its own |
| `label`          |     | string                                               | Human-readable name for UIs |
| `simulated`      |     | boolean (default `false`)                            | Wired to a synthetic source (mock). UIs show a `MOCK` badge |
| `metadata`       |     | free-form object                                     | Per-asset extras (e.g. `floor`, `bay`) |

The whole document is `{ "version": 2, "assets": [ … ] }`. Copy
[`dev/assets.json`](https://github.com/Jacobbista/5g-northbound/blob/main/dev/assets.json)
as your starting point:

```json
{
  "version": 2,
  "assets": [
    {
      "asset_id": "pkg-4471",
      "positioning_id": "wittra-tag-01",
      "kind": "pallet",
      "source": "wittra",
      "org": "fiskarheden",
      "label": "Wittra tag 01",
      "simulated": true,
      "metadata": { "floor": 0, "note": "Timber bundle" }
    }
  ]
}
```

## How an asset resolves to a position

`asset_id` is what a CAMARA consumer asks for; everything after it is internal.

```mermaid
flowchart LR
    A["CAMARA request<br/>device.assetId = pkg-4471"] --> G["camara-gateway<br/>look up asset in the map"]
    G -->|positioning_id = wittra-tag-01| E["positioning-engine<br/>/position/{positioning_id}"]
    E -->|route by source / registry / DEVICE_MAP| AD["adapter (wittra)"]
    AD --> V["vendor cloud / sensor"]
```

`positioning_id` joins to an adapter through the engine's
[adapter registry / routing](adapter-registry.md); `source` names which
modality answers (and how much to trust the fix). Full chain down to a vendor
REST API: [integrating a vendor REST API](integrating-a-vendor-rest-api.md).

## Adding a device

Runtime is authoritative, so add through the gateway — do **not** edit a file on
the running pod.

`PUT /assets` **replaces the whole map**. Never blind-write: read, merge your
new entry, write back.

```bash
# 1. read the current map
curl -s -H "Authorization: Bearer $JWT" $GW/assets > assets.json

# 2. add your asset to assets.json (keep version: 2)

# 3. write it back
curl -s -X PUT -H "Authorization: Bearer $JWT" \
     -H "Content-Type: application/json" \
     --data @assets.json $GW/assets
```

The KELT dashboard does this for you (the editor proxies it at `/api/assets`);
onboarding discovered tags is the dashboard's job, not the editor's.

### Seeding a fresh deployment

On first boot the store is empty. The gateway seeds it **once** from
`ASSET_SEED_FILE` (default `/app/config/assets.seed.json`), then persists to
`ASSET_STORE_FILE` (default `/app/data/assets.json`, the PVC) and never seeds
again. Mount your `dev/assets.json` shape as the seed for a cold start; after
that, all changes go through `PUT /assets`.

## Tenancy and sensitivity

`GET /assets` filters by the token's `org` claim — a consumer only ever sees
its own tenant's assets, and `GET /assets/{id}/details` returns `404` (not
`403`) for a cross-tenant id so existence never leaks.

The asset inventory is **sensitive** (Tier-1: org + asset list). It is
gitignored in dev and lives on a PVC in prod — never commit a real map. Only
the placeholder `dev/assets.json` is in the repo.
