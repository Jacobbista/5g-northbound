// Where a fix sits in the room the scene draws.
//
// The engine reports fixes in WGS84. The chain back to the room follows the
// blueprint: the georef places the floor plan in the world (venue frame, x
// along the width, y along the depth, azimuth_deg the bearing of +y), and the
// room sits in the floor plan at its lower-left corner, rotated clockwise about
// its centre. The engine applies the same chain forward.
//
// The scene draws the room in screen axes: x right, z down from the room's top
// edge. `scene` below means that frame.

const M_PER_DEG = 111320;

// Frame of the first room of a version 3 blueprint, or null without a
// complete georef (origin and bearing) or a placed room, as the engine judges.
export function frameFromBlueprint(blueprint) {
  const fp = blueprint?.floor_plans?.[0];
  const g = fp?.georef;
  const room = (blueprint?.rooms || []).find((r) => (r.floor_plan_id ?? fp?.id) === fp?.id);
  if (!g || [g.latitude, g.longitude, g.azimuth_deg].some((v) => v == null)) return null;
  if (!room || [room.x_m, room.y_m, room.width_m, room.depth_m].some((v) => v == null)) return null;
  return {
    lat0: Number(g.latitude),
    lon0: Number(g.longitude),
    az: (Number(g.azimuth_deg) * Math.PI) / 180,
    room: {
      id: room.id,
      x_m: Number(room.x_m),
      y_m: Number(room.y_m),
      width_m: Number(room.width_m),
      depth_m: Number(room.depth_m),
      rot: ((Number(room.rotation_deg) || 0) * Math.PI) / 180,
    },
  };
}

function gpsToVenue(lat, lon, f) {
  const east = (lon - f.lon0) * M_PER_DEG * Math.cos((f.lat0 * Math.PI) / 180);
  const north = (lat - f.lat0) * M_PER_DEG;
  return {
    x: east * Math.cos(f.az) - north * Math.sin(f.az),
    y: east * Math.sin(f.az) + north * Math.cos(f.az),
  };
}

function venueToGps(x, y, f) {
  const east = x * Math.cos(f.az) + y * Math.sin(f.az);
  const north = -x * Math.sin(f.az) + y * Math.cos(f.az);
  return {
    lat: f.lat0 + north / M_PER_DEG,
    lon: f.lon0 + east / (M_PER_DEG * Math.cos((f.lat0 * Math.PI) / 180)),
  };
}

export function roomToVenue(x, y, f) {
  const r = f.room;
  const cx = r.x_m + r.width_m / 2;
  const cy = r.y_m + r.depth_m / 2;
  const dx = r.x_m + x - cx;
  const dy = r.y_m + y - cy;
  return {
    x: cx + dx * Math.cos(r.rot) + dy * Math.sin(r.rot),
    y: cy - dx * Math.sin(r.rot) + dy * Math.cos(r.rot),
  };
}

export function venueToRoom(x, y, f) {
  const r = f.room;
  const cx = r.x_m + r.width_m / 2;
  const cy = r.y_m + r.depth_m / 2;
  const dx = x - cx;
  const dy = y - cy;
  return {
    x: cx + dx * Math.cos(r.rot) - dy * Math.sin(r.rot) - r.x_m,
    y: cy + dx * Math.sin(r.rot) + dy * Math.cos(r.rot) - r.y_m,
  };
}

// Room frame <-> scene: the same point, y up from the bottom edge or z down
// from the top edge.
export const roomToScene = (x, y, f) => ({ x, z: f.room.depth_m - y });
export const sceneToRoom = (x, z, f) => ({ x, y: f.room.depth_m - z });

export function gpsToScene(lat, lon, f) {
  if (!f) return null;
  const v = gpsToVenue(lat, lon, f);
  const r = venueToRoom(v.x, v.y, f);
  return roomToScene(r.x, r.y, f);
}

export function sceneToGps(x, z, f) {
  if (!f) return null;
  const r = sceneToRoom(x, z, f);
  const v = roomToVenue(r.x, r.y, f);
  return venueToGps(v.x, v.y, f);
}

// A WGS84 fix in the room frame, the coordinates the blueprint and the
// contracts use.
export function gpsToRoom(lat, lon, f) {
  if (!f) return null;
  const v = gpsToVenue(lat, lon, f);
  return venueToRoom(v.x, v.y, f);
}
