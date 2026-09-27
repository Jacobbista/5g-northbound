// Blueprint version 3 <-> the canvas model the renderer draws.
//
// The blueprint places each level in its parent with the venue-frame
// convention: x along the width, y along the depth, origin at the lower-left
// corner. Drawing uses screen axes, y down from the top-left corner, and names
// depths `height_m`. The conversion happens here, once, when a blueprint
// arrives. The same file lives in the placement editor; both are checked
// against schema/examples.

const plainNumber = (v) => typeof v === "number" && Number.isFinite(v);

function planDepth(blueprint, fp) {
  const d = Number(fp?.georef?.depth_m);
  if (d > 0) return d;
  // No surveyed extent: the rooms' own extent keeps every relative position.
  const rooms = (blueprint.rooms || []).filter((r) => (r.floor_plan_id ?? fp?.id) === fp?.id);
  return rooms.reduce((m, r) => Math.max(m, (Number(r.y_m) || 0) + (Number(r.depth_m) || 0)), 0);
}

// A shallow copy of `obj` with key `from` renamed to `to`, in place.
function rename(obj, from, to) {
  if (!obj || !(from in obj)) return { ...obj };
  const out = {};
  for (const [k, v] of Object.entries(obj)) out[k === from ? to : k] = v;
  return out;
}

// Version 3 -> canvas model. A document that is not version 3 is returned
// unchanged.
export function blueprintToCanvas(blueprint) {
  if (!blueprint || blueprint.version !== 3) return blueprint;
  const fps = blueprint.floor_plans || [];
  const depthOf = Object.fromEntries(fps.map((fp) => [fp.id, planDepth(blueprint, fp)]));
  const firstId = fps[0]?.id;
  return {
    ...blueprint,
    version: 2,
    floor_plans: fps.map((fp) => {
      const D = depthOf[fp.id];
      const out = { ...fp };
      if (fp.georef) out.georef = rename(fp.georef, "depth_m", "height_m");
      if (Array.isArray(fp.scale_calibration_refs)) {
        out.scale_calibration_refs = fp.scale_calibration_refs.map((ref) => {
          const r = { ...ref };
          for (const k of ["p1", "p2"]) {
            if (Array.isArray(ref[k]) && ref[k].length >= 2) r[k] = [ref[k][0], D - ref[k][1]];
          }
          return r;
        });
      }
      return out;
    }),
    rooms: (blueprint.rooms || []).map((room) => {
      const D = depthOf[room.floor_plan_id ?? firstId] ?? 0;
      const d = Number(room.depth_m) || 0;
      const x0 = Number(room.x_m) || 0;
      const yTop = D - ((Number(room.y_m) || 0) + d);
      const out = rename(room, "depth_m", "height_m");
      out.y_m = yTop;
      if (Array.isArray(room.shape)) {
        out.shape = room.shape.map((p) =>
          Array.isArray(p) && p.length >= 2 ? [p[0] + x0, yTop + (d - p[1])] : p
        );
      }
      if (Array.isArray(room.anchors)) {
        out.anchors = room.anchors.map((a) => {
          const r = rename(a, "z", "height_m");
          if (plainNumber(a.y)) r.y = d - a.y;
          return r;
        });
      }
      if (Array.isArray(room.walls)) {
        out.walls = room.walls.map((w) => {
          const r = { ...w };
          for (const k of ["y1", "y2"]) if (plainNumber(w[k])) r[k] = d - w[k];
          return r;
        });
      }
      return out;
    }),
  };
}

// Depth of a floor plan in the canvas model: the surveyed extent, or the
// rooms' own extent when none is set. The mirror axis between the two frames.
export function canvasPlanDepth(model, fp) {
  const d = Number(fp?.georef?.height_m);
  if (d > 0) return d;
  const rooms = (model?.rooms || []).filter((r) => (r.floor_plan_id ?? fp?.id) === fp?.id);
  return rooms.reduce((m, r) => Math.max(m, (Number(r.y_m) || 0) + (Number(r.height_m) || 0)), 0);
}

// Canvas model -> version 3. The inverse of blueprintToCanvas.
export function canvasToBlueprint(model) {
  if (!model || model.version !== 2) return model;
  const fps = model.floor_plans || [];
  const depthOf = Object.fromEntries(fps.map((fp) => [fp.id, canvasPlanDepth(model, fp)]));
  const firstId = fps[0]?.id;
  const { room_w, room_h, aps, gps_origin, walls, floor_plan_image, ...rest } = model;
  return {
    ...rest,
    version: 3,
    floor_plans: fps.map((fp) => {
      const D = depthOf[fp.id];
      const out = { ...fp };
      if (fp.georef) out.georef = rename(fp.georef, "height_m", "depth_m");
      if (Array.isArray(fp.scale_calibration_refs)) {
        out.scale_calibration_refs = fp.scale_calibration_refs.map((ref) => {
          const r = { ...ref };
          for (const k of ["p1", "p2"]) {
            if (Array.isArray(ref[k]) && ref[k].length >= 2) r[k] = [ref[k][0], D - ref[k][1]];
          }
          return r;
        });
      }
      return out;
    }),
    rooms: (model.rooms || []).map((room) => {
      const D = depthOf[room.floor_plan_id ?? firstId] ?? 0;
      const d = Number(room.height_m) || 0;
      const x0 = Number(room.x_m) || 0;
      const y0 = Number(room.y_m) || 0;
      const out = rename(room, "height_m", "depth_m");
      out.y_m = D - (y0 + d);
      if (Array.isArray(room.shape)) {
        out.shape = room.shape.map((p) =>
          Array.isArray(p) && p.length >= 2 ? [p[0] - x0, d - (p[1] - y0)] : p
        );
      }
      if (Array.isArray(room.anchors)) {
        out.anchors = room.anchors.map((a) => {
          const r = { ...a };
          if (plainNumber(a.y)) r.y = d - a.y;
          const out = rename(r, "height_m", "z");
          // An unmeasured mounting height is absent, never null.
          if (out.z == null) delete out.z;
          return out;
        });
      }
      if (Array.isArray(room.walls)) {
        out.walls = room.walls.map((w) => {
          const r = { ...w };
          for (const k of ["y1", "y2"]) if (plainNumber(w[k])) r[k] = d - w[k];
          return r;
        });
      }
      return out;
    }),
  };
}
