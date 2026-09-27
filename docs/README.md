# 5G Northbound

An open positioning stack that exposes the location of **assets** in a private
venue - tools, tags, pallets, forklifts - to applications, over the standard
[CAMARA Device Location API](https://camaraproject.org/). Sensing sources
(WiFi, UWB, vendor RTLS) are fused at the edge and served through one familiar
API. It runs unchanged from a laptop to a Kubernetes cluster, and new sources
plug in as new adapters. Written for developers and operators working with the
stack directly.

New here? Read the **[Overview](overview.md)** first - it gives the mental
model in one page.

---

## Where to start

| Goal | Path |
|------|------|
| **Understand what this is** | [Overview](overview.md) → [Architecture](architecture.md) |
| **Run it on your laptop** | repo `README.md` quick start (`make demo`) → [Architecture](architecture.md) |
| **Add a positioning source** | [Adapters](adapters.md) → [Vendor REST API](integrating-a-vendor-rest-api.md) → [Adapter registry](adapter-registry.md) |
| **Build a CAMARA client** | [Data contracts](data-contracts.md) → [API reference](api-reference.md) |
| **Map real devices (assets)** | [Asset registry](asset-registry.md) → [Data contracts](data-contracts.md) |
| **Author a venue (rooms, walls, anchors)** | [Blueprint vs bindings](blueprint-vs-bindings.md) → [Georeferencing](georeferencing.md) |
| **Deploy to Kubernetes** | [Deployment](deployment.md) → [Blueprint vs bindings](blueprint-vs-bindings.md) |
| **Change how positions fuse** | [Fusion strategies](fusion-strategies.md) |

---

## Concepts

Read these to understand how the system is designed.

| Document | Description |
|----------|-------------|
| [Overview](overview.md) | What it is, the sense → fuse → expose model, key concepts. Start here. |
| [Private-asset profile](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/README.md) | The CAMARA Device Location profile this stack implements: asset identity, source/altitude metadata, streaming, 2-legged org-scoped authz, and the base-contract conformance (`maxAge`, `maxSurface`, error codes) |
| [Architecture](architecture.md) | Services, request flow, adapter routing, coordinate frames; the 3GPP-to-CAMARA mapping |
| [Blueprint vs bindings](blueprint-vs-bindings.md) | Portable venue geometry vs per-venue secrets (BSSIDs, MACs) |
| [Georeferencing](georeferencing.md) | Anchoring the local metric frame to the world: datums, tile drift, N-point calibration |
| [Authentication](authentication.md) | How the browser apps sign in against the Keycloak realm: in-browser OIDC and the proxy-gated pattern |

## Guides

Task-focused, follow top to bottom.

| Document | Description |
|----------|-------------|
| [Adapters](adapters.md) | The HTTP contract every adapter implements, with a minimal Python skeleton |
| [Integrating a vendor REST API](integrating-a-vendor-rest-api.md) | Wrap a vendor cloud with the schema-driven `vendor-adapter`; the full identity chain |
| [Adapter registry](adapter-registry.md) | How adapters self-register, heartbeat, and route by `source` |
| [Asset registry](asset-registry.md) | The Asset Identity Map: asset structure, authoring, seeding, tenancy |
| [Fusion strategies](fusion-strategies.md) | Fusion algorithms and how to switch between them |
| [Deployment](deployment.md) | Images, environment variables, ConfigMap and Secret shapes, health probes |

## Reference

Look up exact formats once you know the model.

| Document | Description |
|----------|-------------|
| [Data contracts](data-contracts.md) | Exact wire formats across CAMARA, vendor extensions, engine, and the adapter contract |
| [Machine-readable contracts](contracts.md) | Every published contract (profiled spec, schemas, overlays) and its raw URL - how to fetch and pin |
| [API reference](api-reference.md) | One row per endpoint across every service |
| [Latency instrumentation](latency-instrumentation.md) | The per-hop latency trace: x-correlator propagation and the hop log-line contract |
| [Profile extensions](profile-extensions.md) | The surfaces beside CAMARA, how extension data is contained, and the core diagnostics vocabulary |

## Documentation map

Every topic has one document that owns it. The owner holds the facts, and
other documents link to it instead of restating them. To change a fact, change
it at its owner.

| Topic | Owner |
|-------|-------|
| What the stack is, the sense, fuse, expose model | [Overview](overview.md) |
| Services, request flow, coordinate frames | [Architecture](architecture.md) |
| The CAMARA private-asset profile: identity, extensions, authorisation model, conformance | [Private-asset profile](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/README.md) |
| Surfaces beside CAMARA and the diagnostics vocabulary | [Profile extensions](profile-extensions.md) |
| Published contract files, who governs each, the naming convention, how to fetch them | [Machine-readable contracts](contracts.md) |
| JSON examples of every wire body | [Data contracts](data-contracts.md) |
| The list of endpoints per service | [API reference](api-reference.md) |
| The adapter contract and how to write an adapter | [Adapters](adapters.md) |
| Adapter registration, health and routing | [Adapter registry](adapter-registry.md) |
| The schema-driven vendor adapter | [Integrating a vendor REST API](integrating-a-vendor-rest-api.md) |
| The Asset Identity Map | [Asset registry](asset-registry.md) |
| What is portable venue geometry and what is per-venue binding | [Blueprint vs bindings](blueprint-vs-bindings.md) |
| Anchoring the venue frame to the world | [Georeferencing](georeferencing.md) |
| Browser sign-in against the Keycloak realm | [Authentication](authentication.md) |
| Fusion algorithms | [Fusion strategies](fusion-strategies.md) |
| Images, environment, storage, probes | [Deployment](deployment.md) |
| Per-hop latency trace | [Latency instrumentation](latency-instrumentation.md) |
| Code conventions, constraints, commits | `AGENTS.md` at the repository root |
| Repository layout | `STRUCTURE.md` at the repository root |

---

The Kubernetes manifests live in the companion repository
[`kelt`](https://github.com/Jacobbista/kelt); this repo defines the contracts
those manifests consume. Repo conventions (code style, tests, security) are in
`AGENTS.md` at the repository root.
