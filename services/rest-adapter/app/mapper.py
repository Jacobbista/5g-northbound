"""Translate a vendor JSON response into a Measurement dict using a schema."""

from datetime import datetime
from typing import Any, Optional

from .schema import (
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


def to_measurement(mapping: Mapping, payload: Any, vendor_name: str) -> dict[str, Any]:
    """Translate a vendor response payload into the engine's Measurement shape.

    Returns a dict ready to be returned as JSON from GET /measurement/{id}.
    Missing required fields fall back to safe defaults so the engine sees a
    well-formed reply (the operator is expected to validate the schema first).
    """
    frame = resolve_field(mapping.frame, payload) or "local"
    out: dict[str, Any] = {
        "source": vendor_name,
        "frame": frame,
        "accuracy_m": float(resolve_field(mapping.accuracy_m, payload) or 0.0),
        "confidence": float(resolve_field(mapping.confidence, payload) or 0.0),
    }
    if frame == "wgs84":
        out["latitude"] = float(resolve_field(mapping.latitude, payload) or 0.0)
        out["longitude"] = float(resolve_field(mapping.longitude, payload) or 0.0)
    else:
        # local frame uses x/z; mapping fields named latitude/longitude carry them
        # by convention so the same spec works for either frame.
        out["x"] = float(resolve_field(mapping.latitude, payload) or 0.0)
        out["z"] = float(resolve_field(mapping.longitude, payload) or 0.0)
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
