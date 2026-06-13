// Snap-to-OSM-building helper for the placement editor's World step.
//
// Given a (lat, lng) anchor (typically the map centre) and a search radius
// in metres, ask Overpass for nearby building footprints, pick the largest
// one whose footprint overlaps or is closest to the anchor, and return its
// minimum-area oriented bounding box as a georef record:
//   { latitude, longitude, azimuth_deg, width_m, height_m }
// where (latitude, longitude) is the rectangle's lower-left corner in the
// rotated local frame - the same convention as `floor_plans[].georef`.
//
// Why OMBB and not just an axis-aligned bbox: most buildings aren't aligned
// to north, so an axis-aligned bbox would over-cover the footprint and bake
// a wrong azimuth into the area. OMBB on the convex hull recovers the dominant
// edge direction → an azimuth_deg that already lines up with the building.
//
// All maths happens in local east/north metres around the anchor. Latitude
// scaling uses a flat-earth approximation, which is fine for buildings up to
// ~200 m at any latitude on the planet (sub-cm error).

const M_PER_DEG = 111_320;

const OVERPASS_ENDPOINTS = [
  "https://overpass-api.de/api/interpreter",
  "https://overpass.kumi.systems/api/interpreter",
  "https://overpass.private.coffee/api/interpreter",
];

function llToEN(lat, lng, anchorLat, anchorLng) {
  const cosLat = Math.cos((anchorLat * Math.PI) / 180);
  const e = (lng - anchorLng) * M_PER_DEG * cosLat;
  const n = (lat - anchorLat) * M_PER_DEG;
  return { e, n };
}
function enToLL(e, n, anchorLat, anchorLng) {
  const cosLat = Math.cos((anchorLat * Math.PI) / 180);
  const lat = anchorLat + n / M_PER_DEG;
  const lng = anchorLng + e / (M_PER_DEG * cosLat);
  return { lat, lng };
}

// Andrew's monotone chain convex hull. Returns points in CCW order.
function convexHull(points) {
  const pts = points.slice().sort((a, b) => (a.e - b.e) || (a.n - b.n));
  if (pts.length < 3) return pts;
  const cross = (o, a, b) => (a.e - o.e) * (b.n - o.n) - (a.n - o.n) * (b.e - o.e);
  const lower = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) {
      lower.pop();
    }
    lower.push(p);
  }
  const upper = [];
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) {
      upper.pop();
    }
    upper.push(p);
  }
  upper.pop();
  lower.pop();
  return lower.concat(upper);
}

function polygonAreaEN(pts) {
  let a = 0;
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i];
    const q = pts[(i + 1) % pts.length];
    a += p.e * q.n - q.e * p.n;
  }
  return Math.abs(a) / 2;
}

// Rotating-calipers OMBB: for each edge of the convex hull, rotate so that
// edge is horizontal and compute the axis-aligned bbox; keep the smallest.
// Returns { theta, minE, maxE, minN, maxN } in the original east-north frame
// (theta is the angle of the rectangle's local +x axis, measured CCW from east).
function minAreaBBox(hullPts) {
  if (hullPts.length < 3) {
    let minE = Infinity, maxE = -Infinity, minN = Infinity, maxN = -Infinity;
    for (const p of hullPts) {
      if (p.e < minE) minE = p.e;
      if (p.e > maxE) maxE = p.e;
      if (p.n < minN) minN = p.n;
      if (p.n > maxN) maxN = p.n;
    }
    return { theta: 0, minE, maxE, minN, maxN };
  }
  let best = null;
  for (let i = 0; i < hullPts.length; i++) {
    const a = hullPts[i];
    const b = hullPts[(i + 1) % hullPts.length];
    const dx = b.e - a.e;
    const dy = b.n - a.n;
    if (dx === 0 && dy === 0) continue;
    const theta = Math.atan2(dy, dx);
    const cosT = Math.cos(-theta);
    const sinT = Math.sin(-theta);
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const p of hullPts) {
      const x = p.e * cosT - p.n * sinT;
      const y = p.e * sinT + p.n * cosT;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
    const area = (maxX - minX) * (maxY - minY);
    if (!best || area < best.area) {
      best = { area, theta, minX, maxX, minY, maxY };
    }
  }
  return best
    ? { theta: best.theta, minE: best.minX, maxE: best.maxX, minN: best.minY, maxN: best.maxY }
    : null;
}

// Convert an OMBB result back to the placement-editor's georef record. The
// rectangle's lower-left corner (in the rotated frame, x=minX, y=minY) becomes
// the area's origin; width/height are the rotated-frame extents; azimuth_deg
// follows our clockwise-from-north convention:
//   east = x*cos(az) + y*sin(az), north = -x*sin(az) + y*cos(az)
// If the rectangle's local +x is along world direction (cos(theta), sin(theta))
// then matching the rotation gives az = -theta in our convention.
function ombbToGeoref(ombb, anchorLat, anchorLng) {
  const { theta, minE, maxE, minN, maxN } = ombb;
  const width_m = Math.max(0.5, maxE - minE);
  const height_m = Math.max(0.5, maxN - minN);
  // BL in rotated frame, rotated back to world east/north.
  const cosT = Math.cos(theta);
  const sinT = Math.sin(theta);
  const blE = minE * cosT - minN * sinT;
  const blN = minE * sinT + minN * cosT;
  const { lat, lng } = enToLL(blE, blN, anchorLat, anchorLng);
  // theta is CCW math angle; our azimuth_deg is clockwise. Normalise to (-180, 180].
  let azDeg = -(theta * 180) / Math.PI;
  while (azDeg > 180) azDeg -= 360;
  while (azDeg <= -180) azDeg += 360;
  return {
    latitude: lat,
    longitude: lng,
    azimuth_deg: Number(azDeg.toFixed(1)),
    width_m: Number(width_m.toFixed(2)),
    height_m: Number(height_m.toFixed(2)),
  };
}

async function queryOverpass(query) {
  let lastError = null;
  for (const endpoint of OVERPASS_ENDPOINTS) {
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: `data=${encodeURIComponent(query)}`,
      });
      if (!res.ok) {
        lastError = new Error(`overpass ${endpoint} → HTTP ${res.status}`);
        continue;
      }
      return await res.json();
    } catch (e) {
      lastError = e;
      continue;
    }
  }
  throw lastError || new Error("overpass: all endpoints failed");
}

// Parse Overpass `out geom tags` reply into an array of building footprints.
// Each entry carries the polygon vertices + OSM ID so the operator can
// cross-reference on openstreetmap.org from the preview panel.
function extractBuildingsWithMeta(json) {
  const out = [];
  for (const el of json.elements || []) {
    if (el.type === "way" && Array.isArray(el.geometry) && el.geometry.length >= 3) {
      out.push({
        osm_type: "way",
        osm_id: el.id,
        polygon: el.geometry.map((g) => ({ lat: g.lat, lng: g.lon })),
        tags: el.tags || {},
      });
    } else if (el.type === "relation" && Array.isArray(el.members)) {
      for (const m of el.members) {
        if (m.role === "outer" && Array.isArray(m.geometry) && m.geometry.length >= 3) {
          out.push({
            osm_type: "relation",
            osm_id: el.id,
            polygon: m.geometry.map((g) => ({ lat: g.lat, lng: g.lon })),
            tags: el.tags || {},
          });
        }
      }
    }
  }
  return out;
}

// Public entry point. Returns:
//   - { candidates: [{...}], anchor } on success - top buildings by area,
//     each with polygon, georef (OMBB), area_m2, osm_id, name
//   - { error: "..." } on failure (no buildings / overpass down / etc.)
// Caller is expected to surface the error to the user.
export async function fetchBuildingCandidates(anchorLat, anchorLng, radiusM = 120, limit = 6) {
  const r = Math.max(10, Math.min(500, Math.round(radiusM)));
  // `out body geom;` is the canonical "full element body + inline geometry"
  // recipe. The previous `out geom tags;` had the modifier before the
  // verbosity, which Overpass parsed as verbosity=tags + modifier=geom - that
  // form omits relation `members`, so multipolygon buildings (e.g. Electrum
  // at KTH Kista, where the `building=university` tag lives on the relation
  // and not on the outer way) silently dropped out of the candidates.
  const query = `
[out:json][timeout:15];
(
  way["building"](around:${r},${anchorLat},${anchorLng});
  relation["building"](around:${r},${anchorLat},${anchorLng});
);
out body geom;
`.trim();

  let json;
  try {
    json = await queryOverpass(query);
  } catch (e) {
    return { error: `overpass unreachable: ${e.message}` };
  }
  const raw = extractBuildingsWithMeta(json);
  if (raw.length === 0) {
    return { error: `no OSM building within ${r} m of the map centre` };
  }

  // Project each polygon to local east/north, compute area + OMBB, keep the
  // top N by area. Largest wins because small sheds, bike racks, etc. would
  // otherwise dominate "nearest by centroid". If the operator wants a smaller
  // candidate they can pick it from the dropdown.
  const enriched = [];
  for (const b of raw) {
    const pts = b.polygon.map((p) => llToEN(p.lat, p.lng, anchorLat, anchorLng));
    const area = polygonAreaEN(pts);
    if (area <= 0) continue;
    const hull = convexHull(pts);
    const ombb = minAreaBBox(hull);
    if (!ombb) continue;
    const georef = ombbToGeoref(ombb, anchorLat, anchorLng);
    enriched.push({
      polygon: b.polygon,
      georef,
      area_m2: Number(area.toFixed(1)),
      polygon_points: b.polygon.length,
      osm_type: b.osm_type,
      osm_id: b.osm_id,
      name: b.tags.name || b.tags["addr:street"] || null,
    });
  }
  if (enriched.length === 0) {
    return { error: "OSM building geometry was degenerate" };
  }
  enriched.sort((a, b) => b.area_m2 - a.area_m2);
  return {
    candidates: enriched.slice(0, limit),
    anchor: { lat: anchorLat, lng: anchorLng },
    total_found: raw.length,
  };
}

// Back-compat shim - single-best return for any callers still using the old
// signature. New code should use fetchBuildingCandidates + a preview flow.
export async function snapToNearestBuilding(anchorLat, anchorLng, radiusM = 80) {
  const res = await fetchBuildingCandidates(anchorLat, anchorLng, radiusM, 1);
  if (res.error) return res;
  const c = res.candidates[0];
  return {
    georef: c.georef,
    building: {
      area_m2: c.area_m2,
      polygon_points: c.polygon_points,
      candidates: res.total_found,
    },
  };
}
