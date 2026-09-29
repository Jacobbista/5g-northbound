"""Vendor REST schema model.

A schema describes how to fetch and translate one vendor's REST response into
the engine's `Measurement` shape. Operators load it at runtime via
PUT /schema; the example committed under examples/ illustrates the shape but
is not auto-loaded.
"""

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EnvRef(BaseModel):
    """Pointer to an environment variable the operator must set on the pod.

    The name is constrained to what a shell, a ConfigMap and a Secret can all
    carry. The constraint travels in `GET /contract/schema`, so a caller can
    reject a bad name before `PUT /schema`.
    """

    model_config = ConfigDict(extra="forbid")
    env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")


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
    not expose (e.g. `accuracy` when the vendor only reports confidence)."""

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


FRAME_FIELDS = {"wgs84": ("latitude", "longitude"), "venue": ("x", "y")}


class Mapping(BaseModel):
    """Mapping from the vendor response onto the engine `Measurement` fields.

    `frame` is "wgs84" or "venue", and selects the horizontal pair:
    `latitude`/`longitude` in wgs84, `x`/`y` in the venue frame (floor-plan
    lower-left origin, x along the width, y along the depth). A constant frame
    requires its pair and admits only that pair. A frame read from the payload
    admits both pairs, and the resolved frame picks one per record. `z` is the
    height above the venue floor in either frame, mapped only for a source that
    measures it. `accuracy` is optional: a
    vendor with no genuine per-fix radius omits it, and the engine substitutes
    the nominal value of the adapter's accuracy_class.
    """

    model_config = ConfigDict(extra="forbid")
    frame: FieldSpec = Field(
        description="Coordinate frame of the position: 'wgs84' (geographic) or 'venue' (metres from the floor-plan lower-left corner)."
    )
    latitude: Optional[FieldSpec] = Field(
        default=None, description="wgs84 frame: geographic latitude in degrees."
    )
    longitude: Optional[FieldSpec] = Field(
        default=None, description="wgs84 frame: geographic longitude in degrees."
    )
    x: Optional[FieldSpec] = Field(
        default=None,
        json_schema_extra={"x-unit": "m"},
        description="venue frame: metres along the floor-plan width from its lower-left corner.",
    )
    y: Optional[FieldSpec] = Field(
        default=None,
        json_schema_extra={"x-unit": "m"},
        description="venue frame: metres along the floor-plan depth from its lower-left corner.",
    )
    accuracy: Optional[FieldSpec] = Field(
        default=None,
        json_schema_extra={"x-unit": "m"},
        description=(
            "Horizontal accuracy radius; surfaced as the core `accuracy` diagnostic. "
            "Omit when the vendor reports no genuine per-fix radius (a confidence "
            "score is not a radius - map that to `confidence` instead). The engine "
            "falls back to a nominal value for the adapter's declared accuracy_class "
            "rather than fusing a fabricated number."
        ),
    )
    confidence: Optional[FieldSpec] = Field(
        default=None,
        description="Optional fix confidence in [0,1]. Omit when the vendor reports none: the engine then weights the fix by its accuracy alone.",
    )
    z: Optional[FieldSpec] = Field(
        default=None,
        json_schema_extra={"x-unit": "m"},
        description=(
            "Height above the venue floor, in either frame. Map it only when the source "
            "measures height and declares `z: true`, translating another reference with a "
            "`linear` transform. A record where it resolves to null carries no height."
        ),
    )
    verticalAccuracy: Optional[FieldSpec] = Field(
        default=None,
        json_schema_extra={"x-unit": "m"},
        description=(
            "One-sigma error of `z`, in metres. Map it only with `z`, and only when the vendor "
            "reports it. A record where it resolves to null carries no vertical error."
        ),
    )
    timestamp: FieldSpec = Field(
        description="Fix time. A PathSpec with format:'iso8601' coerces an ISO string to epoch seconds; a numeric epoch passes through.",
    )
    lastSeen: Optional[FieldSpec] = Field(
        default=None,
        description=(
            "Optional time the device last communicated with the vendor. This is NOT the fix "
            "time: a still asset freezes its fix while still reporting, so this is the signal "
            "that drives liveness downstream. Use format:'iso8601' for an ISO string. Omit when "
            "the vendor exposes no such field."
        ),
    )

    @model_validator(mode="after")
    def _vertical_error_needs_height(self) -> "Mapping":
        if self.verticalAccuracy is not None and self.z is None:
            raise ValueError("verticalAccuracy is the error of z: map z too")
        return self

    @model_validator(mode="after")
    def _horizontal_pair(self) -> "Mapping":
        pairs = {
            frame: [getattr(self, f) is not None for f in fields]
            for frame, fields in FRAME_FIELDS.items()
        }
        for frame, present in pairs.items():
            if any(present) and not all(present):
                raise ValueError(f"{frame} frame: map both of {', '.join(FRAME_FIELDS[frame])}")
        if isinstance(self.frame, ConstSpec):
            frame = self.frame.const
            if frame not in FRAME_FIELDS:
                raise ValueError(f"frame must be one of {sorted(FRAME_FIELDS)}, got {frame!r}")
            other = "venue" if frame == "wgs84" else "wgs84"
            if not all(pairs[frame]):
                raise ValueError(f"frame {frame!r} requires {', '.join(FRAME_FIELDS[frame])}")
            if any(pairs[other]):
                raise ValueError(f"frame {frame!r} admits only {', '.join(FRAME_FIELDS[frame])}")
        elif not any(all(v) for v in pairs.values()):
            raise ValueError("map latitude/longitude, x/y, or both")
        return self


class DiscoverMapping(BaseModel):
    """Field mapping for one entry in the vendor's device list.

    The editor's sync flow consumes a normalised shape with these keys.
    Optional fields default to None when the vendor does not expose them.
    """

    model_config = ConfigDict(extra="forbid")
    vendorDeviceId: FieldSpec
    label: Optional[FieldSpec] = None
    latitude: Optional[FieldSpec] = None
    longitude: Optional[FieldSpec] = None
    # Mounting height above the venue floor, the vertical of every contract.
    z: Optional[FieldSpec] = Field(default=None, json_schema_extra={"x-unit": "m"})
    # Native vendor device type (e.g. Wittra `deviceType`: "beacon" / "tag" /
    # "meshrouter" / "gateway"). Surfaced as `deviceType` on discovery and used
    # by the `classify` block's predicates to derive role + source_class.
    deviceType: Optional[FieldSpec] = None


class Pagination(BaseModel):
    """How to walk the vendor's pagination, if any.

    `type = page`: query params control 1-indexed page number + page size,
    body carries the total count under `totalPath`. Pull pages until the
    accumulated list reaches `total`.

    `type = none`: response carries the full list in one go.
    """

    model_config = ConfigDict(extra="forbid")
    type: Literal["none", "page"] = "none"
    pageParam: str = "page"
    sizeParam: str = "size"
    pageSize: int = 100
    totalPath: str = "total"


class DiscoverFilter(BaseModel):
    """Optional per-entry filter. Drops an entry from the discover output
    when the named dotted path resolves to None / missing. Useful when the
    vendor exposes both mobile tags (no position) and anchors (with
    position) under the same list endpoint and the editor only wants the
    anchors.
    """

    model_config = ConfigDict(extra="ignore")
    # Skip the entry when get_path(entry, requirePath) is None.
    requirePath: Optional[str] = None


class ClassifyPredicate(BaseModel):
    """A structural test against one raw vendor device record. Matches when:
      - `requirePath` (if set) resolves to a non-null value, AND
      - `path` == `equals` (if both set).
    Vendors differ: some expose a clean type string (Wittra's `deviceType` is
    "beacon" / "tag" / "meshrouter" / "gateway" - match with `path` + `equals`);
    others only encode it structurally, as a sub-object's presence (a MIOTY node
    has a `miotyConfig`, a border router has a `borderrouter` - match with
    `requirePath`). Both forms are the schema author's, written against the
    vendor's own fields; the adapter code stays vendor-agnostic."""

    model_config = ConfigDict(extra="forbid")
    requirePath: Optional[str] = None
    path: Optional[str] = None
    equals: Optional[Any] = None


class SourceClassRule(BaseModel):
    """When `when` matches, the device's `source_class` is `value`. First
    matching rule wins; `Classify.sourceClassDefault` applies if none do."""

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
          * `assetWhen`          - match -> asset, else infrastructure.
            Positively names the asset; an UNKNOWN device defaults to
            infrastructure (conservative: not auto-onboarded). Preferred when
            the vendor's device list is mostly fixed gear and only a small,
            named type is trackable (Wittra: `deviceType == tag`).
          * `infrastructureWhen` - match -> infrastructure, else asset.
            An unknown device defaults to asset (onboardable). Use when the
            trackable set is open-ended and infra is the small, named set.
      - source_class: the positioning technology (uwb / ble / wifi / gnss /
        cellular / mioty / other) - the paper's optional `source-class` field.
        `rules` map structural predicates to a class; `default` applies
        otherwise.

    Everything is optional: declare neither role predicate and no `role` is
    emitted (every candidate stays onboardable); omit source_class and none is
    emitted. If both role predicates are set, `assetWhen` wins.
    """

    model_config = ConfigDict(extra="forbid")
    assetWhen: Optional[ClassifyPredicate] = None
    infrastructureWhen: Optional[ClassifyPredicate] = None
    sourceClassDefault: Optional[str] = None
    sourceClassRules: list[SourceClassRule] = Field(default_factory=list)


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
    listPath: str = ""
    pathVars: dict[str, EnvRef] = Field(default_factory=dict)
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
    listPath: str = ""
    pathVars: dict[str, EnvRef] = Field(default_factory=dict)
    mapping: dict[str, FieldSpec] = Field(default_factory=dict)


class DiagnosticsBlock(BaseModel):
    """Optional vendor fidelity telemetry, delivered in two tiers.

    `stream` fields resolve against the SAME record `/measurement` maps (the
    current-fix payload), so motion rides the broadcast at no extra fetch.
    `onDemand` entries are extra vendor fetches, issued only by the
    GET /diagnostics/{id} endpoint."""
    model_config = ConfigDict(extra="forbid")
    stream: dict[str, FieldSpec] = Field(default_factory=dict)
    onDemand: list[DiagnosticsFetch] = Field(default_factory=list)


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vendor: str
    # Source-side ingest transport. The engine-facing contract is always pull
    # (GET /measurement/{id}); this only changes how the adapter reaches the
    # vendor. Only `rest` (pull-through) is implemented; `mqtt` (subscribe +
    # cache) and `webhook` (push) are declared extension points.
    transport: Literal["rest", "mqtt", "webhook"] = "rest"
    # The vendor's API root. An EnvRef, never a literal: the image is generic
    # and the URL is operator input, so the document names only the variable
    # the operator fills.
    baseUrl: EnvRef
    path: str
    pathVars: dict[str, EnvRef] = Field(default_factory=dict)
    auth: Auth
    cacheTtl: float = Field(default=5.0, json_schema_extra={"x-unit": "s"})
    requestTimeout: float = Field(default=5.0, json_schema_extra={"x-unit": "s"})
    mapping: Mapping
    discover: Optional[DiscoverBlock] = None
    diagnostics: Optional[DiagnosticsBlock] = None
