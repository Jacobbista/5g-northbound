# Asset registry

The asset map is the list of assets the gateway knows. An asset has no phone
number. It is named by an `assetId` the organisation chooses, such as
`pkg-4471` or `forklift-7`, and carries one or more capabilities, each a way of
locating it. The gateway holds the map, serves it on `GET /assets`, replaces it
on `PUT /assets`, and persists it on its own volume.

## The document

The contract is
[`schema/asset.schema.json`](https://github.com/Jacobbista/5g-northbound/blob/main/schema/asset.schema.json),
version 4. The document is `{"version": 4, "assets": [...]}`.

| Asset field | Required | Content |
|-------------|----------|---------|
| `assetId` | yes | `^[A-Za-z0-9._:-]{1,128}$`, the CAMARA `device.assetId` |
| `kind` | yes | the asset class, published as profile `kind` |
| `org` | yes | `^[a-z0-9-]{1,64}$`, the organisation that owns the asset, matched against the token's `org` claim |
| `capabilities` | yes | one or more `{source, positioningId}` |
| `label` | no | a name for user interfaces |
| `metadata` | no | a free object, such as `floor` or `bay` |

| Capability field | Content |
|------------------|---------|
| `source` | the name of the adapter that serves this capability |
| `positioningId` | `^[A-Za-z0-9._:-]{1,128}$`, the id that adapter knows the asset by |

A physical thing is a different id to each source, so each capability carries
its own `positioningId`. The seed in
[`dev/assets.json`](https://github.com/Jacobbista/5g-northbound/blob/main/dev/assets.json)
has a single-capability pallet and a robot located by WiFi and UWB:

```json
{
  "version": 4,
  "assets": [
    {
      "assetId": "pkg-4471",
      "kind": "pallet",
      "org": "acme",
      "capabilities": [{ "source": "wittra", "positioningId": "wittra-tag-01" }],
      "label": "Wittra tag 01",
      "metadata": { "floor": 0, "note": "Timber bundle" }
    },
    {
      "assetId": "robot-2",
      "kind": "forklift",
      "org": "acme",
      "capabilities": [
        { "source": "wifi", "positioningId": "wifi-asset-02" },
        { "source": "wittra", "positioningId": "wittra-tag-02" }
      ],
      "label": "Mobile robot 2"
    }
  ]
}
```

For each capability of `robot-2` the gateway asks the engine for the position
of that `positioningId` from that `source`, then fuses the answers into one
CAMARA `Location` ([fusion strategies](fusion-strategies.md)). The first
capability is the primary one. Device diagnostics and placement use it, and the
position stream and the asset details report its `positioningId` and `source`
beside the fused position.

## Checks on write

`PUT /assets` refuses a document that breaks one of these rules, with `422`:

| Code | Rule |
|------|------|
| `DUPLICATE_POSITIONING_ID` | a `positioningId` appears once in the whole map, since the position stream maps it back to one asset |
| `UNKNOWN_SOURCE` | a `source` is served by an adapter registered with the engine |
| `UNKNOWN_KIND` | a `kind` is advertised by a registered adapter in its `kinds` |

A `source` or `kind` the stored map already uses is accepted, so the assets of
an adapter that is down stay writable. When the engine cannot be reached, the
source and kind checks are skipped. The checks run on write only: a stored map
is not validated again when it is read.

## Writing the map

`PUT /assets` replaces the whole map. Read it, change it, write it back:

```bash
curl -s -H "Authorization: Bearer $JWT" "$GW/assets" > assets.json
# edit assets.json
curl -s -X PUT -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
     --data @assets.json "$GW/assets"
```

Only an operator token, which carries no `org` claim, writes. A token with an
`org` claim receives `403 PERMISSION_DENIED`. The KELT dashboard writes the map
with its operator token.

The gateway keeps the map in `ASSET_STORE_FILE` (`/app/data/assets.json`),
which belongs on a persistent volume. When that file is absent at start, the
gateway copies `ASSET_SEED_FILE` (`/app/config/assets.seed.json`) into it once.
Without either, it starts with an empty map.

## Onboarding discovered devices

An adapter that advertises the `devices` capability lists the devices its
source knows on `GET /devices`. The engine merges these lists, and the gateway
serves on `GET /assets/discoverable` the devices whose id is not yet a
`positioningId` in the map. The list spans every organisation, so only an
operator token reads it. The KELT Assets page offers each candidate for
onboarding: the candidate's `id` becomes a `positioningId`, its `source` the
capability's source, and the operator adds `assetId`, `kind`, `org` and
`label`. Nothing is onboarded without a `PUT /assets`.

| Candidate field | Content |
|-----------------|---------|
| `id`, `source` | the device id and the adapter that reports it |
| `origin` | `inventory` for a list the vendor maintains (vendor-adapter), `observed` for a device seen in recent traffic (wifi-adapter) |
| `role` | `asset` or `infrastructure`, when the source classifies its devices |
| `sourceClass` | the positioning technology, when the source states it |
| `deviceType`, `label` | as the source reports them |
| `lastCommunicationTime` | when the device last communicated with its source, RFC 3339 |

A device with `role: infrastructure` is a fixed sensor, such as a UWB anchor or
a gateway: it feeds positioning and is not an asset. A source that does not
classify leaves `role` out. The vendor-adapter classifies from its schema's
`classify` block
([the device list](integrating-a-vendor-rest-api.md#the-device-list)). The
synthetic-adapter reports its walking tags as assets and its anchors as
infrastructure.

## Organisations

`GET /assets` returns only the assets of the token's `org`. For an asset of
another organisation, `GET /assets/{assetId}/details` and the CAMARA endpoints
answer `404`, as for an asset that does not exist.

The map lists an organisation's assets, so a real map is never committed. The
repository holds only the placeholder `dev/assets.json`.
