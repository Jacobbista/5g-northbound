// Three-layer placement schema (v2):
//
//   floor_plans[]  ← architectural drawings positioned on the world map
//        ↑
//   rooms[]        ← bounded areas inside a floor plan, where anchors live
//        ↑
//   anchors[]      ← per-technology instruments inside a room
//
// Each layer aligns to the one above it: a floor plan aligns to the real
// world (georef + image bounds), a room aligns to its floor plan (offset +
// rotation in metres), an anchor aligns to its room (x/y in metres). The
// editor's three sections walk the operator through these layers in order.
//
// Room shape: rooms always carry an axis-aligned bbox (x_m / y_m / width_m /
// height_m). They MAY also carry a `shape: [[x, y], ...]` polygon in
// floor-plan-local metres for non-rectangular rooms (L/T/H shapes, irregular
// labs, anything UWB-anchored where precise wall geometry matters). When
// shape is present, the bbox is *derived* from the polygon (= AABB) so the
// engine and section 3 still have a consistent frame; the editor recomputes
// it on every polygon edit.
//
// Legacy v1 layouts (single-room top-level: room_w / room_h / gps_origin /
// aps / walls / floor_plan_image) are normalised into a single floor_plan +
// single room so the new shape is fully backward-compatible at read time.
// Writes always emit v2.

export const DEFAULT_FP_ID = "fp-01";
export const DEFAULT_ROOM_ID = "room-01";
// Default ceiling height for a room when wall_height_m is not set. 2.7 m is
// the common office / lab ceiling - APs mounted to ceiling sit at this
// height by default. Operators can override per-room.
export const DEFAULT_WALL_HEIGHT_M = 2.7;
// Default vertical extent of an opening (door / pass-through) cut out of a
// wall. 2.1 m matches a standard interior door. Operators can override per
// opening for windows / partial-height gaps.
export const DEFAULT_OPENING_HEIGHT_M = 2.1;
// Legacy hint labels for the four rectangle edges. The perimeter opening
// model uses an `edge_index` so it also works for polygon-shaped rooms
// (`room.shape`), but for axis-aligned bboxes the cardinal hint is still
// the fastest way to disambiguate "which side does this door sit on".
// Index convention for rectangle rooms (no shape):
//   0 = N  (0,0)         → (W,0)        - runs along +x
//   1 = E  (W,0)         → (W,H)        - runs along +y
//   2 = S  (0,H)         → (W,H)        - runs along +x (NOT in CW order;
//                                          start_m measured from origin-x)
//   3 = W  (0,0)         → (0,H)        - runs along +y
// For polygon rooms, edge_index = i references the segment from
// `shape[i]` to `shape[(i+1) % shape.length]` in whatever winding order
// the operator drew. The 4 cardinals are convention-only and matter only
// to the editor for the side label; the geometry is regenerated from
// width_m / height_m on every render.
export const PERIMETER_SIDES = ["N", "E", "S", "W"];
export const PERIMETER_SIDE_LABELS = {
  N: "north",
  E: "east",
  S: "south",
  W: "west",
};
const SIDE_TO_INDEX = { N: 0, E: 1, S: 2, W: 3 };

// Resolve the room's perimeter into an ordered list of edges:
//   { start: [x, y], dir: [dx, dy], length, label? }
// Polygon rooms use the shape vertices; rectangle rooms use the four
// cardinal sides in the convention above. Edges that are too short to be
// useful (zero-length, ~0 length) are dropped so downstream code can
// iterate without guarding.
export function perimeterEdges(room) {
  if (!room) return [];
  const w = Number(room.width_m) || 0;
  const h = Number(room.height_m) || 0;
  // Polygon perimeter - shape is in floor-plan-local metres; rebase to
  // room-local by subtracting (x_m, y_m). Section 3 always renders the
  // room axis-aligned.
  if (Array.isArray(room.shape) && room.shape.length >= 3) {
    const baseX = Number(room.x_m) || 0;
    const baseY = Number(room.y_m) || 0;
    const pts = room.shape.map((p) => [
      Number(p[0]) - baseX,
      Number(p[1]) - baseY,
    ]);
    const edges = [];
    for (let i = 0; i < pts.length; i++) {
      const [x1, y1] = pts[i];
      const [x2, y2] = pts[(i + 1) % pts.length];
      const dx = x2 - x1;
      const dy = y2 - y1;
      const length = Math.hypot(dx, dy);
      if (length < 0.05) continue;
      edges.push({ start: [x1, y1], dir: [dx / length, dy / length], length });
    }
    return edges;
  }
  if (w <= 0 || h <= 0) return [];
  return [
    { start: [0, 0], dir: [1, 0], length: w, label: "N" },
    { start: [w, 0], dir: [0, 1], length: h, label: "E" },
    { start: [0, h], dir: [1, 0], length: w, label: "S" },
    { start: [0, 0], dir: [0, 1], length: h, label: "W" },
  ];
}

// Normalise one perimeter-opening record. Older saved layouts (and the
// rectangle-only first iteration of this feature) carried a `side`
// cardinal instead of an `edge_index`; we lift it forward in place.
export function normalizePerimeterOpening(o) {
  if (!o || typeof o !== "object") return null;
  const out = { ...o };
  if (out.edge_index == null && out.side && SIDE_TO_INDEX[out.side] != null) {
    out.edge_index = SIDE_TO_INDEX[out.side];
  }
  if (!Number.isFinite(Number(out.edge_index))) return null;
  out.edge_index = Number(out.edge_index);
  return out;
}

export function emptyLayoutV2() {
  return {
    version: 2,
    floor_plans: [
      {
        id: DEFAULT_FP_ID,
        label: "Floor plan",
        image: null,
        georef: {
          latitude: 0,
          longitude: 0,
          azimuth_deg: 0,
          altitude_m: 0,
          // 0 → "no area defined yet" - UI prompts the operator to
          // upload a reference image or draw a rectangle in step 1.
          width_m: 0,
          height_m: 0,
        },
        // Persisted scale-calibration references. Each entry: { id, p1: [x, y],
        // p2: [x, y], knownM }. Coordinates are in floor-plan-local metres at
        // the current scale (rescaled in lock-step when the plan's scale
        // changes). The operator can re-open the calibration tool to add more
        // references and re-apply for tighter confidence.
        scale_calibration_refs: [],
      },
    ],
    rooms: [
      {
        id: DEFAULT_ROOM_ID,
        label: "Room",
        floor_plan_id: DEFAULT_FP_ID,
        x_m: 0,
        y_m: 0,
        width_m: 10,
        height_m: 10,
        rotation_deg: 0,
        wall_height_m: DEFAULT_WALL_HEIGHT_M,
        anchors: [],
        walls: [],
        perimeter_openings: [],
      },
    ],
  };
}

// Read either v1 or v2; emit v2. v1 layouts get a single floor_plan and a
// single room derived from the top-level fields.
export function normalizeLayout(raw) {
  if (!raw || typeof raw !== "object") return emptyLayoutV2();
  if (raw.version === 2 && Array.isArray(raw.floor_plans) && Array.isArray(raw.rooms)) {
    // Lift legacy `side` perimeter openings to `edge_index` in-place so
    // the rest of the editor only deals with one shape.
    return {
      ...raw,
      rooms: raw.rooms.map((r) => {
        if (!Array.isArray(r.perimeter_openings)) return r;
        const lifted = r.perimeter_openings
          .map(normalizePerimeterOpening)
          .filter(Boolean);
        if (lifted.length === r.perimeter_openings.length &&
            lifted.every((o, i) => o === r.perimeter_openings[i])) {
          return r;
        }
        return { ...r, perimeter_openings: lifted };
      }),
    };
  }

  const room_w = Number(raw.room_w) || 10;
  const room_h = Number(raw.room_h) || 10;
  const gps = raw.gps_origin || {};
  // v1 had no floor-plan concept - a layout was a single room. Do NOT
  // fabricate a floor footprint from the room's dimensions; that would make
  // a 13×32 m rectangle appear on the world map as if the operator had
  // already defined a building outline. Leave width_m/height_m at 0 so the
  // step-1 empty-state prompt fires and the operator picks image or rectangle.
  const fp = {
    id: DEFAULT_FP_ID,
    label: raw.label || "Floor plan",
    image: raw.floor_plan_image || null,
    georef: {
      latitude: Number(gps.latitude) || 0,
      longitude: Number(gps.longitude) || 0,
      azimuth_deg: Number(gps.azimuth_deg) || 0,
      altitude_m: gps.altitude_m == null ? null : Number(gps.altitude_m),
      width_m: 0,
      height_m: 0,
    },
  };
  const room = {
    id: DEFAULT_ROOM_ID,
    label: "Room",
    floor_plan_id: DEFAULT_FP_ID,
    x_m: 0,
    y_m: 0,
    width_m: room_w,
    height_m: room_h,
    rotation_deg: 0,
    wall_height_m: DEFAULT_WALL_HEIGHT_M,
    anchors: Array.isArray(raw.aps) ? raw.aps : [],
    walls: Array.isArray(raw.walls) ? raw.walls : [],
    perimeter_openings: [],
  };
  return { version: 2, floor_plans: [fp], rooms: [room] };
}

// Convenience getters used across the editor.
export const findFloorPlan = (layout, id) =>
  (layout.floor_plans || []).find((fp) => fp.id === id) || null;
export const findRoom = (layout, id) =>
  (layout.rooms || []).find((r) => r.id === id) || null;
export const roomsOnFloorPlan = (layout, fpId) =>
  (layout.rooms || []).filter((r) => r.floor_plan_id === fpId);

// Axis-aligned bounding box of a polygon (array of [x, y] points).
// Returns { x_m, y_m, width_m, height_m } in the same frame as the input.
// Used to keep the rectangle fields in sync whenever a polygon-shaped room
// is edited - section 3 and the engine still rely on the bbox as the room's
// metric frame.
export function bboxOfPolygon(shape) {
  if (!Array.isArray(shape) || shape.length === 0) return null;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of shape) {
    if (!Array.isArray(p) || p.length < 2) continue;
    const [x, y] = p;
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY)) return null;
  return {
    x_m: minX,
    y_m: minY,
    width_m: Math.max(0.5, maxX - minX),
    height_m: Math.max(0.5, maxY - minY),
  };
}

// Centroid of a polygon - area-weighted (not just vertex average), so the
// result is the geometric centre even for irregular shapes. Used by the
// World-position readout when the room has a non-rectangular shape.
export function centroidOfPolygon(shape) {
  if (!Array.isArray(shape) || shape.length < 3) return null;
  let area = 0, cx = 0, cy = 0;
  for (let i = 0; i < shape.length; i++) {
    const [x0, y0] = shape[i];
    const [x1, y1] = shape[(i + 1) % shape.length];
    const cross = x0 * y1 - x1 * y0;
    area += cross;
    cx += (x0 + x1) * cross;
    cy += (y0 + y1) * cross;
  }
  area /= 2;
  if (Math.abs(area) < 1e-9) {
    // Degenerate (zero-area) polygon - fall back to vertex average.
    let sx = 0, sy = 0;
    for (const [x, y] of shape) { sx += x; sy += y; }
    return { x: sx / shape.length, y: sy / shape.length };
  }
  return { x: cx / (6 * area), y: cy / (6 * area) };
}

// Save side: emit v2 alongside legacy top-level fields derived from the
// first floor-plan / first room. The positioning-demo and any v1 consumer
// keep working unchanged; v2-aware consumers pick up floor_plans / rooms.
export function denormalizeForCompat(layout) {
  if (!layout || layout.version !== 2) return layout;
  const fp = layout.floor_plans?.[0] || null;
  const room = layout.rooms?.[0] || null;
  const out = { ...layout };
  if (room) {
    out.room_w = room.width_m;
    out.room_h = room.height_m;
    out.aps = room.anchors || [];
    out.walls = room.walls || [];
  }
  if (fp) {
    if (fp.georef) {
      out.gps_origin = {
        latitude: fp.georef.latitude,
        longitude: fp.georef.longitude,
        azimuth_deg: fp.georef.azimuth_deg,
        altitude_m: fp.georef.altitude_m,
      };
    }
    if (fp.image) out.floor_plan_image = fp.image;
  }
  return out;
}
