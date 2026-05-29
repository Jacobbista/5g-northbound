"""
Edge WiFi scanner. Scans nearby access points with nmcli and posts the
per-BSSID RSSI to the wifi-positioning adapter over the 5G data network. The
adapter performs the multilateration; this client only scans and posts.

Env:
  ADAPTER_URL   wifi-positioning adapter base URL (default http://wifi-positioning:8080)
  DEVICE_ID     stable identifier of this asset   (default the hostname)
  INTERFACE     WiFi interface                    (default wlan0)
  SEND_INTERVAL seconds between scans             (default 1.0)
  BUFFER_MAX    scans buffered while offline      (default 120)
"""

import os
import socket
import re
import subprocess
import time
from collections import deque

import requests


def _normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    # tolerate the common single-slash typo: http:/host -> http://host
    return re.sub(r"^(https?):/(?!/)", r"\1://", url)


ADAPTER_URL = _normalize_url(
    os.environ.get("ADAPTER_URL", os.environ.get("ENGINE_URL", "http://wifi-positioning:8080"))
)
DEVICE_ID = os.environ.get("DEVICE_ID", socket.gethostname())
INTERFACE = os.environ.get("INTERFACE", "wlan0")
SEND_INTERVAL = float(os.environ.get("SEND_INTERVAL", "1.0"))
BUFFER_MAX = int(os.environ.get("BUFFER_MAX", "120"))  # scans kept during an outage

INGEST_PATH = "/ingest/wifi-scan"


def scan_wifi() -> dict[str, int]:
    """Fresh WiFi scan via NetworkManager. Returns {BSSID: rssi_dbm}."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "BSSID,SIGNAL", "dev", "wifi", "list", "--rescan", "yes"],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"  [!] scan error: {exc}")
        return {}

    aps: dict[str, int] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # nmcli -t escapes BSSID colons as '\:'; split on unescaped colons only
        parts = [p.replace("\x00", ":") for p in line.replace("\\:", "\x00").split(":")]
        if len(parts) < 2:
            continue
        bssid = parts[0].upper().strip()
        try:
            signal = int(parts[1].strip())
        except ValueError:
            continue
        # nmcli SIGNAL is 0-100 quality; approximate dBm = quality/2 - 100
        aps[bssid] = int(signal / 2) - 100
    return aps


# Bounded buffer of (timestamp, scan) kept while the engine is unreachable
# (e.g. 5G out of range); flushed oldest-first on reconnect.
_buffer: "deque[tuple[float, dict[str, int]]]" = deque(maxlen=BUFFER_MAX)


def _post(scan: dict[str, int], ts: float) -> bool:
    payload = {"device_id": DEVICE_ID, "scan": scan, "timestamp": ts}
    try:
        r = requests.post(f"{ADAPTER_URL}{INGEST_PATH}", json=payload, timeout=5)
        if r.status_code == 200:
            return True
        print(f"  [!] engine {r.status_code}: {r.text[:120]}")
    except requests.exceptions.RequestException as exc:
        print(f"  [!] cannot reach engine: {exc}")
    return False


def send_scan(scan: dict[str, int], ts: float) -> tuple[bool, int]:
    # drain the backlog first so the engine sees scans in time order
    while _buffer:
        b_ts, b_scan = _buffer[0]
        if not _post(b_scan, b_ts):
            break  # still down; keep the backlog
        _buffer.popleft()
    ok = _post(scan, ts)
    if not ok:
        _buffer.append((ts, scan))
    return ok, len(_buffer)


def main():
    print("\n  Raspberry Pi WiFi Scanner — mode B (engine ingestion)")
    print(f"  device={DEVICE_ID}  iface={INTERFACE}  engine={ADAPTER_URL}  buffer={BUFFER_MAX}\n")

    while True:
        t0 = time.time()
        aps = scan_wifi()
        if not aps:
            print(f"  [!] no APs ({time.time() - t0:.1f}s)")
            time.sleep(1)
            continue
        ok, buffered = send_scan(aps, t0)
        status = "sent" if ok else f"buffered ({buffered})"
        print(f"  {len(aps)} APs in {time.time() - t0:.1f}s → {status}")
        time.sleep(max(0.0, SEND_INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    main()
