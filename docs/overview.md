# Overview

What this system is, why it is built this way, and how the pieces fit. Read
this before the other documents.

## What this system does

It exposes **where things are** inside a private venue - tools, tags, pallets,
forklifts - to applications, over the standard
[CAMARA Device Location API](https://camaraproject.org/). The things it tracks
are **assets**, not phones: they are located by on-site sensing (WiFi, UWB, and
others), fused at the edge, and served through one familiar API.

It runs unchanged from a laptop (`docker compose`) to a Kubernetes cluster. New
positioning technologies plug in as new **adapters**; the engine and gateway
never change.

## The mental model: sense, fuse, expose

Three roles, left to right:

```mermaid
flowchart LR
    W["WiFi adapter"] --> E
    U["UWB / vendor adapter"] --> E
    M["mock adapter"] --> E
    E["positioning-engine<br/>fuses sources · owns coordinates"] --> G
    G["camara-gateway<br/>CAMARA API · identity · tenant auth"] --> C["consumer app"]
    ED["placement-editor<br/>author the venue"] -. blueprint .-> E
```

- **Adapters sense.** Each positioning technology is its own service speaking
  one tiny HTTP contract (`GET /measurement/{id}`). WiFi RSSI, a vendor UWB
  cloud, a synthetic mock - all look the same to the engine.
- **The engine fuses.** It merges the measurements, owns the coordinate frame,
  and converts to WGS84. It is the authority for the venue **blueprint**.
- **The gateway exposes.** It speaks CAMARA to consumers, resolves identity,
  and gates each consumer to its tenant.

That separation is the whole point: a new sensing technology is a new adapter,
nothing upstream changes.

## Assets, not subscribers

CAMARA was designed for public mobile networks, where a device is a phone
identified by a number. Here the tracked entity is an **asset** with a business
id (`assetId`, e.g. `pkg-4471`) - never a phone number. This is the
**private-asset profile**; the gateway resolves `assetId` to a positioning
source and serves a normal CAMARA `Location`. See
[the profile](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/README.md)
for the full rationale.

## Key concepts

| Concept | In one line | Detail |
|---------|-------------|--------|
| **Adapter** | A positioning source behind one HTTP contract | [adapters.md](adapters.md) |
| **Adapter registry** | Adapters self-register with the engine; routing follows the asset's `source` | [adapter-registry.md](adapter-registry.md) |
| **Blueprint vs bindings** | Portable venue geometry (committable) vs per-venue secrets like BSSIDs (never committed) | [blueprint-vs-bindings.md](blueprint-vs-bindings.md) |
| **Identity chain** | `assetId` → `positioning_id` → adapter → vendor fix | [integrating-a-vendor-rest-api.md](integrating-a-vendor-rest-api.md#identity-resolution-from-a-camara-assetid-to-a-vendor-fix) |
| **Coordinate frames** | Room-local (editor) vs floor-plan north-up (engine) vs WGS84 (gateway) | [architecture.md](architecture.md) |

## Where to go next

| You want to… | Start at |
|--------------|----------|
| Run it on your laptop | the repo `README.md` quick start (`make demo`) |
| Understand the design in depth | [architecture.md](architecture.md) |
| Add a positioning source | [adapters.md](adapters.md) → [integrating-a-vendor-rest-api.md](integrating-a-vendor-rest-api.md) |
| Build a CAMARA client | [data-contracts.md](data-contracts.md) → [api-reference.md](api-reference.md) |
| Deploy to Kubernetes | [deployment.md](deployment.md) |
