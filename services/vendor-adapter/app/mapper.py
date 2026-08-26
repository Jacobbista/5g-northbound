"""Translate a vendor JSON response into a Measurement dict using a schema."""

from datetime import datetime
from typing import Any, Optional

from .schema import (
    Classify,
    ClassifyPredicate,
    ConstSpec,
    DiscoverMapping,
    FieldSpec,
    LinearTransform,
    Mapping,
    PathSpec,
)


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
        "accuracy_m": float(resolve_field(mapping.accuracy_m, payload) or 0.0),
        "confidence": float(resolve_field(mapping.confidence, payload) or 0.0),
    }
    if frame == "wgs84":
        out["latitude"] = float(lat_raw)
        out["longitude"] = float(lon_raw)
    else:
        # local frame uses x/z; mapping fields named latitude/longitude carry them
        # by convention so the same spec works for either frame.
        out["x"] = float(lat_raw)
        out["z"] = float(lon_raw)
    out["y"] = float(resolve_field(mapping.y, payload) or 0.0)
    ts = resolve_field(mapping.timestamp, payload)
    if ts is not None:
        out["timestamp"] = float(ts)
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

        { vendor_device_id: str,
          label:       str|None,
          latitude:    float|None,
          longitude:   float|None,
          height_m:    float|None }

    `fixed` is True when the entry resolved a position (a fixed-location
    anchor) and False otherwise (a mobile tag). A single discover list carries
    both; each consumer filters - the editor keeps fixed anchors for the
    blueprint, asset onboarding keeps mobile tags for the registry.

    Returns None when the entry has no `vendor_device_id` (skipped silently
    so a sparse list element does not break the whole sync).
    """
    raw_id = resolve_field(mapping.vendor_device_id, entry)
    if raw_id is None or str(raw_id).strip() == "":
        return None
    label_val = _resolve_optional(mapping.label, entry)
    lat = _coerce_float(_resolve_optional(mapping.latitude, entry))
    lon = _coerce_float(_resolve_optional(mapping.longitude, entry))
    device_type_val = _resolve_optional(mapping.device_type, entry)
    return {
        "vendor_device_id": str(raw_id),
        "label": str(label_val) if label_val is not None else None,
        "latitude": lat,
        "longitude": lon,
        "height_m": _coerce_float(_resolve_optional(mapping.height_m, entry)),
        "device_type": str(device_type_val) if device_type_val is not None else None,
        "fixed": lat is not None and lon is not None,
    }


def _predicate_matches(pred: Optional[ClassifyPredicate], entry: Any) -> bool:
    """A structural predicate against one raw vendor record. An empty predicate
    (neither `require_path` nor `path`) never matches."""
    if pred is None:
        return False
    matched_any = False
    if pred.require_path is not None:
        if get_path(entry, pred.require_path) is None:
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
    # asset_when wins if declared: match -> asset, else infrastructure (unknown
    # defaults to infra, not auto-onboarded). infrastructure_when is the inverse
    # convention: match -> infrastructure, else asset.
    if classify.asset_when is not None:
        out["role"] = (
            "asset" if _predicate_matches(classify.asset_when, entry) else "infrastructure"
        )
    elif classify.infrastructure_when is not None:
        out["role"] = (
            "infrastructure"
            if _predicate_matches(classify.infrastructure_when, entry)
            else "asset"
        )
    source_class = None
    for rule in classify.source_class_rules:
        if _predicate_matches(rule.when, entry):
            source_class = rule.value
            break
    if source_class is None:
        source_class = classify.source_class_default
    if source_class:
        out["source_class"] = source_class
    return out


def map_stream_diagnostics(block, payload: Any) -> dict[str, Any]:
    """Map the schema's stream-tier diagnostics against a current-fix payload.
    Omits any field that does not resolve, so a sparse record stays clean."""
    out: dict[str, Any] = {}
    for name, spec in block.stream.items():
        value = resolve_field(spec, payload)
        if value is not None:
            out[name] = value
    return out


def map_fetch_diagnostics(fetch, payload: Any) -> dict[str, Any]:
    """Map one on-demand fetch's mapping against its fetched payload."""
    out: dict[str, Any] = {}
    for name, spec in fetch.mapping.items():
        value = resolve_field(spec, payload)
        if value is not None:
            out[name] = value
    return out
