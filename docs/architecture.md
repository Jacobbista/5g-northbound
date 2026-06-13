# Architecture

The 5G Northbound stack exposes device location to third-party applications over the CAMARA Device Location API while abstracting the underlying positioning technology. It is the northbound capability-exposure layer of a 5G research testbed built on [Open5GS](https://open5gs.org/) and Kubernetes (k3s).

## System overview

```mermaid
flowchart LR
  subgraph client["Client side"]
    BR(["Browser"])
    EDGE(["Edge devices<br/>(Pi WiFi scanner, …)"])
  end

  subgraph public["Public images, this repository"]
    DEMO["positioning-demo<br/>React + Three.js · CAMARA consumer"]
    EDIT["placement-editor<br/>operator UI · owns layout.json"]
    GW["camara-gateway<br/>FastAPI · JWT · device map"]
    ENG["positioning-engine<br/>thin fusion · WGS84"]
    WIFI["wifi-positioning<br/>RSSI multilateration"]
    MOCK["mock-positioning<br/>random walk"]
    REST["rest-adapter<br/>schema-driven REST translator"]
    MWIT["mock-wittra<br/>demo-only Wittra cloud fake"]
  end

  subgraph private["Private images (separate repos)"]
    VENDOR["vendor adapter<br/>e.g, proprietary SDK / NDA"]
  end

  subgraph vendor_cloud["Vendor clouds (third-party)"]
    WITTRA[("Wittra cloud<br/>api.wittra.se")]
  end

  subgraph identity["Identity / 5G core"]
    KC[("Keycloak<br/>OIDC + JWKS")]
    SMF[("Open5GS SMF<br/>session state")]
  end

  BR -- "PKCE login" --> KC
  BR -- "CAMARA REST<br/>(Bearer JWT)" --> DEMO
  DEMO -- "POST /location-retrieval/v0.5/retrieve" --> GW
  GW -- "JWKS validate" --> KC
  GW -- "GET /position/{id}" --> ENG
  GW -. "session lookup" .-> SMF
  ENG -- "GET /measurement/{id}<br/>ADAPTER_URLS" --> WIFI
  ENG -- "GET /measurement/{id}<br/>ADAPTER_URLS" --> MOCK
  ENG -- "GET /measurement/{id}<br/>ADAPTER_URLS" --> REST
  ENG -- "GET /measurement/{id}<br/>ADAPTER_URLS" --> VENDOR
  REST -- "GET /v1/.../devices/{id}<br/>(per schema)" --> WITTRA
  REST -. "demo only" .-> MWIT
  EDGE -- "POST /ingest/wifi-scan<br/>(5G data network)" --> WIFI

  LAYOUT[("layout.json<br/>shared volume / ConfigMap")]
  EDIT -- "PUT /api/layout" --> LAYOUT
  LAYOUT -. "GET /layout.json" .-> DEMO
  LAYOUT -. "floor plan ConfigMap" .-> ENG
```

`positioning-demo` is the **end-user / CAMARA consumer**. `placement-editor` is the **operator-facing** sibling that writes the layout JSON those consumers read; the two never talk to each other directly, only through the shared file artefact.

Devices are generic assets: UWB tags, WiFi clients, 5G UEs, anything with a stable identifier. Each positioning *technology* is its own pod that speaks a single HTTP contract; the engine fuses whichever adapter URLs are listed in its configuration. `ADAPTER_URLS` is a comma-separated list of `name=url` entries; `DEVICE_MAP` optionally pins a device to one named adapter. With no adapters configured, the engine produces no measurements. Deploy at least one adapter (the [`mock-positioning`](../mocks/mock-positioning/) reference is the simplest path for development).

### Request flow: one CAMARA call, end to end

```mermaid
sequenceDiagram
  autonumber
  participant App as CAMARA client<br/>(positioning-demo)
  participant GW as camara-gateway
  participant KC as Keycloak
  participant ENG as positioning-engine
  participant A1 as wifi-positioning
  participant A2 as mock-positioning

  App->>GW: POST /location-retrieval/v0.5/retrieve<br/>{ device.phoneNumber }
  GW->>KC: GET JWKS (cached)
  KC-->>GW: keys
  GW->>GW: validate JWT + role<br/>map phoneNumber → device_id
  GW->>ENG: GET /position/{device_id}

  par fan-out (concurrent)
    ENG->>A1: GET /measurement/{device_id}
    A1-->>ENG: 200 Measurement (local)<br/>or 404
  and
    ENG->>A2: GET /measurement/{device_id}
    A2-->>ENG: 200 Measurement (local)<br/>or 404
  end

  ENG->>ENG: normalise wgs84→local if needed<br/>run FUSION_STRATEGY<br/>local→WGS84 via gps_origin
  ENG-->>GW: EnginePosition (lat/lon, accuracy, strategy)
  GW-->>App: CAMARA Location { area.center, radius }
```

### Adapter routing: how the engine picks who to call

```mermaid
flowchart TD
  REQ([GET /position/device_id]) --> Q{device_id<br/>in DEVICE_MAP?}
  Q -- yes --> ONE[poll the single named adapter only]
  Q -- no  --> ALL[poll every adapter in ADAPTER_URLS]
  ONE --> COLLECT[collect responses · 404 = drop · timeout = drop]
  ALL --> COLLECT
  COLLECT --> NORM[normalise WGS84 replies → local frame<br/>via floor_plan.gps_origin]
  NORM --> FUSE[run FUSION_STRATEGY<br/>weighted_avg · kalman · …]
  FUSE --> PROJ[project local → WGS84]
  PROJ --> OUT([EnginePosition northbound])
```

## Services

| Service              | Role                                                                  | Repository path                          |
|----------------------|-----------------------------------------------------------------------|------------------------------------------|
| `camara-gateway`     | CAMARA Location Retrieval v0.5 and Location Verification v3 endpoints; JWT validation against Keycloak; cross-technology device-identity mapping | [`services/camara-gateway/`](../services/camara-gateway/) |
| `positioning-engine` | Fuses measurements from configured adapters; runs the selected fusion strategy; converts local coordinates to WGS84; serves the northbound contract consumed by the gateway | [`services/positioning-engine/`](../services/positioning-engine/) |
| `wifi-positioning`   | Reference positioning adapter: WiFi RSSI multilateration over a fixed AP map; receives scans on the 5G data network                            | [`services/wifi-positioning/`](../services/wifi-positioning/) |
| `mock-positioning`   | Reference positioning adapter: synthetic random walk inside the floor bounds. Produces continuous motion without a real measurement source, used by the local demo and as a generic adapter template | [`mocks/mock-positioning/`](../mocks/mock-positioning/) |
| `positioning-demo`   | Browser MEC application. Keycloak PKCE login, polls the CAMARA gateway (`/devices` for discovery, `/devices/{id}/details` per device), renders them on a 3D floor plan. Read-only consumer; never mutates server state | [`services/positioning-demo/`](../services/positioning-demo/) |
| `placement-editor`   | Operator-facing service, reads/writes the floor-plan / AP layout JSON via `GET/PUT /api/layout`. Runs alongside (not inside) the demo and is the artefact pulled by the testbed dashboard. Distinct realm role (`placement-admin`) when auth is wired in | [`services/placement-editor/`](../services/placement-editor/) |

Edge clients (for example, the Raspberry Pi WiFi scanner; see [`edge/wifi-scanner/README.md`](../edge/wifi-scanner/README.md) for the deploy flow) are not deployed by Kubernetes. They run on the device and reach the cluster over the 5G data network.

## Mapping to 3GPP and CAMARA reference architecture

The canonical 3GPP location-exposure chain is:

```
[Application] ──CAMARA──► [CAMARA Gateway] ──Nnef──► [NEF] ──Nlmf──► [LMF] ──► RAN / UE
```

This stack collapses that chain to fit a research testbed where Open5GS does not ship a full NEF or LMF:

| 3GPP / CAMARA role              | This repository                                            | Notes |
|---------------------------------|------------------------------------------------------------|-------|
| Application (API consumer)      | `positioning-demo` (any CAMARA client also works)          | PKCE login, polls `POST /location-retrieval/v0.5/retrieve` |
| CAMARA Gateway + NEF            | `camara-gateway`                                           | Single service: CAMARA REST surface, JWT, device-identity mapping. Geometry-agnostic |
| LMF                             | `positioning-engine`                                       | Thin fusion of 3GPP and non-3GPP sources via the HTTP adapter contract; fusion strategy is pluggable (see [`fusion-strategies.md`](fusion-strategies.md), baseline is `weighted_avg`); normalises to WGS84 |
| RAN / UE measurements           | Adapter pods (`wifi-positioning` in repo; vendor adapters as private images) | Each adapter is its own pod implementing `GET /measurement/{id}`: see [`adapters.md`](adapters.md) |
| AMF / SMF session state         | Open5GS SMF (mocked locally by `dev/mock_smf.py`)          | Provides UE session info (IMSI, IPv4, `up_cnx_state`) for cross-tech identity resolution |

The external contracts (CAMARA REST) are standard; the internal decomposition is a deployment choice and can be re-split into separate NEF and LMF services later without breaking northbound consumers.

## Coordinate frame

All adapters, the engine, and the floor plan share a single right-handed local frame:

- **Origin:** lower-left corner of the room.
- **x:** east (along `width_m`).
- **z:** north (along `depth_m`).
- **y:** vertical (height).

Adapters may report measurements in this local frame (the default) or in WGS84 latitude/longitude. WGS84-native sources (typically commercial RTLS platforms anchored on a real map) are projected into the local frame by the engine using the floor plan's `gps_origin` before fusion. The engine then converts the fused result back to WGS84 at the northbound boundary so the gateway stays geometry-agnostic. The demo recovers room-local coordinates by inverting this conversion against the same `gps_origin`. If `gps_origin` is absent (production deployments may legitimately omit it until a real lab GPS reference has been measured), the engine returns `latitude: 0, longitude: 0` and logs a warning.

```mermaid
flowchart LR
  subgraph in[Adapter replies]
    L["wifi-positioning<br/>frame=local<br/>(x, z)"]
    G["wittra-uwb<br/>frame=wgs84<br/>(lat, lon)"]
  end
  G -- "gps_to_local(lat,lon, gps_origin)" --> N(["local (x, z)"])
  L --> N
  N --> F["FUSION_STRATEGY.fuse(...)<br/>weighted_avg by default"]
  F --> P["local_to_gps(x, z, gps_origin)"]
  P --> OUT([EnginePosition · WGS84])
```

## Deployment model

This repository builds container images. A companion testbed repository (`kelt`) owns the Kubernetes manifests, ConfigMaps, and Secrets that compose them into a running cluster. See [`deployment.md`](deployment.md) for the image and configuration contract between the two.
