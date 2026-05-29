from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --- Device identifiers (CAMARA Commonalities) ---


class DeviceIpv4Addr(BaseModel):
    model_config = ConfigDict(extra="ignore")
    publicAddress: Optional[str] = None
    privateAddress: Optional[str] = None
    publicPort: Optional[int] = Field(default=None, ge=0, le=65535)

    @model_validator(mode="after")
    def _require_pair(self) -> "DeviceIpv4Addr":
        if not self.publicAddress:
            raise ValueError("publicAddress is required")
        if not (self.privateAddress or self.publicPort is not None):
            raise ValueError("privateAddress or publicPort is required")
        return self


class Device(BaseModel):
    model_config = ConfigDict(extra="ignore")
    phoneNumber: Optional[str] = Field(default=None, pattern=r"^\+[1-9][0-9]{4,14}$")
    networkAccessIdentifier: Optional[str] = None
    ipv4Address: Optional[DeviceIpv4Addr] = None
    ipv6Address: Optional[str] = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "Device":
        if not any(
            (self.phoneNumber, self.networkAccessIdentifier, self.ipv4Address, self.ipv6Address)
        ):
            raise ValueError("at least one device identifier is required")
        return self


# --- Geometry ---


class Point(BaseModel):
    model_config = ConfigDict(extra="ignore")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class Circle(BaseModel):
    model_config = ConfigDict(extra="ignore")
    areaType: Literal["CIRCLE"] = "CIRCLE"
    center: Point
    radius: float = Field(ge=1)


# --- Location Retrieval (v0.5) ---


class RetrievalLocationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    device: Optional[Device] = None
    maxAge: Optional[int] = None
    maxSurface: Optional[int] = Field(default=None, ge=1)


class Location(BaseModel):
    lastLocationTime: str
    area: Circle
    device: Optional[Device] = None


# --- Location Verification (v3) ---


class VerifyLocationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    device: Optional[Device] = None
    area: Circle
    maxAge: Optional[int] = None


class VerifyLocationResponse(BaseModel):
    verificationResult: Literal["TRUE", "FALSE", "PARTIAL"]
    lastLocationTime: str
    matchRate: Optional[int] = Field(default=None, ge=1, le=99)
    device: Optional[Device] = None
