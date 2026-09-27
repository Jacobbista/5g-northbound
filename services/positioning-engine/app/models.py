from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class GpsOrigin(BaseModel):
    """Georeference of the venue frame: the WGS84 position of the floor-plan
    origin (its lower-left corner).

    `azimuth_deg` is the bearing of the venue +y axis, clockwise from true
    north. 0 means the floor plan is north-aligned.

    `altitude_m` is the height of the origin above the WGS84 ellipsoid, the
    datum of latitude and longitude. None when it has not been surveyed.
    """

    model_config = ConfigDict(extra="ignore")
    latitude: float
    longitude: float
    azimuth_deg: float = 0.0
    altitude_m: Optional[float] = None


class RoomPlacement(BaseModel):
    """Where a room sits in its floor plan: lower-left corner, extents, and a
    rotation clockwise on the plan about the room centre."""

    model_config = ConfigDict(extra="ignore")
    x_m: float = 0.0
    y_m: float = 0.0
    width_m: float = 0.0
    depth_m: float = 0.0
    rotation_deg: float = 0.0


class FloorPlan(BaseModel):
    """What the engine needs from the blueprint: the georeference, the
    floor-plan extent, and the placement of each room."""

    model_config = ConfigDict(extra="ignore")
    gps_origin: Optional[GpsOrigin] = None
    width_m: float = 0.0
    depth_m: float = 0.0
    rooms: dict[str, RoomPlacement] = {}


class FusionOutput(BaseModel):
    """One strategy's output, in WGS84. Used inside EnginePosition.fusions for
    side-by-side comparison when FUSION_COMPARE is set."""

    latitude: float
    longitude: float
    accuracy: float
    sources: list[str]


class EnginePosition(BaseModel):
    """Northbound contract consumed by camara-gateway.

    The engine owns its native coordinate frame and normalises to WGS84
    lat/lon at this boundary, so the gateway stays geometry-agnostic.

    `fusions` is populated only when the engine is configured with
    FUSION_COMPARE (research/demo path). Production deployments should leave
    it absent and consume the top-level fields.
    """

    positioningId: str
    latitude: float
    longitude: float
    accuracy: float = Field(json_schema_extra={"x-unit": "m"})
    timestamp: str
    sources: list[str]
    strategy: str = "weighted_avg"
    fusions: Optional[dict[str, FusionOutput]] = None
    # Third dimension for the CAMARA private-asset profile (multi-floor /
    # stacked storage). `altitude` is the fused vertical position; absent
    # when the engine has no height estimate. The gateway exposes it as the
    # profile `altitude` extension. CAMARA's 2D Circle drops this.
    altitude: Optional[float] = Field(
        default=None, json_schema_extra={"x-unit": "m"}
    )
