"""The southbound contract: what an adapter sends to the engine.

These models parse the bodies the engine receives, and their JSON Schema is
the published contract (`make contract-schemas` writes it under `schema/`).
One definition serves both, so the parser and the document cannot drift.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Frame = Literal["venue", "room", "wgs84"]
Reporting = Literal["on_request", "periodic", "on_motion"]

# Coordinates each frame requires.
FRAME_COORDINATES: dict[str, tuple[str, str]] = {
    "venue": ("x", "y"),
    "room": ("x", "y"),
    "wgs84": ("latitude", "longitude"),
}


class MeasurementBody(BaseModel):
    """`GET /measurement/{positioningId}`: one fix from one source.

    The frame names the reference of the horizontal position and decides which
    coordinates are required. A value the source does not measure is omitted,
    never sent as a default."""

    model_config = ConfigDict(
        extra="ignore",
        title="Adapter measurement",
        # The frame rule of the validator below, for readers of the schema.
        json_schema_extra={"allOf": [
            {"if": {"properties": {"frame": {"const": "wgs84"}}, "required": ["frame"]},
             "then": {"required": ["latitude", "longitude"]},
             "else": {"required": ["x", "y"]}},
            {"if": {"properties": {"frame": {"const": "room"}}, "required": ["frame"]},
             "then": {"required": ["room"]}},
        ]},
    )

    source: Optional[str] = Field(
        default=None,
        description="Short tag of the positioning technology. Defaults to the adapter's registered name.",
    )
    frame: Frame = Field(
        default="venue",
        description=(
            "Reference of the horizontal position. `room`: x, y from the lower-left corner of the "
            "room named by `room`. `venue`: x, y from the lower-left corner of the floor plan. "
            "`wgs84`: latitude, longitude."
        ),
    )
    room: Optional[str] = Field(default=None, description="Blueprint room id. Required with frame `room`.")
    x: Optional[float] = Field(
        default=None, json_schema_extra={"x-unit": "m"},
        description="Along the width. Required with frame `room` or `venue`.",
    )
    y: Optional[float] = Field(
        default=None, json_schema_extra={"x-unit": "m"},
        description="Along the depth. Required with frame `room` or `venue`.",
    )
    latitude: Optional[float] = Field(
        default=None, json_schema_extra={"x-unit": "deg"}, description="Required with frame `wgs84`.",
    )
    longitude: Optional[float] = Field(
        default=None, json_schema_extra={"x-unit": "deg"}, description="Required with frame `wgs84`.",
    )
    z: Optional[float] = Field(
        default=None, json_schema_extra={"x-unit": "m"},
        description=(
            "Height above the venue floor, in every frame. Sent only by a source that declares "
            "`z: true`, and only when measured for this fix."
        ),
    )
    accuracy: Optional[float] = Field(
        default=None, json_schema_extra={"x-unit": "m"},
        description=(
            "One-sigma horizontal error radius. When absent, the engine uses the nominal accuracy "
            "of the adapter's declared accuracy class."
        ),
    )
    confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="The source's own reliability score, a multiplier on the fusion weight.",
    )
    timestamp: float = Field(
        json_schema_extra={"x-unit": "s"},
        description="When the fix was taken, Unix epoch seconds.",
    )
    lastSeen: Optional[float] = Field(
        default=None, json_schema_extra={"x-unit": "s"},
        description=(
            "When the device last communicated with its source, Unix epoch seconds. For a source "
            "that declares `reporting: on_motion`, it confirms that the last fix still holds."
        ),
    )
    diagnostics: dict = Field(
        default_factory=dict, description="Stream-tier diagnostics, carried to the position stream.",
    )

    @model_validator(mode="after")
    def _frame_coordinates(self) -> "MeasurementBody":
        missing = [c for c in FRAME_COORDINATES[self.frame] if getattr(self, c) is None]
        if missing:
            raise ValueError(f"frame {self.frame!r} requires {', '.join(missing)}")
        if self.frame == "room" and not self.room:
            raise ValueError("frame 'room' requires room")
        return self


class AdapterCapabilities(BaseModel):
    """What an adapter declares about itself. Unknown keys are carried as
    declared."""

    model_config = ConfigDict(extra="allow", title="Adapter capabilities")

    source: Optional[str] = Field(default=None, description="Technology tag the adapter reports under.")
    kinds: list[str] = Field(default_factory=list, description="Asset kinds this source can position.")
    frame: Optional[Frame] = Field(default=None, description="Frame of the measurements it sends.")
    streaming: bool = Field(default=False, description="The adapter pushes its fixes instead of being polled.")
    z: bool = Field(default=False, description="The source measures height.")
    accuracy_class: Optional[str] = Field(
        default=None, description="Band from spec/private-profile/accuracy-class-vocabulary.json.",
    )
    nominalAccuracy: Optional[float] = Field(
        default=None, json_schema_extra={"x-unit": "m"},
        description="Nominal accuracy for an open-ended accuracy class.",
    )
    calibration: bool = Field(default=False, description="Serves the calibration tool.")
    devices: bool = Field(default=False, description="Serves GET /devices for onboarding.")
    discover: bool = Field(default=False, description="Serves GET /discover, the vendor device list.")
    diagnostics: bool = Field(default=False, description="Serves GET /diagnostics/{positioningId}.")
    placement: bool = Field(default=False, description="Accepts a placement, for a synthetic source.")
    reporting: Optional[Reporting] = Field(
        default=None,
        description=(
            "How the source produces fixes. `on_request`: a fix at each poll. `periodic`: a fix at "
            "least every `reportingInterval`. `on_motion`: a fix whenever the device moves, and a "
            "communication at least every `reportingInterval` while it is still. Undeclared, the "
            "source counts as `periodic` without an interval, and its fixes are never current."
        ),
    )
    reportingInterval: Optional[float] = Field(
        default=None, gt=0, json_schema_extra={"x-unit": "s"},
        description=(
            "Longest time between two reports the source guarantees, transport included. "
            "Required with `periodic` and `on_motion`."
        ),
    )

    @model_validator(mode="after")
    def _interval_for_reporting(self) -> "AdapterCapabilities":
        if self.reporting in ("periodic", "on_motion") and self.reportingInterval is None:
            raise ValueError(f"reporting {self.reporting!r} requires reportingInterval")
        return self


class Announcement(BaseModel):
    """`POST /adapters`: an adapter registers itself and keeps announcing."""

    model_config = ConfigDict(extra="ignore", title="Adapter announcement")

    name: str
    baseUrl: str = Field(description="Where the engine reaches the adapter.")
    kind: str = "adapter"
    capabilities: AdapterCapabilities = Field(default_factory=AdapterCapabilities)


class DeviceEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="The source's device id. Becomes a capability's positioningId on onboarding.")
    role: Optional[Literal["asset", "infrastructure"]] = None
    sourceClass: Optional[str] = Field(default=None, description="uwb, ble, wifi, gnss, cellular or other.")
    deviceType: Optional[str] = Field(default=None, description="The vendor's own device type.")
    label: Optional[str] = None
    lastSeen: Optional[float] = Field(
        default=None, json_schema_extra={"x-unit": "s"},
        description="When the device last communicated with its source, Unix epoch seconds.",
    )
    position: Optional[dict] = Field(
        default=None,
        description="Last known position, with the coordinate fields of a measurement.",
    )


class DevicesBody(BaseModel):
    """`GET /devices`: the devices a source knows, for onboarding."""

    model_config = ConfigDict(extra="ignore", title="Adapter devices")

    origin: Literal["inventory", "observed"] = Field(
        description="`inventory`: the vendor's registry. `observed`: seen by activity.",
    )
    devices: list[DeviceEntry]
