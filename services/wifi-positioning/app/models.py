from typing import Optional

from pydantic import BaseModel, ConfigDict


class GpsOrigin(BaseModel):
    model_config = ConfigDict(extra="ignore")
    latitude: float
    longitude: float


class Router(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    x: float
    y: float
    bssids: list[str] = []
    # Per-AP path-loss overrides. When set, compute_position uses these
    # instead of the global tx_power / path_loss_n. Populated by the
    # calibration tool. None means "fall back to the global tunables".
    tx_power: Optional[float] = None
    path_loss_n: Optional[float] = None


class WifiBinding(BaseModel):
    """One id → physical-BSSID mapping. Lives in the per-venue bindings
    file (see WifiBindings). Positions are NOT here - they come from the
    blueprint, joined by id."""

    model_config = ConfigDict(extra="ignore")
    id: str
    bssids: list[str] = []
    # Per-AP path-loss overrides. None means "use the file-level defaults".
    # The calibration tool writes these after a successful fit.
    tx_power: Optional[float] = None
    path_loss_n: Optional[float] = None


class CalibrationSample(BaseModel):
    """One survey point. The operator stands at (x_m, y_m) inside the
    room frame; the adapter averages the next N scans and records the
    mean RSSI per anchor id. Persisted in the bindings file under
    `calibration_samples` so a re-fit is possible after schema updates.
    """

    model_config = ConfigDict(extra="ignore")
    id: str
    x_m: float
    y_m: float
    # {anchor_id: mean_rssi_dbm}. Anchors not heard from at this point are
    # absent from the dict (they did not contribute to the fit).
    rssi_by_anchor: dict[str, float]
    # How many raw scans were averaged.
    n_scans: int
    ts: float


class WifiBindings(BaseModel):
    """Per-venue WiFi adapter config when positions come from the blueprint.

    Carries only:
      - propagation tunables (tx_power, path_loss_n, algorithm, etc.)
      - id → bssids mapping (physical hardware fingerprint per anchor)

    NOT in this file:
      - x / y positions  → come from the placement-editor blueprint
      - room_w / room_h  → come from the blueprint's first room
      - gps_origin       → derived from the blueprint's floor_plan georef

    Why the split: BSSIDs are venue-specific and sensitive (real network
    MACs); blueprint geometry is portable. Keeping them in separate files
    lets one blueprint travel between clusters without leaking BSSIDs,
    and lets BSSIDs be rotated without touching geometry.
    """

    model_config = ConfigDict(extra="ignore")
    tx_power: float = -42.0
    path_loss_n: float = 2.7
    algorithm: str = "trilateration"
    weight_power: float = 2.0
    smoothing: bool = True
    process_noise: float = 0.5
    bindings: list[WifiBinding] = []
    # Persisted calibration survey points. Empty until the operator runs
    # the guided calibration tool. The tool re-derives `tx_power` and
    # `path_loss_n` (per binding) from these samples on each "apply".
    calibration_samples: list[CalibrationSample] = []


class WifiConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    room_w: float
    room_h: float
    tx_power: float = -42.0
    path_loss_n: float = 2.7
    gps_origin: Optional[GpsOrigin] = None
    routers: list[Router]
    # "trilateration" (least-squares, uses all ranges) | "centroid" (weighted average)
    algorithm: str = "trilateration"
    weight_power: float = 2.0
    smoothing: bool = True
    process_noise: float = 0.5


class Measurement(BaseModel):
    """HTTP response of GET /measurement/{device_id}.

    Same shape consumed by positioning-engine's HttpAdapter. The engine maps
    `x`,`z` to its local room frame (room y maps to engine z = north).
    """

    source: str = "wifi"
    x: float
    y: float = 0.0  # height; not estimated by RSSI
    z: float
    accuracy_m: float
    confidence: float
    timestamp: Optional[float] = None
