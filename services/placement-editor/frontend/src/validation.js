// Pure validators used both for disabling the save button and for surfacing
// the reason to the operator. Returns a list of {field, message} so the UI
// can render them next to the relevant input.

// Validates both v1 (single-room top-level) and v2 (floor_plans + rooms).
// In v2 every room is validated independently; the field keys keep the same
// shape so the existing inspector can highlight problems.
export function validateLayout(layout) {
  const errors = [];
  if (!layout) return errors;

  // v2 path
  if (Array.isArray(layout.rooms)) {
    for (const room of layout.rooms) {
      if (!(Number(room.width_m) > 0)) {
        errors.push({ field: "room_w", message: `${room.id}: width must be > 0` });
      }
      if (!(Number(room.height_m) > 0)) {
        errors.push({ field: "room_h", message: `${room.id}: height must be > 0` });
      }
      validateAnchors(room.anchors || [], errors);
      validateWalls(room.walls || [], errors);
    }
    return errors;
  }

  // v1 fallback
  if (!(Number(layout.room_w) > 0)) {
    errors.push({ field: "room_w", message: "Room width must be > 0" });
  }
  if (!(Number(layout.room_h) > 0)) {
    errors.push({ field: "room_h", message: "Room depth must be > 0" });
  }
  validateAnchors(layout.aps || [], errors);
  validateWalls(layout.walls || [], errors);
  return errors;
}

function validateAnchors(anchors, errors) {
  const seen = new Map();
  for (const ap of anchors) {
    const id = (ap.id || "").trim();
    if (id === "") {
      errors.push({ field: `ap:${ap.id}`, message: "AP id cannot be empty" });
      continue;
    }
    if (seen.has(id)) {
      errors.push({ field: `ap:${id}`, message: `Duplicate AP id: ${id}` });
    } else {
      seen.set(id, ap);
    }
    if (!Number.isFinite(Number(ap.x)) || !Number.isFinite(Number(ap.y))) {
      errors.push({ field: `ap:${id}`, message: `${id}: x/y must be numbers` });
    }
  }
}

function validateWalls(walls, errors) {
  const wseen = new Map();
  for (const w of walls) {
    const id = (w.id || "").trim();
    if (id === "") {
      errors.push({ field: `wall:${w.id}`, message: "Wall id cannot be empty" });
      continue;
    }
    if (wseen.has(id)) {
      errors.push({ field: `wall:${id}`, message: `Duplicate wall id: ${id}` });
    } else {
      wseen.set(id, w);
    }
    const len = wallLength(w);
    if (!Number.isFinite(len) || len < 0.05) {
      errors.push({ field: `wall:${id}`, message: `${id}: zero-length wall` });
    }
  }
}

export function wallLength(w) {
  const dx = Number(w.x2) - Number(w.x1);
  const dy = Number(w.y2) - Number(w.y1);
  if (!Number.isFinite(dx) || !Number.isFinite(dy)) return NaN;
  return Math.hypot(dx, dy);
}

export function snap(value, step) {
  if (!step || step <= 0) return value;
  return Math.round(value / step) * step;
}
