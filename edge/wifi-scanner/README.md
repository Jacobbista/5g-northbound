# WiFi Scanner - edge client

Reference edge client for the [`wifi-adapter`](../../) adapter. Runs on a Raspberry Pi (or any Linux host with `nmcli`), scans nearby access points, and posts the per-BSSID RSSI readings to the adapter's `POST /ingest/wifi-scan` endpoint over the 5G data network. The adapter performs the multilateration; this client only scans and posts.

## Files

| File                | Purpose                                                                          |
|---------------------|----------------------------------------------------------------------------------|
| `scanner.py`        | The scanner. Configuration via environment variables.                            |
| `scanner.service`   | Systemd unit; reads `EnvironmentFile=/etc/positioning-scanner.env`.              |
| `deploy.sh`         | One-shot installer. Reads `./.env`, validates, copies files + service to the Pi. |
| `.env.example`      | Template for `./.env` (gitignored). Required by `deploy.sh`.                     |

## Runtime configuration (on the Pi)

| Variable        | Default                            | Notes                                                                 |
|-----------------|------------------------------------|-----------------------------------------------------------------------|
| `ADAPTER_URL`   | `http://wifi-adapter:8080`     | Base URL of the wifi-adapter adapter on the cluster data network. |
| `DEVICE_ID`     | hostname                           | Stable identifier for the asset. Must match the gateway's `DEVICE_REGISTRY` value for this device's CAMARA identifier. |
| `INTERFACE`     | `wlan0`                            | NetworkManager interface to scan.                                     |
| `SEND_INTERVAL` | `1.0`                              | Seconds between scans.                                                |
| `BUFFER_MAX`    | `120`                              | Bounded buffer used when the adapter is unreachable; flushed oldest-first on reconnect. |

These are written to `/etc/positioning-scanner.env` on the Pi by `deploy.sh config`.

## Deploying to a Pi

```bash
cp .env.example .env
$EDITOR .env                  # set PI_HOST, ADAPTER_URL, DEVICE_ID
./deploy.sh                   # full deploy: code + service + config
./deploy.sh config            # retarget only (no code change)
```

`deploy.sh` refuses to run if `.env` is missing or still contains `CHANGE-ME` placeholders. No production targets or asset identifiers ever enter the repository.

The deployment model is restart-on-change, not live reload: smaller attack surface, no runtime configuration endpoint on the device.

## Calibration

Room dimensions and the AP map (BSSID → router coordinates) live in the adapter's configuration, not on the device. The repository ships [`dev/wifi-config.json`](../../../dev/wifi-config.json) with placeholder BSSIDs; copy it to `dev/wifi-config.local.json` (gitignored) with your real values and mount that file into the adapter - see [`docs/deployment.md`](../../../docs/deployment.md) for the override pattern. The edge client is unaffected by either choice.
