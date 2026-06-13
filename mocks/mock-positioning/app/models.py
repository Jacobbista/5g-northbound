from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class Measurement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    source: str = "mock"
    frame: Literal["local"] = "local"
    x: float
    y: float
    z: float
    accuracy_m: float
    confidence: float
    timestamp: Optional[float] = None
