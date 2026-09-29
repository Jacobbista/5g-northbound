# 5G Northbound

The reference implementation of the CAMARA private-asset profile: the location
of assets in a private venue, such as tools, pallets and forklifts, served
through the CAMARA Device Location APIs. Positions come from on-site sources
such as WiFi, UWB or a vendor's positioning cloud, and are fused at the edge.
The [overview](overview.md) introduces the model and its terms.

## Where to start

| Goal | Pages |
|------|-------|
| Understand the system | [Overview](overview.md), then [Architecture](architecture.md) |
| Run it on a laptop | the repository [README](https://github.com/Jacobbista/5g-northbound/blob/main/README.md) |
| Build a CAMARA client | the [profile](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/README.md), then [Data contracts](data-contracts.md) |
| Add a positioning source | [Adapters](adapters.md), then [Integrating a vendor REST API](integrating-a-vendor-rest-api.md) |
| Register assets | [Asset registry](asset-registry.md) |
| Describe a venue | [Blueprint and bindings](blueprint-vs-bindings.md), then [Georeferencing](georeferencing.md) |
| Deploy on Kubernetes | [Deployment](deployment.md) |

## Documentation map

Each topic has one page that owns it. The other pages link to it and do not
restate it.

| Topic | Owner |
|-------|-------|
| The model and its terms | [Overview](overview.md) |
| Services, request flow, coordinate frame, time | [Architecture](architecture.md) |
| The private-asset profile: identity, extensions, authorisation, conformance | [Profile](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/README.md) |
| Endpoints beside CAMARA, diagnostics vocabulary | [Profile extensions](profile-extensions.md) |
| Browser sign-in | [Authentication](authentication.md) |
| The adapter contract, declarations, writing an adapter | [Adapters](adapters.md) |
| The schema-driven vendor adapter | [Integrating a vendor REST API](integrating-a-vendor-rest-api.md) |
| Adapter registration, health and routing | [Adapter registry](adapter-registry.md) |
| The asset map and onboarding | [Asset registry](asset-registry.md) |
| Venue blueprint, WiFi bindings and calibration | [Blueprint and bindings](blueprint-vs-bindings.md) |
| Tie between the venue frame and WGS84 | [Georeferencing](georeferencing.md) |
| Fusion in the engine and the gateway | [Fusion strategies](fusion-strategies.md) |
| Images, configuration, storage, probes | [Deployment](deployment.md) |
| Published contract files, surface governance, naming | [Machine-readable contracts](contracts.md) |
| An example of every body | [Data contracts](data-contracts.md) |
| Every route of every service | [API reference](api-reference.md) |
| Per-hop latency log | [Latency instrumentation](latency-instrumentation.md) |
| Environment contract format | [`deploy/contracts`](https://github.com/Jacobbista/5g-northbound/blob/main/deploy/contracts/README.md) |
| Code conventions and commits | `AGENTS.md` at the repository root |
| Repository layout | `STRUCTURE.md` at the repository root |

The Kubernetes manifests of the testbed are in the
[KELT](https://github.com/Jacobbista/kelt) repository.
