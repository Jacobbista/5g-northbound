from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --- Device identifier (CAMARA private-asset profile) ---


class Device(BaseModel):
    """The tracked entity is an ASSET, not a cellular subscriber.

    Private-asset profile (see spec/private-profile/): `assetId` is the
    first-class identifier. `networkAccessIdentifier` is accepted only as an
    optional alias carrier using the asset scheme `<asset_id>@<org>.assets`,
    for consumers that must stay on a stock CAMARA field. No MSISDN/IMSI/IP -
    those are public-network subscriber identifiers and have no meaning here.
    """

    model_config = ConfigDict(extra="ignore")
    assetId: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{1,128}$")
    networkAccessIdentifier: Optional[str] = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "Device":
        if not (self.assetId or self.networkAccessIdentifier):
            raise ValueError(
                "device.assetId is required (or networkAccessIdentifier as an asset alias)"
            )
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
    # Private-asset profile extensions (omitted when null). `source`/`kind`
    # let quality-sensitive consumers reason about the fix (a UWB fix is
    # trusted differently from a WiFi fix at the same radius). `altitude` +
    # `verticalAccuracy` carry the third dimension CAMARA's 2D Circle drops
    # (multi-floor / stacked storage).
    source: Optional[str] = None
    kind: Optional[str] = None
    altitude: Optional[float] = None
    verticalAccuracy: Optional[float] = None


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
