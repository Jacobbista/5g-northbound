"""Blueprint authority: persistence + FloorPlan derivation.

The engine is the canonical, network-distributed home of the venue blueprint
(the placement-editor `layout.json` shape: floor_plans, rooms, anchors, walls).
It persists the raw blueprint on its own writable volume and serves it over
HTTP (`GET /blueprint`), so the demo (via the gateway proxy), the adapters and
any future edge pod read it over the network instead of mounting a shared PVC.
The placement-editor is a write-client (`PUT /blueprint`).

The engine needs the georef of the floor plan and the placement of each room,
which `floor_plan_from_blueprint` extracts into the engine's `FloorPlan`. The
full blueprint is what other services consume, so it is stored and served as
authored, in the current version: an older document is migrated once, at load
or on PUT (see blueprint_migration.py).
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

from .blueprint_migration import blueprint_version, migrate_blueprint
from .models import FloorPlan, GpsOrigin, RoomPlacement

log = logging.getLogger(__name__)


def validate_blueprint(raw: dict) -> None:
    """Validate against schema/layout.schema.json, which `make stage-contracts`
    bakes into the image. Raises ValueError with a one-line reason on a
    violation, which the PUT handler maps to 422. When the schema cannot be
    found the document is accepted and a warning says that it was not
    validated."""
    try:
        import jsonschema
    except ImportError:
        return
    candidates = [
        "/app/contracts/layout.schema.json",  # staged into the image by `make stage-contracts`
        "/app/schema/layout.schema.json",
    ]
    # Repo-root fallback for running outside a container (tests). Guarded:
    # in-container __file__ has fewer than 4 parents, so index defensively.
    parents = Path(__file__).resolve().parents
    if len(parents) > 3:
        candidates.append(str(parents[3] / "schema" / "layout.schema.json"))
    schema_path = next((c for c in candidates if c and Path(c).is_file()), None)
    if not schema_path:
        log.warning("layout.schema.json not found; blueprint accepted without validation")
        return
    try:
        schema = json.loads(Path(schema_path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("layout.schema.json unreadable (%s); blueprint accepted without validation", exc)
        return
    try:
        jsonschema.validate(raw, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(exc.message) from exc

# The engine starts without a blueprint. It then has no georeference and
# answers 503 on GET /position until one is written.
DEFAULT_FLOOR_PLAN = FloorPlan()


def floor_plan_from_blueprint(raw: dict) -> FloorPlan:
    """Build the engine's FloorPlan from a version 3 blueprint: the georef of
    the first floor plan, its extent, and the placement of every room on it."""
    fps = raw.get("floor_plans") or []
    fp = fps[0] if fps else {}
    georef = fp.get("georef") or {}
    gps = None
    # A georeference places the venue only with its origin and its bearing.
    # Without the bearing the orientation is unknown, not north.
    if all(georef.get(k) is not None for k in ("latitude", "longitude", "azimuth_deg")):
        gps = GpsOrigin(
            latitude=float(georef["latitude"]),
            longitude=float(georef["longitude"]),
            azimuth_deg=float(georef["azimuth_deg"]),
            altitude_m=georef.get("altitude_m"),
        )
    elif any(georef.get(k) is not None for k in ("latitude", "longitude", "azimuth_deg")):
        log.warning("floor plan georef lacks latitude, longitude or azimuth_deg; the venue has no georeference")
    rooms: dict[str, RoomPlacement] = {}
    for r in raw.get("rooms") or []:
        if r.get("id") is None or r.get("floor_plan_id", fp.get("id")) != fp.get("id"):
            continue
        placement = [r.get(k) for k in ("x_m", "y_m", "width_m", "depth_m")]
        if any(v is None for v in placement):
            # Not placed in the floor plan: a measurement in it cannot be placed.
            log.warning("room %s lacks x_m, y_m, width_m or depth_m; skipped", r["id"])
            continue
        x_m, y_m, width_m, depth_m = (float(v) for v in placement)
        rooms[str(r["id"])] = RoomPlacement(
            x_m=x_m, y_m=y_m, width_m=width_m, depth_m=depth_m,
            # Absent means unrotated, the default the layout schema declares.
            rotation_deg=float(r.get("rotation_deg", 0.0)),
        )
    return FloorPlan(
        gps_origin=gps,
        width_m=georef.get("width_m"),
        depth_m=georef.get("depth_m"),
        rooms=rooms,
    )


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
            return _migrated(json.loads(p.read_text()), blueprint_path)
        except (OSError, json.JSONDecodeError) as exc:
            log.error("blueprint at %s unreadable (%s); ignoring", blueprint_path, exc)
    if seed_path:
        sp = Path(seed_path)
        if sp.is_file():
            try:
                raw = migrate_blueprint(json.loads(sp.read_text()))
                save_blueprint(blueprint_path, raw)
                log.info("blueprint seeded from %s into %s", seed_path, blueprint_path)
                return raw
            except (OSError, json.JSONDecodeError) as exc:
                log.error("blueprint seed %s unreadable (%s); skipping", seed_path, exc)
    return None


def _migrated(raw: dict[str, Any], blueprint_path: str) -> dict[str, Any]:
    """Migrate a stored blueprint to the current version and persist the result,
    so the conversion runs once per venue."""
    before = blueprint_version(raw)
    out = migrate_blueprint(raw)
    if out is not raw:
        try:
            save_blueprint(blueprint_path, out)
            log.info("blueprint migrated from version %d to %d", before, out["version"])
        except OSError as exc:
            log.warning("blueprint migrated in memory, not persisted (%s)", exc)
    return out


def save_blueprint(blueprint_path: str, raw: dict[str, Any]) -> None:
    """Persist the raw blueprint to the writable volume. Raises on I/O error
    (the PUT handler surfaces it as a 5xx)."""
    p = Path(blueprint_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(raw, indent=2))
