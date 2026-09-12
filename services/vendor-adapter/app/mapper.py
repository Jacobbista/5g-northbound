"""Translate a vendor JSON response into a Measurement dict using a schema."""

from datetime import datetime
from typing import Any, Optional

from .schema import (
    BoolTransform,
    Classify,
    ClassifyPredicate,
    ConstSpec,
    DiscoverMapping,
    FieldSpec,
    LinearTransform,
    Mapping,
    PathSpec,
)
from .vocabulary import EXTENSION_BAG, MOVING_SPEED_THRESHOLD_MPS, is_core


def get_path(obj: Any, dotted: str) -> Any:
    """Dotted-path lookup with list indices: `a.b.0.c` -> obj["a"]["b"][0]["c"].

    Returns None on any missing key, missing index, or non-container traversal.
    """
    cur = obj
    for part in dotted.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _parse_iso8601(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _apply_transform(value: Any, transform) -> Any:
    if isinstance(transform, LinearTransform):
        try:
            return transform.scale * float(value) + transform.offset
        except (TypeError, ValueError):
            return None
    if isinstance(transform, BoolTransform):
        return value in transform.truthy
    return value


def resolve_field(spec: FieldSpec, payload: Any) -> Any:
    if isinstance(spec, ConstSpec):
        return spec.const
    assert isinstance(spec, PathSpec)
    value = get_path(payload, spec.path)
    if value is None:
        value = spec.default
    if value is None:
        return None
    if spec.format == "iso8601":
        value = _parse_iso8601(value)
    if spec.transform is not None and value is not None:
        value = _apply_transform(value, spec.transform)
    return value


def to_measurement(mapping: Mapping, payload: Any, vendor_name: str) -> Optional[dict[str, Any]]:
    """Translate a vendor response payload into the engine's Measurement shape.

    Returns a dict ready to be returned as JSON from GET /measurement/{id}, or
    None when the payload carries no resolvable position (either horizontal
    coordinate absent). None is 'no fix', not a (0,0) phantom: the caller 404s,
    the engine drops the source this cycle, and the gateway surfaces
    UNABLE_TO_LOCATE instead of a bogus location at null island. A field the
    vendor genuinely reports as 0 (a ConstSpec, or a present 0 value) is kept -
    only an absent/unresolvable coordinate means no fix.
    """
    lat_raw = resolve_field(mapping.latitude, payload)
    lon_raw = resolve_field(mapping.longitude, payload)
    if lat_raw is None or lon_raw is None:
        return None
    frame = resolve_field(mapping.frame, payload) or "local"
    out: dict[str, Any] = {
        "source": vendor_name,
        "frame": frame,
        # confidence and y are optional in the mapping; absent -> 0.0.
        "confidence": float(_resolve_optional(mapping.confidence, payload) or 0.0),
    }
    # accuracy is optional: a vendor with no genuine per-fix radius omits the
    # mapping entirely rather than fabricate one. Present-and-zero (a real
    # reported value, however suspect) is kept, matching the coordinate rule
    # above - only an unresolved mapping means "no radius", not a zero one.
    accuracy = _resolve_optional(mapping.accuracy, payload)
    if accuracy is not None:
        out["accuracy"] = float(accuracy)
    if frame == "wgs84":
        out["latitude"] = float(lat_raw)
        out["longitude"] = float(lon_raw)
    else:
        # local frame uses x/z; mapping fields named latitude/longitude carry them
        # by convention so the same spec works for either frame.
        out["x"] = float(lat_raw)
        out["z"] = float(lon_raw)
    out["y"] = float(_resolve_optional(mapping.y, payload) or 0.0)
    ts = resolve_field(mapping.timestamp, payload)
    if ts is not None:
        out["timestamp"] = float(ts)
    # When the device last talked to the vendor, distinct from the fix time
    # (which freezes for a still asset). Carried on the fast path so the engine
    # can broadcast it and consumers derive liveness from it.
    lastSeen = _resolve_optional(mapping.lastSeen, payload)
    if lastSeen is not None:
        out["lastSeen"] = float(lastSeen)
    return out


def _resolve_optional(spec: Optional[FieldSpec], payload: Any) -> Any:
    if spec is None:
        return None
    return resolve_field(spec, payload)


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_discover_entry(mapping: DiscoverMapping, entry: Any) -> Optional[dict[str, Any]]:
    """Map one element from the vendor's device-list response into the
    normalised shape the editor consumes:

        { vendorDeviceId: str,
          label:       str|None,
          latitude:    float|None,
          longitude:   float|None,
          height:    float|None }

    `fixed` is True when the entry resolved a position (a fixed-location
    anchor) and False otherwise (a mobile tag). A single discover list carries
    both; each consumer filters - the editor keeps fixed anchors for the
    blueprint, asset onboarding keeps mobile tags for the registry.

    Returns None when the entry has no `vendorDeviceId` (skipped silently
    so a sparse list element does not break the whole sync).
    """
    raw_id = resolve_field(mapping.vendorDeviceId, entry)
    if raw_id is None or str(raw_id).strip() == "":
        return None
    label_val = _resolve_optional(mapping.label, entry)
    lat = _coerce_float(_resolve_optional(mapping.latitude, entry))
    lon = _coerce_float(_resolve_optional(mapping.longitude, entry))
    device_type_val = _resolve_optional(mapping.deviceType, entry)
    return {
        "vendorDeviceId": str(raw_id),
        "label": str(label_val) if label_val is not None else None,
        "latitude": lat,
        "longitude": lon,
        "height": _coerce_float(_resolve_optional(mapping.height, entry)),
        "deviceType": str(device_type_val) if device_type_val is not None else None,
        "fixed": lat is not None and lon is not None,
    }


def _predicate_matches(pred: Optional[ClassifyPredicate], entry: Any) -> bool:
    """A structural predicate against one raw vendor record. An empty predicate
    (neither `requirePath` nor `path`) never matches."""
    if pred is None:
        return False
    matched_any = False
    if pred.requirePath is not None:
        if get_path(entry, pred.requirePath) is None:
            return False
        matched_any = True
    if pred.path is not None:
        if get_path(entry, pred.path) != pred.equals:
            return False
        matched_any = True
    return matched_any


def classify_entry(classify: Optional[Classify], entry: Any) -> dict[str, Any]:
    """Derive `role` (asset | infrastructure) and `source_class` for one raw
    device record from the schema's classify rules. Returns only the keys the
    schema actually declares, so an unclassified source emits neither."""
    out: dict[str, Any] = {}
    if classify is None:
        return out
    # assetWhen wins if declared: match -> asset, else infrastructure (unknown
    # defaults to infra, not auto-onboarded). infrastructureWhen is the inverse
    # convention: match -> infrastructure, else asset.
    if classify.assetWhen is not None:
        out["role"] = (
            "asset" if _predicate_matches(classify.assetWhen, entry) else "infrastructure"
        )
    elif classify.infrastructureWhen is not None:
        out["role"] = (
            "infrastructure"
            if _predicate_matches(classify.infrastructureWhen, entry)
            else "asset"
        )
    source_class = None
    for rule in classify.sourceClassRules:
        if _predicate_matches(rule.when, entry):
            source_class = rule.value
            break
    if source_class is None:
        source_class = classify.sourceClassDefault
    if source_class:
        out["sourceClass"] = source_class
    return out


def _route_diagnostics(mapping: dict, payload: Any) -> dict[str, Any]:
    """Resolve each mapped field, then split by the core vocabulary: core names
    at the top, everything else under `vendorSpecific`, raw. `moving` is derived from
    the omlox-standard `speed` when the schema did not map `moving` directly.
    Omits any field that does not resolve, so a sparse record stays clean."""
    core: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for name, spec in mapping.items():
        value = resolve_field(spec, payload)
        if value is None:
            continue
        (core if is_core(name) else extra)[name] = value

    # `speed` is not a core output field in v1; it only feeds `moving`.
    speed = extra.pop("speed", None)
    if "moving" not in core and speed is not None:
        try:
            core["moving"] = float(speed) > MOVING_SPEED_THRESHOLD_MPS
        except (TypeError, ValueError):
            pass

    out = dict(core)
    if extra:
        out[EXTENSION_BAG] = extra
    return out


def map_stream_diagnostics(block, payload: Any) -> dict[str, Any]:
    return _route_diagnostics(block.stream, payload)


def map_fetch_diagnostics(fetch, payload: Any) -> dict[str, Any]:
    return _route_diagnostics(fetch.mapping, payload)
