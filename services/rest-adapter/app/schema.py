"""Vendor REST schema model.

A schema describes how to fetch and translate one vendor's REST response into
the engine's `Measurement` shape. Operators load it at runtime via
PUT /schema; the example committed under examples/ illustrates the shape but
is not auto-loaded.
"""

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class EnvRef(BaseModel):
    """Pointer to an environment variable the operator must set on the pod."""

    model_config = ConfigDict(extra="forbid")
    env: str


# --- Auth schemes (discriminated by `scheme`) -------------------------------


class AuthNone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheme: Literal["none"]


class AuthBasic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheme: Literal["basic"]
    username: EnvRef
    password: EnvRef


class AuthBearer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheme: Literal["bearer"]
    token: EnvRef


class AuthHeader(BaseModel):
    """Custom header carrying a token, e.g. X-API-Key."""

    model_config = ConfigDict(extra="forbid")
    scheme: Literal["header"]
    header: str
    value: EnvRef


Auth = Annotated[
    Union[AuthNone, AuthBasic, AuthBearer, AuthHeader],
    Field(discriminator="scheme"),
]


# --- Field specs (const-or-path) --------------------------------------------


class LinearTransform(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["linear"]
    scale: float
    offset: float = 0.0


Transform = Annotated[Union[LinearTransform], Field(discriminator="type")]


class ConstSpec(BaseModel):
    """A constant value, returned verbatim. Use for fields the vendor does
    not expose (e.g. `accuracy_m` when the vendor only reports confidence)."""

    model_config = ConfigDict(extra="forbid")
    const: Any


class PathSpec(BaseModel):
    """Pull from the vendor response by dotted path. Supports list indices
    (`a.b.0.c`). `default` is used when the path is absent or null."""

    model_config = ConfigDict(extra="forbid")
    path: str
    default: Optional[Any] = None
    transform: Optional[Transform] = None
    format: Optional[Literal["iso8601"]] = None


FieldSpec = Union[ConstSpec, PathSpec]


# --- Top-level schema -------------------------------------------------------


class Mapping(BaseModel):
    """Mapping from vendor response onto the engine `Measurement` fields.

    `frame` may be either "local" or "wgs84". The other six fields each carry
    a ConstSpec or a PathSpec.
    """

    model_config = ConfigDict(extra="forbid")
    frame: FieldSpec
    latitude: FieldSpec
    longitude: FieldSpec
    accuracy_m: FieldSpec
    confidence: FieldSpec
    y: FieldSpec
    timestamp: FieldSpec


class DiscoverMapping(BaseModel):
    """Field mapping for one entry in the vendor's device list.

    The editor's sync flow consumes a normalised shape with these keys.
    Optional fields default to None when the vendor does not expose them.
    """

    model_config = ConfigDict(extra="forbid")
    vendor_device_id: FieldSpec
    label: Optional[FieldSpec] = None
    latitude: Optional[FieldSpec] = None
    longitude: Optional[FieldSpec] = None
    height_m: Optional[FieldSpec] = None


class Pagination(BaseModel):
    """How to walk the vendor's pagination, if any.

    `type = page`: query params control 1-indexed page number + page size,
    body carries the total count under `total_path`. Pull pages until the
    accumulated list reaches `total`.

    `type = none`: response carries the full list in one go.
    """

    model_config = ConfigDict(extra="forbid")
    type: Literal["none", "page"] = "none"
    page_param: str = "page"
    size_param: str = "size"
    page_size: int = 100
    total_path: str = "total"


class DiscoverFilter(BaseModel):
    """Optional per-entry filter. Drops an entry from the discover output
    when the named dotted path resolves to None / missing. Useful when the
    vendor exposes both mobile tags (no position) and anchors (with
    position) under the same list endpoint and the editor only wants the
    anchors.
    """

    model_config = ConfigDict(extra="ignore")
    # Skip the entry when get_path(entry, require_path) is None.
    require_path: Optional[str] = None


class DiscoverBlock(BaseModel):
    """Optional second endpoint the schema can declare: a list of devices
    the editor uses to populate / sync UWB (or any vendor-managed) anchors.
    Independent from the single-device telemetry endpoint that the engine
    polls; uses the same auth + base URL.
    """

    model_config = ConfigDict(extra="ignore")
    path: str
    # JSON dotted path to the array inside the response. Empty / "" means
    # the response itself IS the array.
    list_path: str = ""
    path_vars: dict[str, EnvRef] = Field(default_factory=dict)
    pagination: Pagination = Field(default_factory=Pagination)
    mapping: DiscoverMapping
    filter: Optional[DiscoverFilter] = None


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor: str
    default_base_url: str
    base_url_env: Optional[str] = None
    path: str
    path_vars: dict[str, EnvRef] = Field(default_factory=dict)
    auth: Auth
    cache_ttl_s: float = 5.0
    request_timeout_s: float = 5.0
    mapping: Mapping
    discover: Optional[DiscoverBlock] = None
