"""Calibration logic for the WiFi adapter.

Owns:
- the set of capture sessions opened by the operator while surveying;
- the persistent list of CalibrationSample records;
- the log-distance regression that turns samples into per-AP `tx_power`
  and `path_loss_n` values.

The HTTP surface (`app/routers/calibration.py`) is a thin layer over
this module. The ingest path (`WifiAdapter.on_ingest`) feeds raw scans
into any open session so the operator does not need to push a separate
"calibration scan" stream.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .models import CalibrationSample, WifiConfig

log = logging.getLogger(__name__)


@dataclass
class CaptureSession:
    """One short-lived survey point. Raw scans flow in while the session
    is open; when `target_scans` is reached the session closes and the
    aggregated sample is appended to the store."""

    id: str
    x_m: float
    y_m: float
    target_scans: int
    # Raw scans collected so far. Each entry is the full `{bssid: rssi}`
    # received over `/ingest/wifi-scan`. We aggregate per anchor only at
    # the end so an operator can see the raw spread if they ask.
    scans: list[dict[str, int]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    done: bool = False


class CalibrationStore:
    """In-process state plus a hook into the wifi adapter's ingest path.

    Thread-safety: capture sessions are mutated from the FastAPI request
    loop AND from the ingest router. A re-entrant lock around the
    collection methods keeps them honest under uvicorn's default worker
    settings (single process, async I/O).
    """

    def __init__(self, samples: Optional[list[CalibrationSample]] = None):
        self._lock = threading.RLock()
        self._sessions: dict[str, CaptureSession] = {}
        self._samples: list[CalibrationSample] = list(samples or [])
        # Optional callback fired after every store mutation that adds or
        # removes a sample. Wired from main.py to persist the current
        # sample list back to the bindings file. Idempotent and
        # exception-safe: a persist failure logs a warning and the store
        # keeps the sample in memory.
        self.on_samples_changed: Optional[callable] = None

    # ----- session lifecycle ---------------------------------------------------

    def start_capture(self, x_m: float, y_m: float, target_scans: int) -> CaptureSession:
        target_scans = max(1, min(200, int(target_scans)))
        session = CaptureSession(
            id=uuid.uuid4().hex[:12],
            x_m=float(x_m),
            y_m=float(y_m),
            target_scans=target_scans,
        )
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> Optional[CaptureSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def cancel_session(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    # ----- raw-scan ingest -----------------------------------------------------

    def on_ingest(self, device_id: str, scan: dict[str, int], ts: float) -> None:
        # Calibration is venue-wide; we don't filter by device. Any
        # scan that arrives while a capture is open is recorded. If you
        # want to lock calibration to one device, do it at the HTTP
        # boundary in the router.
        del device_id, ts
        finalized = False
        with self._lock:
            for session in self._sessions.values():
                if session.done:
                    continue
                session.scans.append(dict(scan))
                if len(session.scans) >= session.target_scans:
                    sample = self._finalize_locked(session)
                    self._samples.append(sample)
                    session.done = True
                    finalized = True
        if finalized:
            self._notify_changed()

    def _notify_changed(self) -> None:
        cb = self.on_samples_changed
        if cb is None:
            return
        try:
            cb(list(self._samples))
        except Exception as exc:
            log.warning("calibration persistence callback raised: %s", exc)

    def _finalize_locked(self, session: CaptureSession) -> CalibrationSample:
        """Average RSSI per anchor across the session's raw scans. We
        average in dBm (linear-power averaging would be more correct but
        also more sensitive to outliers; dBm avg is the convention used
        in published fingerprinting work). Anchors not heard from in any
        scan are simply absent from the resulting dict."""
        # rssi_by_bssid_accum: bssid -> list of RSSI samples (one per scan)
        accum: dict[str, list[int]] = {}
        for s in session.scans:
            for bssid, rssi in s.items():
                accum.setdefault(bssid.upper(), []).append(int(rssi))
        # bssid -> mean RSSI. The router/anchor mapping is applied by
        # the HTTP layer (it knows the live WifiConfig); here we keep
        # everything keyed by BSSID so a re-fit after BSSID rotation
        # still works.
        rssi_means = {b: sum(v) / len(v) for b, v in accum.items() if v}
        sample = CalibrationSample(
            id=session.id,
            x_m=session.x_m,
            y_m=session.y_m,
            rssi_by_anchor=rssi_means,  # caller maps BSSID -> anchor
            n_scans=len(session.scans),
            ts=time.time(),
        )
        return sample

    # ----- sample management ---------------------------------------------------

    def all_samples(self) -> list[CalibrationSample]:
        with self._lock:
            return list(self._samples)

    def add_sample(self, sample: CalibrationSample) -> None:
        with self._lock:
            self._samples.append(sample)
        self._notify_changed()

    def remove_sample(self, sample_id: str) -> bool:
        with self._lock:
            before = len(self._samples)
            self._samples = [s for s in self._samples if s.id != sample_id]
            removed = len(self._samples) < before
        if removed:
            self._notify_changed()
        return removed

    def clear_samples(self) -> None:
        with self._lock:
            self._samples = []
        self._notify_changed()

    def replace_samples(self, samples: Optional[list[CalibrationSample]]) -> None:
        """Swap the in-memory sample set wholesale. Used after a bindings
        import: the file we just wrote already carries these samples, so we do
        NOT fire on_samples_changed (that would re-persist redundantly)."""
        with self._lock:
            self._samples = list(samples or [])

    # ----- derive --------------------------------------------------------------

    def derive_params(self, cfg: WifiConfig) -> dict[str, dict]:
        """Fit per-AP `tx_power` and `path_loss_n` from the stored samples.

        Model: `RSSI(d) = tx_power - 10 * n * log10(d)`.
        For each anchor, collect `(log10(d), RSSI_mean)` pairs from every
        sample that included that anchor's BSSIDs. Solve the 1D linear
        regression `y = a + b * x` with `y = RSSI`, `x = log10(d)`:
            n        = -b / 10
            tx_power =  a
        Returns: { anchor_id: {tx_power, path_loss_n, n_points, r2,
                               residual_rms_db} }.
        Anchors with fewer than 3 sample points are returned with `None`
        params so the caller can show "not enough samples" instead of
        applying a garbage fit.
        """
        # Build BSSID -> anchor id lookup once.
        bssid_to_anchor: dict[str, str] = {}
        anchor_pos: dict[str, tuple[float, float]] = {}
        for r in cfg.routers:
            anchor_pos[r.id] = (r.x, r.y)
            for b in r.bssids:
                bssid_to_anchor[b.upper()] = r.id

        # anchor_id -> list of (log10_d, rssi)
        pairs: dict[str, list[tuple[float, float]]] = {}
        for sample in self.all_samples():
            for bssid, rssi in sample.rssi_by_anchor.items():
                anchor = bssid_to_anchor.get(bssid.upper())
                if anchor is None or anchor not in anchor_pos:
                    continue
                ax, ay = anchor_pos[anchor]
                d = math.hypot(sample.x_m - ax, sample.y_m - ay)
                if d < 0.5:
                    # Closer than half a metre is dominated by antenna
                    # near-field effects; skip to keep the fit clean.
                    continue
                pairs.setdefault(anchor, []).append((math.log10(d), float(rssi)))

        out: dict[str, dict] = {}
        for anchor_id in anchor_pos:
            data = pairs.get(anchor_id, [])
            if len(data) < 3:
                out[anchor_id] = {
                    "tx_power": None,
                    "path_loss_n": None,
                    "n_points": len(data),
                    "r2": None,
                    "residual_rms_db": None,
                }
                continue
            tx, n, r2, rms = _fit_log_distance(data)
            out[anchor_id] = {
                "tx_power": round(tx, 2),
                "path_loss_n": round(n, 3),
                "n_points": len(data),
                "r2": round(r2, 3),
                "residual_rms_db": round(rms, 2),
            }
        return out


def _fit_log_distance(pairs: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Closed-form OLS on y = a + b*x. Returns (tx_power, n, R2, rms).

    pairs: (log10_distance, rssi_dbm). `tx_power = a`, `n = -b / 10`.
    """
    n = len(pairs)
    sx = sum(p[0] for p in pairs)
    sy = sum(p[1] for p in pairs)
    sxx = sum(p[0] * p[0] for p in pairs)
    sxy = sum(p[0] * p[1] for p in pairs)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return float(sy / n), 2.7, 0.0, 0.0
    b = (n * sxy - sx * sy) / denom
    a = (sy - b * sx) / n
    # R²
    mean_y = sy / n
    ss_tot = sum((y - mean_y) ** 2 for _, y in pairs)
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in pairs)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 1.0
    rms = math.sqrt(ss_res / n)
    n_model = -b / 10.0
    # Clamp `n` to a sane indoor range so a degenerate sample set cannot
    # produce a negative decay (signal getting stronger with distance) or
    # a vacuum-like decay (n < 1).
    n_model = max(1.5, min(6.0, n_model))
    return a, n_model, r2, rms
