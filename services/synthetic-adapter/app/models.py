from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Measurement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source: str = "synthetic"
    # Room frame: x along the width, y along the depth, z the height above the
    # floor, metres from the room's lower-left corner.
    frame: Literal["room"] = "room"
    room: str
    x: float
    y: float
    z: float
    accuracy: float = Field(json_schema_extra={"x-unit": "m"})
    confidence: float
    timestamp: Optional[float] = None
