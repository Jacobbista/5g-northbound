# wifi-scanner

Reference edge client for the
[wifi-adapter](../../services/wifi-adapter). It runs on a Raspberry Pi or any
Linux host with NetworkManager, scans the access points in range with `nmcli`,
and posts the RSSI per BSSID to the adapter's `POST /ingest/wifi-scan`. The
adapter computes the position.

## Files

| File | Content |
|------|---------|
| `scanner.py` | the scanner, configured by environment variables |
| `scanner.service` | systemd unit, reads `/etc/positioning-scanner.env` |
| `deploy.sh` | copies the scanner and the unit to the Pi and writes the configuration |
| `.env.example` | template for `.env`, which `deploy.sh` reads and git ignores |

## Configuration

| Variable | Default | Meaning |
|----------|---------|---------|
| `ADAPTER_URL` | none, required by `deploy.sh` | base URL of the wifi-adapter |
| `DEVICE_ID` | the hostname | the device's `positioningId`: the asset map holds it in a capability with `source: wifi` |
| `INTERFACE` | `wlan0` | the interface to scan |
| `SEND_INTERVAL` | `1.0` | seconds between scans |
| `BUFFER_MAX` | `120` | scans kept while the adapter is unreachable, sent oldest first on reconnection |

## Deploying to a Pi

```bash
cp .env.example .env
$EDITOR .env           # PI_HOST, ADAPTER_URL, DEVICE_ID
./deploy.sh            # code, unit and configuration
./deploy.sh config     # configuration only
```

`deploy.sh` stops when `.env` is missing or still contains `CHANGE-ME`. A
configuration change takes effect when the service restarts. The device
exposes no configuration endpoint.

Anchor positions and BSSIDs live in the adapter's blueprint and bindings, not
on the device ([blueprint and bindings](../../docs/blueprint-vs-bindings.md)).
