# Adapter registry

The engine keeps the list of adapters it can call. Adapters add themselves to
it, so an adapter can run anywhere that reaches the engine, including an edge
node over the data network.

## Registration

An adapter sends `POST /adapters` to the engine at start with
`{name, baseUrl, kind, instance, capabilities}` and repeats it every
`ADAPTER_HEARTBEAT_S` (15 s by default). The request is idempotent. On a clean
shutdown the adapter sends `DELETE /adapters/{name}?instance=<instance>`. The
engine removes an adapter that has not announced itself for `ADAPTER_TTL_S`
(45 s by default).

`instance` identifies the running process. Several instances can serve one
name: the old and the new pod of a rolling update, or replicas. The engine
keeps the name registered while any of its instances announces itself, and a
deregistration removes only the instance that sends it. In a rolling update
the new pod registers before the old one stops, so the source stays
registered throughout, provided every instance announces the same `baseUrl`,
the Service they share. A deregistration without an instance, from an adapter
older than 0.19.3, does not remove a name that live instances still announce,
and answers `status: kept`. The engine does not store self-registered entries:
after an engine restart each adapter is missing until its next heartbeat.
`GET /adapters` on the engine reports the number of live `instances` per
adapter.

`name` is the adapter's `ADAPTER_NAME`. `kind` is the image family (`wifi`,
`vendor`, `synthetic`), read from the image's own `adapter.contract.yaml`.
`capabilities` is the declaration described in
[adapters](adapters.md#what-an-adapter-declares), validated against
[`schema/adapter-announcement.schema.json`](https://github.com/Jacobbista/5g-northbound/blob/main/schema/adapter-announcement.schema.json).

`ADAPTER_URLS` on the engine (`name=url` pairs) seeds the registry once, when
it is empty, for adapters that do not register themselves. The engine stores
seeded entries in `ADAPTER_REGISTRY_PATH` (on the same volume as the
blueprint) and never removes them for silence. Self-registered entries are not
stored, because they return within one heartbeat after an engine restart.

| `registeredVia` | Origin | Stored | Removed for silence |
|-----------------|--------|--------|---------------------|
| `self` | `POST /adapters` | no | yes |
| `seed` | `ADAPTER_URLS` | yes | no |

## Health

Two signals are independent. The heartbeat tells whether the adapter process
reaches the engine. The polls tell whether the adapter answers the engine: a
vendor adapter can announce itself while its vendor cloud is down, so its
measurements fail. `state` combines them:

| `state` | Meaning |
|---------|---------|
| `live` | announcing (or seeded) and answering |
| `unreachable` | registered, but the engine's calls fail and it is backing off |
| `stale` | self-registered and silent for longer than one heartbeat, not yet removed |

The engine's `GET /adapters` returns each entry with `name`, `baseUrl`, `kind`,
`registeredVia`, `lastSeenSAgo`, `failCount`, `inCooldown`,
`cooldownSecondsRemaining`, `state` and `capabilities`. It is an internal
surface for operator tools. The gateway's `GET /adapters` gives applications
`name`, `state` and `capabilities` only.

The engine has no authentication. It is reachable only inside the cluster.

## Routing

The gateway asks for a position with the source of the capability it resolves:
`GET /position/{positioningId}?source={source}`. The engine calls the adapter
whose `ADAPTER_NAME` equals that source. So the one rule an operator must keep
is that a capability's `source` equals the `ADAPTER_NAME` of the adapter
serving it.

Without a `source`, or with one no adapter matches, the engine reads the
optional `DEVICE_MAP` (`positioningId=adapterName` pairs, normally unset), and
otherwise asks every adapter and fuses the answers. An adapter answers `404`
for a device it does not serve.

The position stream uses the same registry. The engine asks each adapter that
declares `devices` for its device list, and broadcasts each id with the
adapter that reported it. When two adapters report the same id, an `observed`
report wins over an `inventory` one, then the adapter name in alphabetical
order. `DEVICE_IDS` seeds the broadcast only while no adapter declares
`devices`.
