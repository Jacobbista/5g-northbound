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
