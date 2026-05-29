from typing import Optional

from pydantic import BaseModel, ConfigDict


class GpsOrigin(BaseModel):
    model_config = ConfigDict(extra="ignore")
    latitude: float
    longitude: float


class Wall(BaseModel):
    model_config = ConfigDict(extra="ignore")
    x: float
    z: float
    w: float
    d: float
    h: float


class UwbAnchor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    x: float
    y: float
    z: float


class Floor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    label: str
    width_m: float
    depth_m: float
    height_m: float
    walls: list[Wall] = []
    uwb_anchors: list[UwbAnchor] = []


class FloorPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: int = 1
    gps_origin: Optional[GpsOrigin] = None
    floors: list[Floor]


class InternalPosition(BaseModel):
    device_id: str
    x: float
    y: float
    z: float
    floor: int
    accuracy_m: float
    timestamp: str
    sources: list[str]


class EnginePosition(BaseModel):
    """Northbound contract consumed by camara-gateway.

    The engine owns its native coordinate frame and normalises to WGS84
    lat/lon at this boundary, so the gateway stays geometry-agnostic.
    """

    device_id: str
    latitude: float
    longitude: float
    accuracy_m: float
    timestamp: str
    sources: list[str]
