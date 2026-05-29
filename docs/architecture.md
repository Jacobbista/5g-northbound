# Architecture

The 5G Northbound stack exposes device location to third-party applications over the CAMARA Device Location API while abstracting the underlying positioning technology. It is the northbound capability-exposure layer of a 5G research testbed built on [Open5GS](https://open5gs.org/) and Kubernetes (k3s).

## System overview

```
Browser
  │  PKCE login              CAMARA REST (Bearer JWT)
  ▼                          ▼
[positioning-demo]──────►[camara-gateway]──────►[positioning-engine]──HTTP──►[wifi-positioning]──◄── edge devices
  React + Three.js           FastAPI                FastAPI                    FastAPI               (5G data network)
  Keycloak PKCE              JWT via JWKS           thin fusion +              RSSI trilateration    POST /ingest/wifi-scan
  2 s poll loop              device-id mapping      WGS84 conversion           Kalman smoothing
                             CAMARA envelopes       ADAPTER_URLS poll          GET /measurement/{id}
                                  │                       │
                              [Keycloak]                  └──HTTP──►[vendor-adapter (private image)]
                              [Open5GS SMF]
```

Devices are generic assets — UWB tags, WiFi clients, 5G UEs, anything with a stable identifier. Each positioning *technology* is its own pod that speaks a single HTTP contract; the engine fuses whichever adapter URLs are listed in its configuration. With no adapters configured, the engine falls back to in-process random-walk sources so the stack runs end-to-end without external dependencies (development only).

## Services

| Service              | Role                                                                  | Repository path                          |
|----------------------|-----------------------------------------------------------------------|------------------------------------------|
| `camara-gateway`     | CAMARA Location Retrieval v0.5 and Location Verification v3 endpoints; JWT validation against Keycloak; cross-technology device-identity mapping | [`camara-gateway/`](../camara-gateway/) |
| `positioning-engine` | Fuses measurements from configured adapters; converts local coordinates to WGS84; serves the northbound contract consumed by the gateway | [`positioning-engine/`](../positioning-engine/) |
| `wifi-positioning`   | Reference positioning adapter: WiFi RSSI multilateration over a fixed AP map; receives scans on the 5G data network                            | [`wifi-positioning/`](../wifi-positioning/) |
| `positioning-demo`   | Browser MEC application — Keycloak PKCE login, polls the CAMARA API, renders the device on a 3D floor plan                                     | [`positioning-demo/`](../positioning-demo/) |

Edge clients (e.g. the Raspberry Pi WiFi scanner under [`wifi-positioning/edge/scanner/`](../wifi-positioning/edge/scanner/)) are not deployed by Kubernetes; they run on the device and reach the cluster over the 5G data network.

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
| LMF                             | `positioning-engine`                                       | Thin fusion of 3GPP and non-3GPP sources via the HTTP adapter contract; weight = `confidence / accuracy_m`; normalises to WGS84 |
| RAN / UE measurements           | Adapter pods (`wifi-positioning` in repo; vendor adapters as private images) | Each adapter is its own pod implementing `GET /measurement/{id}` — see [`adapters.md`](adapters.md) |
| AMF / SMF session state         | Open5GS SMF (mocked locally by `dev/mock_smf.py`)          | Provides UE session info (IMSI, IPv4, `up_cnx_state`) for cross-tech identity resolution |

The external contracts (CAMARA REST) are standard; the internal decomposition is a deployment choice and can be re-split into separate NEF and LMF services later without breaking northbound consumers.

## Coordinate frame

All adapters, the engine, and the floor plan share a single right-handed local frame:

- **Origin:** lower-left corner of the room.
- **x:** east (along `width_m`).
- **z:** north (along `depth_m`).
- **y:** vertical (height).

The engine converts `(x, z)` to WGS84 latitude/longitude using the floor plan's `gps_origin` before publishing the position on the northbound contract. The demo recovers room-local coordinates by inverting this conversion against the same `gps_origin`. If `gps_origin` is absent — production deployments may legitimately omit it until a real lab GPS reference has been measured — the engine returns `latitude: 0, longitude: 0` and logs a warning.

## Deployment model

This repository builds container images. A companion testbed repository (`5g-k3s-kubedge-testbed`) owns the Kubernetes manifests, ConfigMaps, and Secrets that compose them into a running cluster. See [`deployment.md`](deployment.md) for the image and configuration contract between the two.
