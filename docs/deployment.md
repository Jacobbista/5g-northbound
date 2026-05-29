# Deployment

This repository produces container images and exposes a deployment contract (environment variables, ConfigMap shape, port numbers, health probes). The companion repository `5g-k3s-kubedge-testbed` consumes that contract through Ansible roles that render Kubernetes manifests. This document covers the producer side.

## Images

Four images are built and published by CI on every `v*` tag:

| Image                                                              | Source path                                    | Default port |
|--------------------------------------------------------------------|------------------------------------------------|--------------|
| `ghcr.io/jacobbista/5g-northbound/camara-gateway:<tag>`            | [`camara-gateway/`](../camara-gateway/)        | 8080         |
| `ghcr.io/jacobbista/5g-northbound/positioning-engine:<tag>`        | [`positioning-engine/`](../positioning-engine/)| 8080         |
| `ghcr.io/jacobbista/5g-northbound/wifi-positioning:<tag>`          | [`wifi-positioning/`](../wifi-positioning/)    | 8080         |
| `ghcr.io/jacobbista/5g-northbound/positioning-demo:<tag>`          | [`positioning-demo/`](../positioning-demo/)    | 80           |

Each tag publishes three references: the semver tag (`0.1.0`), `latest`, and a short-SHA tag (`sha-abcdef0`).

The Python services share a common Dockerfile pattern: multi-stage `python:3.11-slim`, non-root user, no shell entry point, `uvicorn` as PID 1. The demo image is `node:20-alpine` → `nginx:alpine` and serves a Vite-built bundle with a runtime configuration file (`env-config.js`) mounted from a ConfigMap and served `Cache-Control: no-cache`.

GitHub Packages defaults each new package to private. They must be flipped to **Public** once per package, via *Repo → Packages → \<pkg\> → Package settings → Change visibility*. `GITHUB_TOKEN` cannot change visibility; this is a one-time manual step.

## CI

[`.github/workflows/test.yml`](../.github/workflows/test.yml) runs the Python and JavaScript test suites on every push and pull request. [`.github/workflows/build.yml`](../.github/workflows/build.yml) builds and pushes all four images on `v*` tags. Both use a matrix over services; a failure in one service does not block the others.

To cut a release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

## Environment variables

### camara-gateway

| Variable                  | Default                                                | Notes |
|---------------------------|--------------------------------------------------------|-------|
| `KEYCLOAK_URL`            | `http://keycloak.iam.svc.cluster.local:8080`           | Full base URL including any path prefix |
| `KEYCLOAK_REALM`          | `5g-testbed`                                           | |
| `REQUIRED_ROLE`           | `camara-location-read`                                 | Realm role required to call CAMARA endpoints |
| `POSITIONING_ENGINE_URL`  | empty (mock fallback)                                  | Engine base URL; gateway calls `GET /position/{id}` |
| `SMF_URL`                 | `http://smf.5g.svc.cluster.local:9090`                 | Open5GS SMF management API for cross-tech identity |
| `DEVICE_REGISTRY`         | `{}`                                                   | JSON object mapping CAMARA identifiers to internal device ids |
| `SKIP_AUTH`               | `false`                                                | Development override only |

### positioning-engine

| Variable                | Default                              | Notes |
|-------------------------|--------------------------------------|-------|
| `ADAPTER_URLS`          | empty                                | Comma-separated adapter base URLs. Empty → in-process mock adapters (development only) |
| `FLOOR_PLAN_PATH`       | `/app/config/floor-plan.json`        | Mounted from `positioning-floor-plan` ConfigMap |
| `WEBSOCKET_INTERVAL_MS` | `500`                                | Cadence of the WebSocket position broadcast |
| `DEVICE_IDS`            | `uwb-tag-001`                        | Comma-separated devices broadcast on the WebSocket |

### wifi-positioning

| Variable           | Default                          | Notes |
|--------------------|----------------------------------|-------|
| `WIFI_CONFIG_PATH` | `/app/config/wifi-config.json`   | Path to the AP-map / RSSI calibration JSON. In docker compose, mounted from `dev/wifi-config.json`; in Kubernetes, from the `wifi-positioning-config` ConfigMap. Provisioning is documented in [`adapters.md`](adapters.md#configuration-provisioning). |

### positioning-demo

Runtime configuration is injected through `/usr/share/nginx/html/env-config.js`, mounted from a ConfigMap and served `Cache-Control: no-cache`:

```javascript
window.__ENV__ = {
  VITE_CAMARA_API_BASE:        "https://gateway.example.com",
  VITE_KEYCLOAK_URL:           "https://keycloak.example.com",
  VITE_KEYCLOAK_REALM:         "5g-testbed",
  VITE_KEYCLOAK_CLIENT_ID:     "positioning-demo",
  VITE_DEVICE_PHONE_NUMBER:    "+390111234567",
  VITE_DEVICE_LABEL:           "wifi-asset-01",
  VITE_GPS_ORIGIN_LAT:         45.064312,
  VITE_GPS_ORIGIN_LON:         7.659154,
  VITE_FLOOR_W:                13,
  VITE_FLOOR_D:                32
};
```

The image build does not bake any of these in; the same image runs in every environment.

## Health probes

Every service exposes `GET /health` returning `200 {"status": "ok"}` with no authentication. Use it for both `readinessProbe` and `livenessProbe`. Initial delays should account for the startup work: floor plan loading, JWKS fetch, AP map parsing.

## Adding a new adapter to a running cluster

1. Deploy the adapter (Deployment + ClusterIP Service) in the same namespace as the engine. Adapters that contain vendor code or NDA material ship as private images with an `imagePullSecret`.
2. Append the adapter's Service URL to the engine's `ADAPTER_URLS` (edit the engine ConfigMap or environment).
3. Restart the engine pod to pick up the new list. The engine reads `ADAPTER_URLS` at startup; a `checksum/config` annotation on the engine Deployment automates the rolling restart on ConfigMap change.

The adapter contract is documented in full in [`adapters.md`](adapters.md).

## Local development

```bash
docker compose up --build
```

Local ports: gateway `8088`, engine `8081`, wifi-positioning `8089`, demo `3001`, Keycloak `8180`, mock-smf `9090`. The gateway and demo are intentionally bound to non-default host ports to avoid clashes with common IDE-bound ports (8080, 3000).
