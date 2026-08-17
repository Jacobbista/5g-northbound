import logging
import math
import os
import time
from typing import Optional

from .kalman import Tracker2D
from .models import Measurement, WifiConfig

log = logging.getLogger(__name__)
# Set WIFI_DEBUG=1 to log per-scan diagnostics: which routers matched,
# strongest RSSI per router, computed distances, fused position. Verbose;
# meant for tuning tx_power / path_loss_n against a real venue, off by
# default to keep the adapter quiet in production.
_DEBUG = os.environ.get("WIFI_DEBUG", "0") not in ("", "0", "false", "False")

# --- Positioning: RSSI multilateration with weighted-centroid fallback ---

Scan = dict[str, int]  # BSSID -> RSSI (dBm)


def _rssi_to_distance(rssi: int, tx_power: float, n: float) -> float:
    return 10 ** ((tx_power - rssi) / (10.0 * n))


def _centroid(points: list[tuple[float, float]], dists: list[float], power: float):
    """Weighted centroid; weight = 1 / d^power. Stays inside the AP hull."""
    wx = wy = wsum = 0.0
    for (px, py), d in zip(points, dists):
        w = 1.0 / (d ** power)
        wx += w * px
        wy += w * py
        wsum += w
    if wsum == 0:
        return None
    return wx / wsum, wy / wsum


def _multilaterate(points: list[tuple[float, float]], dists: list[float]):
    """Linear least-squares multilateration from ranges. Needs >= 3 APs.

    Subtract a reference circle equation to linearise, solve the 2x2 normal
    equations. Returns (x, y, rms_residual) or None if degenerate.
    """
    # reference = nearest AP (strongest signal) for numerical stability
    ref = min(range(len(dists)), key=lambda i: dists[i])
    x0, y0 = points[ref]
    d0 = dists[ref]

    a11 = a12 = a22 = b1 = b2 = 0.0
    for i, ((xi, yi), di) in enumerate(zip(points, dists)):
        if i == ref:
            continue
        ax = 2 * (xi - x0)
        ay = 2 * (yi - y0)
        bb = (xi * xi - x0 * x0) + (yi * yi - y0 * y0) - (di * di - d0 * d0)
        a11 += ax * ax
        a12 += ax * ay
        a22 += ay * ay
        b1 += ax * bb
        b2 += ay * bb

    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-9:
        return None
    x = (b1 * a22 - b2 * a12) / det
    y = (a11 * b2 - a12 * b1) / det

    sq = sum((((x - xi) ** 2 + (y - yi) ** 2) ** 0.5 - di) ** 2 for (xi, yi), di in zip(points, dists))
    rms = (sq / len(points)) ** 0.5
    return x, y, rms


def compute_position(scan: Scan, cfg: WifiConfig) -> Optional[tuple[float, float, float, float]]:
    """Return (x, y, confidence_pct, accuracy_m) in room-local metres, or None.

    Algorithm = "trilateration" (least-squares multilateration, uses all ranges)
    or "centroid" (weighted average, stays inside the AP hull).
    """
    bssid_to_router = {b.upper(): r.id for r in cfg.routers for b in r.bssids}
    router_pos = {r.id: (r.x, r.y) for r in cfg.routers}

    router_rssi: dict[str, int] = {}
    for bssid, rssi in scan.items():
        rid = bssid_to_router.get(bssid.upper())
        if rid is None:
            continue
        if rid not in router_rssi or rssi > router_rssi[rid]:
            router_rssi[rid] = rssi

    if not router_rssi:
        return None

    # Per-router path-loss overrides (populated by the calibration tool)
    # win over the global defaults. Falls back to the file-level values
    # whenever an override is unset, so an uncalibrated venue still works.
    router_by_id = {r.id: r for r in cfg.routers}
    def _params_for(rid: str) -> tuple[float, float]:
        r = router_by_id.get(rid)
        tx = r.tx_power if r and r.tx_power is not None else cfg.tx_power
        n = r.path_loss_n if r and r.path_loss_n is not None else cfg.path_loss_n
        return tx, n

    points = [router_pos[rid] for rid in router_rssi]
    dists = []
    for rid, rssi in router_rssi.items():
        tx, n = _params_for(rid)
        dists.append(max(0.1, _rssi_to_distance(rssi, tx, n)))
    confidence = (len(router_rssi) / len(router_pos)) * 100 if router_pos else 0.0
    room_diag = math.hypot(cfg.room_w, cfg.room_h)

    sol = None
    if cfg.algorithm == "trilateration" and len(points) >= 3:
        ml = _multilaterate(points, dists)
        if ml is not None:
            x, y, rms = ml
            sol = (x, y, max(1.0, rms))

    if sol is None:
        c = _centroid(points, dists, cfg.weight_power)
        if c is None:
            return None
        x, y = c
        sol = (x, y, max(1.0, room_diag * (1.0 - confidence / 100.0)))

    x, y, accuracy_m = sol
    clamped_x = max(0.0, min(cfg.room_w, x))
    clamped_y = max(0.0, min(cfg.room_h, y))
    if _DEBUG:
        log.info(
            "wifi-debug: matched=%d/%d, scan_size=%d, "
            "rssi=%s, dists_m=%s, raw_xy=(%.2f, %.2f), clamped=(%.2f, %.2f), "
            "acc_m=%.2f, conf=%.1f%%",
            len(router_rssi), len(router_pos), len(scan),
            {rid: router_rssi[rid] for rid in router_rssi},
            {rid: round(d, 2) for rid, d in zip(router_rssi.keys(), dists)},
            x, y, clamped_x, clamped_y, accuracy_m, confidence,
        )
    return round(clamped_x, 2), round(clamped_y, 2), round(confidence, 1), round(accuracy_m, 2)


class WifiAdapter:
    """Holds the latest trilaterated position per device.

    Fed by `POST /ingest/wifi-scan`; `get_measurement` reads the cache and is
    consumed over HTTP by positioning-engine through the generic Adapter
    contract. The wifi-adapter service therefore owns: BSSID map, RSSI
    math, Kalman smoothing, ingest endpoint. The engine sees only Measurements.
    """

    source = "wifi"

    def __init__(self, config: WifiConfig):
        self.cfg = config
        self._cache: dict[str, Measurement] = {}
        self._trackers: dict[str, Tracker2D] = {}
        self._last_ts: dict[str, float] = {}
        # Optional ingest hook. The calibration router installs one here
        # so an active capture session can pull raw scans in real time.
        # `(device_id, scan, ts)`; should not raise.
        self.on_ingest: Optional[callable] = None

    def reload(self, config: WifiConfig) -> None:
        """Swap the active config in place. Keeps the in-flight cache /
        smoothing trackers; only the propagation model + AP map change.
        Used by the calibration apply path to install per-router params
        without restarting the container."""
        self.cfg = config

    def ingest(self, device_id: str, scan: Scan, ts: Optional[float] = None) -> bool:
        if self.on_ingest is not None:
            try:
                self.on_ingest(device_id, scan, ts if ts is not None else time.time())
            except Exception as exc:
                log.warning("calibration hook raised: %s", exc)
        result = compute_position(scan, self.cfg)
        if result is None:
            return False
        x, y, confidence, accuracy_m = result

        ts = ts if ts is not None else time.time()
        if self.cfg.smoothing:
            tracker = self._trackers.get(device_id)
            if tracker is None:
                tracker = self._trackers[device_id] = Tracker2D(self.cfg.process_noise)
            dt = ts - self._last_ts.get(device_id, ts)
            if dt >= 0:
                x, y = tracker.update(x, y, dt, accuracy_m**2)
        self._last_ts[device_id] = ts

        # Trilateration runs in room-local (canvas-y); lift to the engine's
        # documented `local` frame (floor-plan-local, north-up) before caching.
        fx, fz = self._to_floor_plan(x, y)
        self._cache[device_id] = Measurement(
            source=self.source,
            x=fx,
            y=0.0,
            z=fz,
            accuracy_m=accuracy_m,
            confidence=max(0.01, confidence / 100.0),
            timestamp=ts,
        )
        return True

    def _to_floor_plan(self, x: float, y: float) -> tuple[float, float]:
        """Room-local (canvas-y) -> floor-plan-local (north-up). Falls back to
        room-local + base when no floor-plan height is known (no georef); the
        engine degrades to (0, 0) WGS84 in that case anyway."""
        fx = self.cfg.base_x + x
        if self.cfg.fp_height_m > 0:
            return fx, self.cfg.fp_height_m - (self.cfg.base_y + y)
        return fx, self.cfg.base_y + y

    def get_measurement(self, device_id: str) -> Optional[Measurement]:
        # Always return the last fix with its real timestamp; the consumer decides
        # staleness from the age, so a transport gap greys out instead of resetting.
        return self._cache.get(device_id)

    def observed_devices(self) -> list[dict]:
        """Device ids this adapter has produced a fix for, newest activity
        first. Powers GET /devices for onboarding discovery. This is an
        `observed` list, not a registry: an id appears once a scan tagged with
        it is ingested, so the operator claims + names it (unlike a vendor's
        pre-named inventory). `last_seen` is epoch seconds (as Measurement.timestamp)."""
        out = [
            {
                "id": device_id,
                # A device seen on the air is a tracked asset (paper vocab), not
                # infrastructure; the wifi anchors (APs) live in the bindings.
                "role": "asset",
                "source_class": "wifi",
                "last_seen": m.timestamp,
                "position": {"x": m.x, "y": m.y, "z": m.z},
            }
            for device_id, m in self._cache.items()
        ]
        out.sort(key=lambda d: d["last_seen"] or 0, reverse=True)
        return out
