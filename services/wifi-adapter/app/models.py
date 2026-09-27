from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .kalman import DEFAULT_MOTION_MODEL


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
    """One survey point. The operator stands at (x_m, y_m) in the room frame
    (lower-left origin, y along the depth); the adapter averages the next N
    scans and records the mean RSSI per anchor id. Persisted in the bindings file under
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
      - room extent      → comes from the blueprint's first room

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
    # "random-walk" (constant position; the estimate never extrapolates) |
    # "constant-velocity". The set the image implements is on GET /contract.
    motion_model: str = DEFAULT_MOTION_MODEL
    bindings: list[WifiBinding] = []
    # Persisted calibration survey points. Empty until the operator runs
    # the guided calibration tool. The tool re-derives `tx_power` and
    # `path_loss_n` (per binding) from these samples on each "apply".
    calibration_samples: list[CalibrationSample] = []
    # Frame of the stored samples. "room" is the room frame of blueprint
    # version 3. Absent on files written before it: those samples are in the
    # version 2 screen frame (y down) and are migrated once at config load.
    samples_frame: Optional[str] = None


class WifiConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    # The room the anchors belong to. Fixes are reported in its frame, and the
    # engine places the room in the venue.
    room_id: str
    room_w: float
    room_d: float
    tx_power: float = -42.0
    path_loss_n: float = 2.7
    routers: list[Router]
    # "trilateration" (least-squares, uses all ranges) | "centroid" (weighted average)
    algorithm: str = "trilateration"
    weight_power: float = 2.0
    smoothing: bool = True
    process_noise: float = 0.5
    motion_model: str = DEFAULT_MOTION_MODEL


class Measurement(BaseModel):
    """HTTP response of GET /measurement/{device_id}.

    Same shape consumed by positioning-engine's HttpAdapter. `x`, `y` are in
    the frame of the room named by `room`: lower-left origin, y along the
    depth. RSSI trilateration measures no height, so there is no `z`.
    """

    source: str = "wifi"
    frame: Literal["room"] = "room"
    room: str
    x: float
    y: float
    accuracy: float = Field(json_schema_extra={"x-unit": "m"})
    confidence: float
    timestamp: Optional[float] = None
