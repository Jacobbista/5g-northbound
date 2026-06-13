# 5G Northbound Capability Exposure Stack

Open positioning stack for a 5G research testbed. Exposes device location to applications over the [CAMARA Device Location API](https://camaraproject.org/), backed by a positioning engine that fuses one or more sources (WiFi RSSI, UWB, vendor RTLS, future 5G/GNSS).

The stack ships ten containers. Three are infrastructure: Keycloak (OIDC), a mocked Open5GS SMF, and a mocked Wittra cloud for local demos. Seven are the actual product: `camara-gateway`, `positioning-engine`, two reference adapters (`wifi-positioning`, `mock-positioning`), a schema-driven `rest-adapter` for vendor REST APIs, an operator-facing `placement-editor`, and a browser `positioning-demo`. It runs unchanged on Kubernetes; manifests live in the companion repository [`5g-k3s-kubedge-testbed`](https://github.com/jacobbista/5g-k3s-kubedge-testbed). New measurement sources arrive as new adapters; the engine and gateway never change.

## Quick start

```bash
make demo
```

This is `docker compose up --build` under the hood. Run `make` alone to see every target. The three you use day to day:

| Command       | What it does                                  |
|---------------|-----------------------------------------------|
| `make demo`   | Build + start everything                      |
| `make stop`   | Stop everything                               |
| `make test`   | Run every service's test suite locally        |

Once running:

| Service              | URL                          | Notes                                       |
|----------------------|------------------------------|---------------------------------------------|
| `camara-gateway`     | http://localhost:8087        | CAMARA Location API; host 8080 reserved     |
| `positioning-engine` | http://localhost:8081        | Engine REST + WebSocket on `:8082`          |
| `wifi-positioning`   | http://localhost:8089        | Reference adapter (RSSI multilateration)    |
| `mock-positioning`   | http://localhost:8090        | Reference adapter (waypoint walker)         |
| `rest-adapter`       | http://localhost:8092        | Schema-driven translator (Wittra cloud demo) |
| `mock-wittra`        | http://localhost:8091        | Demo only fake of the Wittra cloud REST API |
| `placement-editor`   | http://localhost:3003        | Operator UI + `/api/layout` BFF             |
| `positioning-demo`   | http://localhost:3002        | 3D browser application                      |
| Keycloak             | http://localhost:8180        | `admin` / `changeme`                        |
| `mock-smf`           | http://localhost:9090        | Open5GS SMF stub                            |

Keycloak imports the `5g-testbed` realm on first boot (~30 s). Host ports `8087` and `3002` are non-default to avoid clashes with common IDE-bound ports.

### Calling the CAMARA API

```bash
TOKEN=$(curl -s -X POST \
  http://localhost:8180/realms/5g-testbed/protocol/openid-connect/token \
  -d "grant_type=client_credentials&client_id=camara-gateway&client_secret=changeme" \
  | jq -r .access_token)

curl -s -X POST http://localhost:8087/location-retrieval/v0.5/retrieve \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device":{"phoneNumber":"+390117654321"}}' | jq
```

The stack registers three demo devices in [`dev/devices.json`](dev/devices.json):

- `+390117654321` resolves to `mock-demo-01`, pinned to `mock-positioning`. Walks around the room, no setup needed.
- `+390111234567` resolves to `wifi-asset-01`, pinned to `wifi-positioning`. Stays **offline** until a real WiFi scan is ingested. That is the expected end-to-end shape, not a bug.
- `+390119876543` resolves to `wittra-tag-01`, pinned to `rest-adapter`, which translates the local `mock-wittra` fake. Position moves immediately. The chain `gateway -> engine -> rest-adapter -> mock-wittra` is the worked example for vendor integration.

The demo discovers this list at runtime via `GET /devices` and renders a toggleable entry per device. To add or remove devices, edit the JSON file and restart the gateway. Registry schema and Kubernetes mount instructions: [`docs/deployment.md`](docs/deployment.md#registering-a-new-device).

### Running the tests

```bash
make test           # all suites
```

Or one suite at a time:

```bash
(cd services/camara-gateway     && pytest)
(cd services/positioning-engine && pytest)
(cd services/wifi-positioning   && pytest)
(cd services/placement-editor   && pytest)
(cd services/rest-adapter       && pytest)
(cd mocks/mock-positioning      && pytest)
(cd mocks/mock-wittra           && pytest)
(cd services/positioning-demo   && npm test)
(cd services/placement-editor/frontend && npm test)
```

No test requires `docker compose` to be running.

## Documentation

The full guided index is in [`docs/README.md`](docs/README.md). It groups the docs by reader intent ("I just cloned this", "I need to deploy", "I need to add a positioning source") and walks you through them in order.

Start there. Every other doc in `docs/` has exactly one job and is linked from the index.

## Configuration

Environment variables for the running stack live in **three** places, never anywhere else:

| Layer                       | File                                                       | What goes here                                                                 |
|-----------------------------|------------------------------------------------------------|--------------------------------------------------------------------------------|
| Backend services (Python)   | [`deploy/compose/docker-compose.yml`](deploy/compose/docker-compose.yml) `environment:` blocks | URLs, ports, flags. Use `${VAR:-default}` for things you want to override from the shell. |
| Frontend services (browser) | `services/positioning-demo/public/env-config.js` and `services/placement-editor/frontend/public/env-config.js` | Anything the browser reads (`VITE_*`). Both files are **gitignored**; copy from the `*.example.js` sibling on first run (`make demo` does this for you). |
| Vendor / edge credentials   | `services/rest-adapter/.env`, `edge/wifi-scanner/.env`     | Real third-party secrets. Both **gitignored**; templates committed as `.env.example` next to them. |

Every service ships a declarative `env.contract.yaml` next to its code listing every variable it expects, which are required, which are sensitive, and which carry safe defaults. Discover them:

```bash
make env-check                                    # what each service needs and where to set it
python3 deploy/tools/contracts.py validate -v     # full per-var breakdown
```

A walk-through of the deploy-portal pattern these contracts feed is in [`deploy/contracts/README.md`](deploy/contracts/README.md).

## Repository layout

```
5g-northbound/
├── services/                  # Production images shipped to the testbed
│   ├── camara-gateway/        #   CAMARA Location Retrieval v0.5 + Verification v3 + vendor extensions
│   ├── positioning-engine/    #   Fusion engine. Pulls Measurements from configured adapters
│   ├── wifi-positioning/      #   Reference adapter: WiFi RSSI multilateration
│   ├── rest-adapter/          #   Schema-driven adapter for vendor REST clouds
│   │   └── examples/          #     Sample schemas (Wittra) for docs and dashboard provisioning
│   ├── placement-editor/      #   Operator-facing service that owns the room layout JSON
│   └── positioning-demo/      #   Browser application (React + Three.js), read-only CAMARA consumer
├── mocks/                     # Compose-only fakes (never deployed to the testbed)
│   ├── mock-positioning/      #   Waypoint walker, wall and opening aware
│   └── mock-wittra/           #   Fake of the Wittra cloud REST API
├── edge/                      # Code that runs outside the cluster
│   └── wifi-scanner/          #   Raspberry Pi edge client (deploy.sh + .env.example)
├── deploy/                    # Deployment manifests + env contracts
│   ├── compose/               #   docker-compose.yml for local dev
│   ├── k8s/                   #   Kubernetes manifests (testbed)
│   └── contracts/             #   Per-service env.contract.yaml (consumed by the deploy portal)
├── dev/                       # Local fixtures (Keycloak realm, mock SMF, devices, floor plan)
├── docs/                      # Architecture and contract documentation (start at docs/README.md)
├── Makefile                   # `make demo`, `make stop`, `make test`
├── STRUCTURE.md               # Orientation guide for the folder tree
└── CLAUDE.md
```

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) (the CAMARA
OpenAPI documents vendored under `services/camara-gateway/spec/` are also
Apache 2.0, from the [CAMARA Project](https://camaraproject.org/)).
