# 5G Northbound Capability Exposure Stack

Northbound capability-exposure layer for a 5G research testbed: exposes device location to third-party applications over the [CAMARA Device Location API](https://camaraproject.org/), backed by a pluggable positioning engine that fuses one or more measurement sources (5G, WiFi RSSI, UWB, vendor RTLS, …).

The stack runs as four containers — CAMARA gateway, positioning engine, a reference WiFi positioning adapter, and a browser demo — plus Keycloak for OIDC. It is designed to be deployed unchanged on Kubernetes (the companion [`5g-k3s-kubedge-testbed`](https://github.com/jacobbista/5g-k3s-kubedge-testbed) repository owns the manifests) and to evolve by adding adapters, never by modifying the engine or the gateway.

## Quick start

```bash
docker compose up --build
```

| Service              | URL                          | Notes                                       |
|----------------------|------------------------------|---------------------------------------------|
| `camara-gateway`     | http://localhost:8088        | CAMARA Location API; host 8080 reserved     |
| `positioning-engine` | http://localhost:8081        | Northbound REST + WebSocket on `:8082`      |
| `wifi-positioning`   | http://localhost:8089        | Reference adapter (RSSI multilateration)    |
| `positioning-demo`   | http://localhost:3001        | 3D MEC application                          |
| Keycloak             | http://localhost:8180        | `admin` / `changeme`                        |
| `mock-smf`           | http://localhost:9090        | Open5GS SMF stub                            |

Keycloak imports the `5g-testbed` realm on first boot (~30 s).

### Calling the CAMARA API

```bash
TOKEN=$(curl -s -X POST \
  http://localhost:8180/realms/5g-testbed/protocol/openid-connect/token \
  -d "grant_type=client_credentials&client_id=camara-gateway&client_secret=changeme" \
  | jq -r .access_token)

curl -s -X POST http://localhost:8088/location-retrieval/v0.5/retrieve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device":{"phoneNumber":"+390111234567"}}' | jq
```

With the local fixture the gateway resolves `+390111234567` → `wifi-asset-01`, fetches the fused position from the engine, and returns a CAMARA `Location` response. The `wifi-positioning` adapter starts with no measurements; populate it by sending a scan:

```bash
curl -s -X POST http://localhost:8089/ingest/wifi-scan \
  -H "Content-Type: application/json" \
  -d '{"device_id":"wifi-asset-01","scan":{"AA:BB:CC:00:01:01":-50,"AA:BB:CC:00:02:01":-55}}'
```

### Running the tests

```bash
(cd camara-gateway      && pytest)
(cd positioning-engine  && pytest)
(cd wifi-positioning    && pytest)
(cd positioning-demo    && npm test)
```

No test requires `docker compose` to be running.

## Documentation

| Document                                     | Audience                                                                 |
|----------------------------------------------|--------------------------------------------------------------------------|
| [`docs/architecture.md`](docs/architecture.md)       | System overview, 3GPP / CAMARA reference mapping, coordinate frame |
| [`docs/data-contracts.md`](docs/data-contracts.md)   | CAMARA API surface, engine REST, floor plan, adapter contract, SMF |
| [`docs/adapters.md`](docs/adapters.md)               | **Writing a custom positioning adapter** — contract, lifecycle, packaging, minimal skeleton |
| [`docs/deployment.md`](docs/deployment.md)           | Images, CI/CD, environment variables, ConfigMap shape, health probes |
| [`CLAUDE.md`](CLAUDE.md)                              | Repository conventions for contributors (and AI agents) |

## Repository layout

```
5g-northbound/
├── camara-gateway/       # CAMARA Location Retrieval v0.5 + Verification v3 (FastAPI)
├── positioning-engine/   # Thin fusion engine; pulls Measurements from configured adapters
├── wifi-positioning/     # Reference adapter: WiFi RSSI multilateration
│   └── edge/scanner/     # Raspberry Pi edge client (deploy.sh + .env.example)
├── positioning-demo/     # Browser MEC application (React + Three.js)
├── dev/                  # Local-only fixtures (Keycloak realm, mock SMF, floor plan, AP map placeholders)
├── docs/                 # Architecture and contract documentation
└── docker-compose.yml
```

## License

TBD.
