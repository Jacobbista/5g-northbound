from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Measurement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source: str = "synthetic"
    frame: Literal["local"] = "local"
    x: float
    y: float
    z: float
    accuracy: float = Field(json_schema_extra={"x-unit": "m"})
    confidence: float
    timestamp: Optional[float] = None
