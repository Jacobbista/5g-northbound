"""Blueprint migration to version 3, the venue-frame convention.

Version 3 expresses every level of the placement hierarchy (floor plan in the
world, room in the floor plan, anchors and walls in the room) with the same
axes: x along the width, y along the depth, z up, origin at the lower-left
corner of the parent. Horizontal extents are `width_m` (x) and `depth_m` (y).
`height_m` is vertical only.

Version 2 used screen axes (origin top-left, y down) and `height_m` for the
depth of floor plans and rooms. Version 1 is the early floor-plan seed
(`gps_origin` plus `floors`). Every conversion below uses stored values only,
so no measurement is repeated: a y mirror on the parent's depth and key
renames.
"""

import copy
from typing import Any

BLUEPRINT_VERSION = 3

# Top-level keys of the version 1 mirror that version 2 documents still carry.
_LEGACY_TOP_LEVEL = ("room_w", "room_h", "aps", "gps_origin", "walls", "floor_plan_image", "floors")


def blueprint_version(raw: dict[str, Any]) -> int:
    """The major version of a stored blueprint. A document without a version
    that has floor plans or rooms is version 2, the editor's shape before
    versions were enforced."""
    v = raw.get("version")
    try:
        major = int(str(v).split(".")[0])
    except (TypeError, ValueError):
        major = 0
    if major:
        return major
    return 2 if ("floor_plans" in raw or "rooms" in raw) else 1


def migrate_blueprint(raw: dict[str, Any]) -> dict[str, Any]:
    """Return `raw` in version 3. A version 3 document is returned unchanged."""
    version = blueprint_version(raw)
    if version >= BLUEPRINT_VERSION:
        return raw
    if version == 1 and "floor_plans" not in raw and "rooms" not in raw:
        return _from_v1(raw)
    return _from_v2(raw)


def _from_v1(raw: dict[str, Any]) -> dict[str, Any]:
    gps = raw.get("gps_origin") or {}
    floor = (raw.get("floors") or [{}])[0]
    georef = {k: gps[k] for k in ("latitude", "longitude", "azimuth_deg", "altitude_m") if k in gps}
    if floor.get("width_m"):
        georef["width_m"] = floor["width_m"]
    if floor.get("depth_m"):
        georef["depth_m"] = floor["depth_m"]
    floor_plans = [{"id": "fp-01", "label": floor.get("label") or "Floor plan", "georef": georef}] if georef else []
    return {"version": BLUEPRINT_VERSION, "floor_plans": floor_plans, "rooms": []}


def _rename(d: dict[str, Any], old: str, new: str) -> None:
    """Rename a key in place, keeping its position in the document."""
    if old not in d:
        return
    items = [(new if k == old else k, v) for k, v in d.items()]
    d.clear()
    d.update(items)


def _mirror(y: Any, depth: float) -> Any:
    return depth - float(y) if isinstance(y, (int, float)) else y


def _plan_depth(raw: dict[str, Any], fp_id: Any) -> float:
    fps = raw.get("floor_plans") or []
    fp = next((f for f in fps if f.get("id") == fp_id), fps[0] if fps else {})
    depth = float((fp.get("georef") or {}).get("height_m") or 0)
    if depth > 0:
        return depth
    # No surveyed extent: the rooms' own extent keeps every relative position.
    rooms = [r for r in raw.get("rooms") or [] if r.get("floor_plan_id", fp_id) == fp_id]
    return max((float(r.get("y_m") or 0) + float(r.get("height_m") or 0) for r in rooms), default=0.0)


def _from_v2(raw: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(raw)
    if not out.get("floor_plans") and isinstance(raw.get("gps_origin"), dict):
        # A version 2 document that kept its georef only in the legacy mirror.
        gps = raw["gps_origin"]
        out["floor_plans"] = [{"id": "fp-01", "label": "Floor plan", "georef": {
            k: gps[k] for k in ("latitude", "longitude", "azimuth_deg", "altitude_m") if k in gps
        }}]
        for room in out.get("rooms") or []:
            room.setdefault("floor_plan_id", "fp-01")
    for key in _LEGACY_TOP_LEVEL:
        out.pop(key, None)
    out["version"] = BLUEPRINT_VERSION

    for fp in out.get("floor_plans") or []:
        plan_depth = _plan_depth(raw, fp.get("id"))
        georef = fp.get("georef")
        if isinstance(georef, dict):
            _rename(georef, "height_m", "depth_m")
        for ref in fp.get("scale_calibration_refs") or []:
            for key in ("p1", "p2"):
                point = ref.get(key)
                if isinstance(point, list) and len(point) >= 2:
                    ref[key] = [point[0], _mirror(point[1], plan_depth)]

    fp_ids = [f.get("id") for f in raw.get("floor_plans") or []]
    for room in out.get("rooms") or []:
        plan_depth = _plan_depth(raw, room.get("floor_plan_id", fp_ids[0] if fp_ids else None))
        x0 = float(room.get("x_m") or 0)
        y0 = float(room.get("y_m") or 0)
        depth = float(room.get("height_m") or 0)
        _rename(room, "height_m", "depth_m")
        room["y_m"] = plan_depth - (y0 + depth)
        shape = room.get("shape")
        if isinstance(shape, list):
            room["shape"] = [
                [float(p[0]) - x0, depth - (float(p[1]) - y0)]
                if isinstance(p, list) and len(p) >= 2 else p
                for p in shape
            ]
        for anchor in room.get("anchors") or []:
            if "y" in anchor:
                anchor["y"] = _mirror(anchor["y"], depth)
            _rename(anchor, "height_m", "z")
        for wall in room.get("walls") or []:
            for key in ("y1", "y2"):
                if key in wall:
                    wall[key] = _mirror(wall[key], depth)
    return out
