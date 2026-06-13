from typing import Optional

from pydantic import BaseModel, ConfigDict


class GpsOrigin(BaseModel):
    """Single georeference linking the floor-plan local frame to WGS84.

    `azimuth_deg` is the bearing of the floor-plan +z axis (the "north" of
    the SVG / top-down view) measured clockwise from true north. Default 0
    means the floor plan is already north-aligned. A real building rotated
    30° east of north would have azimuth_deg=30.

    `altitude_m` is the altitude of the local origin above sea level; carried
    for completeness, not used in the 2D projection.
    """

    model_config = ConfigDict(extra="ignore")
    latitude: float
    longitude: float
    azimuth_deg: float = 0.0
    altitude_m: Optional[float] = None


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


class FusionOutput(BaseModel):
    """One strategy's output, in WGS84. Used inside EnginePosition.fusions for
    side-by-side comparison when FUSION_COMPARE is set."""

    latitude: float
    longitude: float
    accuracy_m: float
    sources: list[str]


class EnginePosition(BaseModel):
    """Northbound contract consumed by camara-gateway.

    The engine owns its native coordinate frame and normalises to WGS84
    lat/lon at this boundary, so the gateway stays geometry-agnostic.

    `fusions` is populated only when the engine is configured with
    FUSION_COMPARE (research/demo path). Production deployments should leave
    it absent and consume the top-level fields.
    """

    device_id: str
    latitude: float
    longitude: float
    accuracy_m: float
    timestamp: str
    sources: list[str]
    strategy: str = "weighted_avg"
    fusions: Optional[dict[str, FusionOutput]] = None
