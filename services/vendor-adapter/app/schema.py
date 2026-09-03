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


class BoolTransform(BaseModel):
    """Coerce a vendor value to a boolean: True when it equals one of `truthy`.
    Lets a vendor's moving/stationary state map onto the core `moving` field."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["bool"]
    truthy: list[Any] = Field(default_factory=list)


Transform = Annotated[
    Union[LinearTransform, BoolTransform], Field(discriminator="type")
]


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
    # Native vendor device type (e.g. Wittra `deviceType`: "beacon" / "tag" /
    # "meshrouter" / "gateway"). Surfaced as `device_type` on discovery and used
    # by the `classify` block's predicates to derive role + source_class.
    device_type: Optional[FieldSpec] = None


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


class ClassifyPredicate(BaseModel):
    """A structural test against one raw vendor device record. Matches when:
      - `require_path` (if set) resolves to a non-null value, AND
      - `path` == `equals` (if both set).
    Vendors differ: some expose a clean type string (Wittra's `deviceType` is
    "beacon" / "tag" / "meshrouter" / "gateway" - match with `path` + `equals`);
    others only encode it structurally, as a sub-object's presence (a MIOTY node
    has a `miotyConfig`, a border router has a `borderrouter` - match with
    `require_path`). Both forms are the schema author's, written against the
    vendor's own fields; the adapter code stays vendor-agnostic."""

    model_config = ConfigDict(extra="forbid")
    require_path: Optional[str] = None
    path: Optional[str] = None
    equals: Optional[Any] = None


class SourceClassRule(BaseModel):
    """When `when` matches, the device's `source_class` is `value`. First
    matching rule wins; `Classify.source_class_default` applies if none do."""

    model_config = ConfigDict(extra="forbid")
    when: ClassifyPredicate
    value: str


class Classify(BaseModel):
    """Schema-declared classification for onboarding discovery. Two axes, both
    from the paper's private-asset model:

      - role: `infrastructure` (fixed sensor: UWB anchor, mesh router, gateway -
        outside the 3GPP trust domain, never onboarded as an asset) vs `asset`
        (the tracked entity). Declare exactly ONE of two predicates, which sets
        the default for an unmatched device:
          * `asset_when`          - match -> asset, else infrastructure.
            Positively names the asset; an UNKNOWN device defaults to
            infrastructure (conservative: not auto-onboarded). Preferred when
            the vendor's device list is mostly fixed gear and only a small,
            named type is trackable (Wittra: `deviceType == tag`).
          * `infrastructure_when` - match -> infrastructure, else asset.
            An unknown device defaults to asset (onboardable). Use when the
            trackable set is open-ended and infra is the small, named set.
      - source_class: the positioning technology (uwb / ble / wifi / gnss /
        cellular / mioty / other) - the paper's optional `source-class` field.
        `rules` map structural predicates to a class; `default` applies
        otherwise.

    Everything is optional: declare neither role predicate and no `role` is
    emitted (every candidate stays onboardable); omit source_class and none is
    emitted. If both role predicates are set, `asset_when` wins.
    """

    model_config = ConfigDict(extra="forbid")
    asset_when: Optional[ClassifyPredicate] = None
    infrastructure_when: Optional[ClassifyPredicate] = None
    source_class_default: Optional[str] = None
    source_class_rules: list[SourceClassRule] = Field(default_factory=list)


class DiscoverBlock(BaseModel):
    """Optional second endpoint the schema can declare: a list of devices
    the editor uses to populate / sync UWB (or any vendor-managed) anchors,
    and the source onboarding discovery reads (unfiltered) to list candidates.
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
    # The editor's anchor-only include filter. Onboarding discovery reads the
    # list UNFILTERED (it wants the tags this drops), so `/devices` bypasses it.
    filter: Optional[DiscoverFilter] = None
    # Role + source_class classification for onboarding. Schema-declared so a
    # different vendor classifies with its own fields - no adapter code changes.
    classify: Optional[Classify] = None


class DiagnosticsFetch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    list_path: str = ""
    path_vars: dict[str, EnvRef] = Field(default_factory=dict)
    mapping: dict[str, FieldSpec] = Field(default_factory=dict)


class DiagnosticsBlock(BaseModel):
    """Optional vendor fidelity telemetry, delivered in two tiers.

    `stream` fields resolve against the SAME record `/measurement` maps (the
    current-fix payload), so motion rides the broadcast at no extra fetch.
    `on_demand` entries are extra vendor fetches, issued only by the
    GET /diagnostics/{id} endpoint."""
    model_config = ConfigDict(extra="forbid")
    stream: dict[str, FieldSpec] = Field(default_factory=dict)
    on_demand: list[DiagnosticsFetch] = Field(default_factory=list)


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor: str
    # Source-side ingest transport. The engine-facing contract is always pull
    # (GET /measurement/{id}); this only changes how the adapter reaches the
    # vendor. Only `rest` (pull-through) is implemented; `mqtt` (subscribe +
    # cache) and `webhook` (push) are declared extension points.
    transport: Literal["rest", "mqtt", "webhook"] = "rest"
    default_base_url: str
    base_url_env: Optional[str] = None
    path: str
    path_vars: dict[str, EnvRef] = Field(default_factory=dict)
    auth: Auth
    cache_ttl_s: float = 5.0
    request_timeout_s: float = 5.0
    mapping: Mapping
    discover: Optional[DiscoverBlock] = None
    diagnostics: Optional[DiagnosticsBlock] = None
