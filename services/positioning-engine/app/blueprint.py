"""Blueprint authority: persistence + FloorPlan derivation.

The engine is the canonical, network-distributed home of the venue blueprint
(the placement-editor `layout.json` shape: floor_plans, rooms, anchors, walls).
It persists the raw blueprint on its own writable volume and serves it over
HTTP (`GET /blueprint`), so the demo (via the gateway proxy), the adapters and
any future edge pod read it over the network instead of mounting a shared PVC.
The placement-editor is a write-client (`PUT /blueprint`).

The engine itself only needs `gps_origin` (the floor plan's georef) for the
WGS84 conversion; `_floor_plan_from_blueprint` extracts that into the engine's
`FloorPlan`. The full raw blueprint is what other services consume, so it is
stored and served verbatim.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from .models import Floor, FloorPlan, GpsOrigin

log = logging.getLogger(__name__)


def validate_blueprint(raw: dict) -> None:
    """Best-effort validation against schema/layout.schema.json (the versioned
    layout contract). No-op when jsonschema or the schema file is unavailable -
    the engine degrades rather than blocking authoring. Raises ValueError with a
    one-line reason on a genuine violation; the PUT handler maps it to 422."""
    try:
        import jsonschema
    except ImportError:
        return
    candidates = [os.environ.get("LAYOUT_SCHEMA_PATH"), "/app/schema/layout.schema.json"]
    # Repo-root fallback for running outside a container (tests). Guarded:
    # in-container __file__ has fewer than 4 parents, so index defensively.
    parents = Path(__file__).resolve().parents
    if len(parents) > 3:
        candidates.append(str(parents[3] / "schema" / "layout.schema.json"))
    schema_path = next((c for c in candidates if c and Path(c).is_file()), None)
    if not schema_path:
        return
    try:
        schema = json.loads(Path(schema_path).read_text())
    except (OSError, json.JSONDecodeError):
        return
    try:
        jsonschema.validate(raw, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(exc.message) from exc

# Engine still works with no blueprint at all: it degrades to lat/lon 0 with a
# warning (see geo.py), which is the documented "no GPS reference yet" state.
DEFAULT_FLOOR_PLAN = FloorPlan(
    version=1,
    floors=[Floor(id=0, label="Default", width_m=20.0, depth_m=30.0, height_m=3.0)],
)


def floor_plan_from_blueprint(raw: dict) -> FloorPlan:
    """Build the engine's FloorPlan from a raw blueprint dict. The engine only
    needs gps_origin; the blueprint authors it as floor_plans[0].georef (with a
    legacy top-level gps_origin as fallback). A single Floor is synthesised from
    the floor-plan extent (or first room) so the FloorPlan stays valid and the
    bounds are the real venue, not a generic box."""
    fps = raw.get("floor_plans") or []
    georef = (fps[0].get("georef") if fps else None) or raw.get("gps_origin") or {}
    gps = None
    if georef.get("latitude") is not None and georef.get("longitude") is not None:
        gps = GpsOrigin(
            latitude=float(georef["latitude"]),
            longitude=float(georef["longitude"]),
            azimuth_deg=float(georef.get("azimuth_deg") or 0.0),
            altitude_m=georef.get("altitude_m"),
        )
    w = h = None
    if fps:
        g = fps[0].get("georef") or {}
        w, h = g.get("width_m"), g.get("height_m")
    rooms = raw.get("rooms") or []
    if (not w or not h) and rooms:
        w, h = rooms[0].get("width_m"), rooms[0].get("height_m")
    floor = Floor(
        id=0,
        label=(fps[0].get("label") if fps else None) or "Floor",
        width_m=float(w or 20.0),
        depth_m=float(h or 30.0),
        height_m=3.0,
    )
    return FloorPlan(version=2, gps_origin=gps, floors=[floor])


def load_blueprint(blueprint_path: str, seed_path: str = "") -> Optional[dict[str, Any]]:
    """Return the persisted blueprint as a raw dict, or None when none exists.

    Resolution order:
      1. the engine's own persisted blueprint at `blueprint_path` (RW volume),
      2. a one-time seed from `seed_path` (a read-only mounted layout.json),
         migrated into the persisted store on first boot,
      3. None - the engine boots with no georef and degrades gracefully.

    Never raises: a malformed file logs and falls through.
    """
    p = Path(blueprint_path)
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.error("blueprint at %s unreadable (%s); ignoring", blueprint_path, exc)
    if seed_path:
        sp = Path(seed_path)
        if sp.is_file():
            try:
                raw = json.loads(sp.read_text())
                save_blueprint(blueprint_path, raw)
                log.info("blueprint seeded from %s into %s", seed_path, blueprint_path)
                return raw
            except (OSError, json.JSONDecodeError) as exc:
                log.error("blueprint seed %s unreadable (%s); skipping", seed_path, exc)
    return None


def save_blueprint(blueprint_path: str, raw: dict[str, Any]) -> None:
    """Persist the raw blueprint to the writable volume. Raises on I/O error
    (the PUT handler surfaces it as a 5xx)."""
    p = Path(blueprint_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(raw, indent=2))
