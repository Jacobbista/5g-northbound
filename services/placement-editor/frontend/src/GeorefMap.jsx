import { forwardRef, Fragment, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import {
  Circle,
  CircleMarker,
  ImageOverlay,
  LayersControl,
  MapContainer,
  Marker,
  Polygon,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
  ZoomControl,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { fetchBuildingCandidates } from "./osmBuildings.js";
import { toast } from "./toast.js";

const { BaseLayer, Overlay } = LayersControl;

const M_PER_DEG = 111_320.0;

// Reliable tile providers (CARTO + ESRI). The direct openstreetmap.org tile
// CDN sometimes rate-limits or is blocked by privacy browsers; CARTO is the
// usual fallback. The testbed can override either via window.__ENV__.
const TILES = {
  street: {
    url: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    maxNativeZoom: 19,
  },
  satellite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics",
    maxNativeZoom: 19,
  },
  // Google satellite + hybrid via the public mt0 tile endpoint. Higher-res
  // than ESRI in most urban areas and refreshed more often. Use for visual
  // diagnostics / cross-checking against vendor maps that use Mapbox or
  // Google. Note: Google's ToS only permits these tiles when consumed via
  // the official Maps JS API; treat this as a development/diagnostic aid,
  // not a production basemap.
  google_satellite: {
    url: "https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}",
    attribution: "Imagery &copy; Google",
    maxNativeZoom: 21,
  },
  google_hybrid: {
    url: "https://mt0.google.com/vt/lyrs=y&hl=en&x={x}&y={y}&z={z}",
    attribution: "Imagery &copy; Google",
    maxNativeZoom: 21,
  },
};
const overrideStreet =
  (typeof window !== "undefined" && window.__ENV__?.VITE_MAP_TILE_URL) || null;
if (overrideStreet) TILES.street.url = overrideStreet;
// Optional Mapbox Satellite-Streets layer. Enabled only when the operator
// configures a token via window.__ENV__.VITE_MAPBOX_TOKEN. Higher-res +
// matches what most vendor portals (e.g. Wittra) ship on.
const MAPBOX_TOKEN =
  (typeof window !== "undefined" && window.__ENV__?.VITE_MAPBOX_TOKEN) || null;
if (MAPBOX_TOKEN) {
  TILES.mapbox_satellite = {
    url: `https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12/tiles/{z}/{x}/{y}@2x?access_token=${MAPBOX_TOKEN}`,
    attribution: "&copy; Mapbox &copy; OpenStreetMap",
    maxNativeZoom: 22,
  };
}

// Basemap preference order. The first available layer becomes the checked
// default in the layer switcher (Mapbox needs a token to exist; everything
// else is always available, so in practice: Mapbox if configured, otherwise
// Google satellite).
const BASEMAP_ORDER = [
  TILES.mapbox_satellite && {
    name: "Satellite (Mapbox)", slug: "mapbox", tile: TILES.mapbox_satellite,
  },
  { name: "Satellite (Google)", slug: "google-satellite", tile: TILES.google_satellite },
  { name: "Hybrid (Google)", slug: "google-hybrid", tile: TILES.google_hybrid },
  { name: "Satellite (Esri)", slug: "esri", tile: TILES.satellite },
  { name: "Street", slug: "osm-carto", tile: TILES.street },
]
  .filter(Boolean)
  .map((bm, i) => ({ ...bm, isDefault: i === 0 }));
const DEFAULT_BASEMAP_SLUG = BASEMAP_ORDER[0].slug;

// Project a local (x, z) point in metres to WGS84 lat/lon given an origin and
// an azimuth rotation. Mirrors positioning-engine/app/services/geo.py exactly
// so what you place here is what the engine returns.
export function localToGps(x, z, origin) {
  if (!origin) return { lat: 0, lng: 0 };
  const az = ((origin.azimuth_deg || 0) * Math.PI) / 180;
  const c = Math.cos(az);
  const s = Math.sin(az);
  const east = x * c + z * s;
  const north = -x * s + z * c;
  const lat = origin.latitude + north / M_PER_DEG;
  const lng =
    origin.longitude + east / (M_PER_DEG * Math.cos((origin.latitude * Math.PI) / 180));
  return { lat, lng };
}

function FitOnFirstLoad({ origin }) {
  const map = useMap();
  const once = useRef(false);
  useEffect(() => {
    if (once.current) return;
    if (!origin || origin.latitude == null || origin.longitude == null) return;
    // Always land at zoom 19 - building-with-context view. fitBounds on a
    // small footprint (13×32 m) pushes Leaflet to z21+, which is the
    // street-tile-too-deep range. Operators want a stable landing zoom they
    // can recognise; they zoom in themselves once oriented.
    map.setView([origin.latitude, origin.longitude], 19);
    once.current = true;
  }, [origin, map]);
  return null;
}

// Auto fly to a new centre when the user searches for an address.
function FlyTo({ target }) {
  const map = useMap();
  useEffect(() => {
    if (target) map.flyTo([target.lat, target.lng], target.zoom || 19, { duration: 0.8 });
  }, [target, map]);
  return null;
}

// Hands the Leaflet map instance up to the parent so non-map UI (e.g. file
// upload) can read the current centre.
function MapHandle({ onReady }) {
  const map = useMap();
  useEffect(() => {
    onReady(map);
    return () => onReady(null);
  }, [map, onReady]);
  return null;
}

// N-point calibration picker. The operator builds correspondence PAIRS by
// alternating clicks: one landmark on the floor-plan image (yellow), then
// where that same landmark sits on the basemap (green). From two pairs the
// parent fits a 4-DOF similarity transform; every additional pair turns the
// fit into a least-squares problem and produces measurable residuals - two
// points always fit exactly, the third is what tells you how good your
// alignment actually is. Esc cancels; Ctrl/Cmd+Z drops the last click.
function CalibratePicker({
  active,
  calibrate,
  setCalibrate,
  computeFit,
  isOnImage,
  onReject,
}) {
  const [cursor, setCursor] = useState(null);
  useMapEvents({
    click: (e) => {
      if (!active) return;
      L.DomEvent.stopPropagation(e.originalEvent);
      const ll = { lat: e.latlng.lat, lng: e.latlng.lng };
      const c = calibrate || { stage: "img", pairs: [], pendingImg: null, proposed: null };
      if (c.stage === "img") {
        // Image picks are CONSTRAINED to the floor plan - clicking outside
        // would give a meaningless image-local coordinate.
        if (!isOnImage(ll)) {
          onReject?.("click must land on the floor-plan image");
          return;
        }
        setCalibrate({ ...c, pendingImg: ll, stage: "world" });
      } else if (c.stage === "world") {
        const pairs = [...c.pairs, { img: c.pendingImg, world: ll }];
        const proposed = pairs.length >= 2 ? computeFit(pairs) : null;
        setCalibrate({ ...c, pairs, pendingImg: null, stage: "img", proposed });
      }
    },
    mousemove: (e) => {
      if (!active) return;
      setCursor({ lat: e.latlng.lat, lng: e.latlng.lng });
    },
  });
  useEffect(() => {
    if (!active) setCursor(null);
  }, [active]);
  if (!active || !calibrate) return null;
  const { stage, pairs, pendingImg } = calibrate;
  // Live dashed line from the pending image point to the cursor while the
  // operator hunts for the matching world position.
  const liveLine = stage === "world" && pendingImg && cursor ? [pendingImg, cursor] : null;
  return (
    <>
      {pairs.map((p, i) => (
        <Fragment key={`cal-pair-${i}`}>
          <CircleMarker
            center={[p.img.lat, p.img.lng]}
            radius={6}
            pathOptions={{ color: "#0c1428", fillColor: "#fbbf24", fillOpacity: 1, weight: 2 }}
            interactive={false}
          >
            <Tooltip permanent direction="top" offset={[0, -8]}>
              <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 10 }}>{i + 1}</span>
            </Tooltip>
          </CircleMarker>
          <CircleMarker
            center={[p.world.lat, p.world.lng]}
            radius={6}
            pathOptions={{ color: "#0c1428", fillColor: "#5dffb0", fillOpacity: 1, weight: 2 }}
            interactive={false}
          >
            <Tooltip permanent direction="top" offset={[0, -8]}>
              <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 10 }}>{i + 1}</span>
            </Tooltip>
          </CircleMarker>
          <Polyline
            positions={[[p.img.lat, p.img.lng], [p.world.lat, p.world.lng]]}
            pathOptions={{ color: "#9ec3ff", weight: 1.5, dashArray: "4 5", opacity: 0.7 }}
            interactive={false}
          />
        </Fragment>
      ))}
      {pendingImg && (
        <CircleMarker
          center={[pendingImg.lat, pendingImg.lng]}
          radius={6}
          pathOptions={{ color: "#0c1428", fillColor: "#fbbf24", fillOpacity: 1, weight: 2 }}
          interactive={false}
        >
          <Tooltip permanent direction="top" offset={[0, -8]}>
            <span style={{ fontFamily: "ui-monospace, monospace", fontSize: 10 }}>{pairs.length + 1}</span>
          </Tooltip>
        </CircleMarker>
      )}
      {liveLine && (
        <Polyline
          positions={liveLine.map((p) => [p.lat, p.lng])}
          pathOptions={{ color: "#5dffb0", weight: 2, dashArray: "8 6", opacity: 0.7 }}
          interactive={false}
        />
      )}
    </>
  );
}

// Diagnostic reference-point picker. While active, every click on the map
// adds a labelled marker at that lat/lng so the operator can compare against
// vendor portal coordinates. Independent of editing mode - works in any
// section 1 state. The list of points + copy/delete affordances lives in a
// floating panel rendered by the parent.
function RefPointPicker({ active, onAdd }) {
  useMapEvents({
    click: (e) => {
      if (!active) return;
      L.DomEvent.stopPropagation(e.originalEvent);
      onAdd({ lat: e.latlng.lat, lng: e.latlng.lng });
    },
  });
  return null;
}

// Rotated image overlay. Leaflet's stock `ImageOverlay` accepts an
// axis-aligned bounding box and stretches the image to fit, so rotating the
// floor plan would warp the picture instead of rotating it. We DOM-overlay
// an <img> in the map's overlayPane and drive it with a 2D affine
// transform built from the rotated TL / TR / BL corners in layer-point
// coords. The image keeps its native aspect ratio and rotates rigidly.
function RotatedImageOverlay({ url, opacity, corners, naturalSize }) {
  const map = useMap();
  const ref = useRef(null);

  useEffect(() => {
    if (!map) return;
    const pane = map.getPanes().overlayPane;
    const div = L.DomUtil.create("div", "rotated-image-overlay", pane);
    div.style.position = "absolute";
    div.style.left = "0";
    div.style.top = "0";
    div.style.pointerEvents = "none";
    const img = document.createElement("img");
    img.style.position = "absolute";
    img.style.left = "0";
    img.style.top = "0";
    img.style.transformOrigin = "0 0";
    img.style.pointerEvents = "none";
    img.style.willChange = "transform";
    img.draggable = false;
    // Opt the <img> into Leaflet's zoom-animation CSS transition. The class
    // `leaflet-zoom-animated` is inert during pan/move but activates a
    // `transition: transform 0.25s cubic-bezier(0,0,0.25,1)` rule whenever the
    // map pane carries `leaflet-zoom-anim` - i.e. only during zoom. That's the
    // exact same hook Leaflet's stock ImageOverlay/TileLayer rely on, so our
    // matrix transform interpolates smoothly to the new corners instead of
    // snapping at the start of the animation.
    img.classList.add("leaflet-zoom-animated");
    div.appendChild(img);
    ref.current = { div, img };
    return () => {
      L.DomUtil.remove(div);
      ref.current = null;
    };
  }, [map]);

  useEffect(() => {
    if (!ref.current) return;
    ref.current.img.src = url;
    ref.current.img.style.opacity = opacity;
  }, [url, opacity]);

  useEffect(() => {
    if (!map || !ref.current || !naturalSize?.w || !naturalSize?.h) return;
    const W = naturalSize.w;
    const H = naturalSize.h;
    const buildMatrix = (tl, tr, bl) => {
      const a = (tr.x - tl.x) / W;
      const b = (tr.y - tl.y) / W;
      const c = (bl.x - tl.x) / H;
      const d = (bl.y - tl.y) / H;
      const e = tl.x;
      const f = tl.y;
      return `matrix(${a}, ${b}, ${c}, ${d}, ${e}, ${f})`;
    };
    const update = () => {
      const img = ref.current?.img;
      if (!img) return;
      const tl = map.latLngToLayerPoint([corners.TL.lat, corners.TL.lng]);
      const tr = map.latLngToLayerPoint([corners.TR.lat, corners.TR.lng]);
      const bl = map.latLngToLayerPoint([corners.BL.lat, corners.BL.lng]);
      img.style.width = W + "px";
      img.style.height = H + "px";
      img.style.transform = buildMatrix(tl, tr, bl);
    };
    // Smooth zoom: project corner lat/lngs into the layer-point coordinate
    // system at the ANIMATION TARGET zoom/centre. Leaflet handles the
    // intermediate frames via its overlay-pane CSS transform; we just need
    // to drop the image at where it will be when the zoom settles.
    const onZoomAnim = (e) => {
      const img = ref.current?.img;
      if (!img) return;
      const tl = map._latLngToNewLayerPoint(L.latLng(corners.TL.lat, corners.TL.lng), e.zoom, e.center);
      const tr = map._latLngToNewLayerPoint(L.latLng(corners.TR.lat, corners.TR.lng), e.zoom, e.center);
      const bl = map._latLngToNewLayerPoint(L.latLng(corners.BL.lat, corners.BL.lng), e.zoom, e.center);
      img.style.transform = buildMatrix(tl, tr, bl);
    };
    update();
    map.on("move", update);
    map.on("viewreset", update);
    map.on("zoomend", update);
    map.on("zoomanim", onZoomAnim);
    return () => {
      map.off("move", update);
      map.off("viewreset", update);
      map.off("zoomend", update);
      map.off("zoomanim", onZoomAnim);
    };
  }, [map, corners, naturalSize]);

  return null;
}

// Detects clicks on bare map background - used to deselect the area when the
// operator clicks somewhere outside the polygon / image. The `shouldIgnore`
// callback lets the parent veto a click in the brief window right after a
// drag completes (Leaflet sometimes treats mousedown-on-marker /
// mouseup-on-map as a map click and would otherwise deselect the area).
function MapClickCatcher({ onClick, shouldIgnore }) {
  useMapEvents({
    click: () => {
      if (shouldIgnore?.()) return;
      onClick?.();
    },
  });
  return null;
}

// Format an OSM Nominatim `address` object into two human-friendly lines:
//   line 1: place / city / town
//   line 2: region · country
// We deliberately skip street + house numbers - at the placement-editor scale
// the operator cares about *where in the world* the map is showing, not the
// exact doorstep address.
function shortPlace(addr) {
  if (!addr) return null;
  const place =
    addr.city ||
    addr.town ||
    addr.village ||
    addr.municipality ||
    addr.hamlet ||
    addr.suburb ||
    addr.neighbourhood ||
    addr.county;
  const region = addr.state || addr.region || addr.state_district;
  const country = addr.country;
  return {
    primary: place || null,
    secondary: [region, country].filter(Boolean).join(" · ") || null,
  };
}

// Live cursor + map-centre readout pinned to the bottom-left corner of the map.
// Includes a reverse-geocoded place name for the map centre so the operator
// can see what neighbourhood / street they are looking at without having to
// recognise tiles. Debounced + capped at 1 req / 1.2 s to respect Nominatim's
// fair-use policy.
function CoordsReadout() {
  const [cursor, setCursor] = useState(null);
  const [centre, setCentre] = useState(null);
  const [zoom, setZoom] = useState(null);
  const [place, setPlace] = useState(null);
  const [placeBusy, setPlaceBusy] = useState(false);
  const lastFetch = useRef(0);
  const debounceTimer = useRef(null);
  const inflight = useRef(null);

  const fetchPlace = (lat, lng) => {
    const now = Date.now();
    const sinceLast = now - lastFetch.current;
    const wait = Math.max(0, 1200 - sinceLast);
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(async () => {
      if (inflight.current) inflight.current.abort();
      const ctrl = new AbortController();
      inflight.current = ctrl;
      setPlaceBusy(true);
      try {
        const resp = await fetch(
          `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lng}&zoom=18&addressdetails=1`,
          { headers: { Accept: "application/json" }, signal: ctrl.signal }
        );
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        const short = shortPlace(data.address);
        setPlace(short || data.display_name || null);
        lastFetch.current = Date.now();
      } catch (err) {
        if (err.name !== "AbortError") setPlace(null);
      } finally {
        setPlaceBusy(false);
      }
    }, wait + 250);
  };

  const map = useMapEvents({
    mousemove: (e) => setCursor(e.latlng),
    mouseout: () => setCursor(null),
    moveend: () => {
      const c = map.getCenter();
      setCentre(c);
      setZoom(map.getZoom());
      fetchPlace(c.lat, c.lng);
    },
  });
  useEffect(() => {
    const c = map.getCenter();
    setCentre(c);
    setZoom(map.getZoom());
    fetchPlace(c.lat, c.lng);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
      if (inflight.current) inflight.current.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  const containerRef = useRef(null);
  useEffect(() => {
    // Leaflet would otherwise treat clicks/drag/scroll inside this overlay
    // as map events (panning the map). Block propagation so the user can
    // select/copy the coordinate text without the map moving underneath.
    if (containerRef.current) {
      L.DomEvent.disableClickPropagation(containerRef.current);
      L.DomEvent.disableScrollPropagation(containerRef.current);
    }
  }, []);

  const fmt = (ll) => `${ll.lat.toFixed(6)}, ${ll.lng.toFixed(6)}`;
  return (
    <div
      ref={containerRef}
      style={{
        position: "absolute",
        left: 8,
        bottom: 8,
        zIndex: 500,
        background: "rgba(8,14,32,0.85)",
        color: "#cce0ff",
        border: "1px solid rgba(58,130,255,0.4)",
        borderRadius: 6,
        padding: "6px 10px",
        fontSize: 11,
        fontFamily: "ui-monospace, monospace",
        lineHeight: 1.4,
        backdropFilter: "blur(4px)",
        maxWidth: 420,
        userSelect: "text",
        cursor: "text",
      }}
    >
      {placeBusy && !place && (
        <div style={{ color: "#7a8aab", fontStyle: "italic", fontSize: 11 }}>looking up…</div>
      )}
      {place && (
        <>
          <div style={{ color: "#cce0ff", fontWeight: 600, fontSize: 12 }}>
            {place.primary || "unknown area"}
          </div>
          {place.secondary && (
            <div style={{ color: "#9ec3ff", fontSize: 11 }}>{place.secondary}</div>
          )}
        </>
      )}
      {!place && !placeBusy && (
        <div style={{ color: "#7a8aab" }}>unknown area</div>
      )}
      <div style={{ marginTop: 4 }}>
        <span style={{ color: "#7a8aab" }}>cursor</span>{" "}
        {cursor ? fmt(cursor) : "-"}
      </div>
      <div>
        <span style={{ color: "#7a8aab" }}>centre</span>{" "}
        {centre ? `${fmt(centre)} · z${zoom}` : "-"}
      </div>
    </div>
  );
}

// Button that asks the browser for the user's geolocation and flies the map
// to that point. The map *displays* the location but does NOT touch the
// gps_origin - the operator still drags the floor-plan polygon explicitly.
function MyLocationButton({ onPick }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const onClick = () => {
    if (!navigator.geolocation) {
      setError("not supported");
      return;
    }
    setBusy(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setBusy(false);
        onPick({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy_m: pos.coords.accuracy,
          zoom: 18,
        });
      },
      (err) => {
        setBusy(false);
        setError(err.message || "denied");
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 }
    );
  };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      title="Fly the map to my current location (the floor-plan origin is not changed)"
      style={{
        padding: "5px 10px",
        background: "transparent",
        color: "#9ec3ff",
        border: "1px solid rgba(58,130,255,0.4)",
        borderRadius: 4,
        fontSize: 11,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        fontFamily: "ui-monospace, monospace",
        cursor: busy ? "wait" : "pointer",
        opacity: busy ? 0.5 : 1,
      }}
    >
      {busy ? "…" : "📍 me"}
      {error && (
        <span style={{ color: "#ff6b78", marginLeft: 6 }}>· {error}</span>
      )}
    </button>
  );
}

// Open the OSM building-snap PREVIEW. The actual apply happens via the
// floating panel inside the map, after the operator has reviewed which
// building / orientation Overpass returned. Two-stage flow because:
//   1. OSM building polygons can be ambiguous (multiple candidates near the
//      map centre - small sheds vs main hall).
//   2. The oriented-bbox of a complex footprint (T / L / H shapes) sometimes
//      aligns to a sub-feature rather than the visually-dominant axis. The
//      operator has to be able to see what we're proposing before it lands.
function SnapToBuildingButton({ getCentre, onOpenPreview, isPreviewOpen }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  useEffect(() => {
    if (!err) return;
    const t = setTimeout(() => setErr(null), 4000);
    return () => clearTimeout(t);
  }, [err]);
  const onClick = async () => {
    const centre = getCentre?.();
    if (!centre) {
      setErr("map not ready");
      return;
    }
    setBusy(true);
    setErr(null);
    const result = await fetchBuildingCandidates(centre.lat, centre.lng, 80, 5);
    setBusy(false);
    if (result.error) {
      setErr(result.error);
      return;
    }
    onOpenPreview(result);
  };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy || isPreviewOpen}
      title="Search OSM for buildings near the map centre. Opens a preview overlay so you can see which polygon matched and accept or cancel before anything is applied to the floor plan."
      style={{
        padding: "5px 10px",
        background: "transparent",
        color: err ? "#ff6b78" : "#9ec3ff",
        border: `1px solid ${err ? "#ff6b7888" : "rgba(58,130,255,0.4)"}`,
        borderRadius: 4,
        fontSize: 11,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        fontFamily: "ui-monospace, monospace",
        cursor: busy ? "wait" : "pointer",
        opacity: busy || isPreviewOpen ? 0.5 : 1,
        maxWidth: 280,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
      }}
    >
      {busy ? "searching…" : err ? err : "✦ snap to building"}
    </button>
  );
}

const techColors = {
  wifi: "#ffb347",
  wittra: "#5dffb0",
  fiveg: "#c084fc",
  gnss: "#fbbf24",
};

// Live autocomplete: as the operator types, fetch up to 5 Nominatim
// suggestions and render them in a dropdown. Submitting the form (or hitting
// Enter without choosing a row) picks the top hit. Click / arrow + Enter
// picks a specific one. Empty input clears the dropdown.
function AddressSearch({ onPick }) {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [highlight, setHighlight] = useState(-1);
  const debounceTimer = useRef(null);
  const inflight = useRef(null);
  const lastFetch = useRef(0);

  const fetchSuggestions = (q) => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    if (!q.trim() || q.trim().length < 3) {
      setSuggestions([]);
      setError(null);
      return;
    }
    // Throttle to ~1 req / 1.2 s to respect Nominatim's fair-use policy.
    const wait = Math.max(0, 1200 - (Date.now() - lastFetch.current));
    debounceTimer.current = setTimeout(async () => {
      if (inflight.current) inflight.current.abort();
      const ctrl = new AbortController();
      inflight.current = ctrl;
      setBusy(true);
      setError(null);
      try {
        const resp = await fetch(
          `https://nominatim.openstreetmap.org/search?format=json&limit=5&addressdetails=1&q=${encodeURIComponent(q)}`,
          { headers: { Accept: "application/json" }, signal: ctrl.signal }
        );
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const arr = await resp.json();
        setSuggestions(arr);
        setOpen(true);
        setHighlight(arr.length ? 0 : -1);
        if (!arr.length) setError("no match");
        lastFetch.current = Date.now();
      } catch (err) {
        if (err.name !== "AbortError") setError(err.message);
      } finally {
        setBusy(false);
      }
    }, wait + 300);
  };

  const pick = (hit) => {
    if (!hit) return;
    setQuery(hit.display_name);
    setSuggestions([]);
    setOpen(false);
    setHighlight(-1);
    onPick({
      lat: Number(hit.lat),
      lng: Number(hit.lon),
      zoom: 18,
      label: hit.display_name,
    });
  };

  const onSubmit = (e) => {
    e.preventDefault();
    if (suggestions.length) {
      pick(suggestions[Math.max(0, highlight)]);
    } else if (query.trim()) {
      // No suggestions cached yet: kick a fetch and pick the top hit when
      // it lands. Simpler than re-implementing the network path here.
      fetchSuggestions(query);
    }
  };

  const onKeyDown = (e) => {
    if (!open || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(suggestions.length - 1, h + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(0, h - 1));
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const shortLabel = (hit) => {
    const a = hit.address || {};
    const name =
      a.city || a.town || a.village || a.municipality || a.hamlet ||
      a.suburb || a.neighbourhood || hit.name;
    const region = a.state || a.region;
    const country = a.country;
    const parts = [name, region, country].filter(Boolean);
    return parts.join(" · ") || hit.display_name;
  };

  return (
    <div style={{ position: "relative" }}>
      <form onSubmit={onSubmit} style={{ display: "flex", gap: 6 }}>
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            fetchSuggestions(e.target.value);
          }}
          onKeyDown={onKeyDown}
          onFocus={() => suggestions.length && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Address or place (e.g. Politecnico di Torino)"
          style={{
            flex: 1,
            background: "rgba(255,255,255,0.06)",
            border: `1px solid ${busy ? "rgba(58,130,255,0.5)" : "rgba(255,255,255,0.12)"}`,
            color: "#e6edf7",
            padding: "5px 10px",
            borderRadius: 4,
            fontSize: 12,
            fontFamily: "ui-monospace, monospace",
          }}
        />
        <button
          type="submit"
          disabled={busy || !query.trim()}
          style={{
            padding: "5px 12px",
            background: "rgba(58,130,255,0.2)",
            color: "#9ec3ff",
            border: "1px solid rgba(58,130,255,0.5)",
            borderRadius: 4,
            fontSize: 11,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            fontFamily: "ui-monospace, monospace",
            cursor: busy ? "wait" : "pointer",
            opacity: busy || !query.trim() ? 0.5 : 1,
          }}
        >
          {busy ? "…" : "find"}
        </button>
      </form>
      {error && !open && (
        <span
          style={{
            position: "absolute",
            right: 60,
            top: 7,
            fontSize: 11,
            color: "#ff6b78",
            fontFamily: "ui-monospace, monospace",
            pointerEvents: "none",
          }}
        >
          {error}
        </span>
      )}
      {open && suggestions.length > 0 && (
        <ul
          style={{
            position: "absolute",
            left: 0,
            right: 60,
            top: "calc(100% + 4px)",
            // Leaflet zoom controls live at z-index 1000; sit above them so
            // the +/- buttons don't bleed through the dropdown.
            zIndex: 1200,
            margin: 0,
            padding: 4,
            listStyle: "none",
            background: "#0c1428",
            boxShadow: "0 8px 20px rgba(0,0,0,0.6)",
            border: "1px solid rgba(58,130,255,0.4)",
            borderRadius: 6,
            maxHeight: 220,
            overflowY: "auto",
            fontFamily: "ui-monospace, monospace",
            fontSize: 12,
          }}
        >
          {suggestions.map((hit, i) => (
            <li
              key={hit.place_id}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(hit);
              }}
              onMouseEnter={() => setHighlight(i)}
              style={{
                padding: "6px 10px",
                borderRadius: 4,
                cursor: "pointer",
                background: i === highlight ? "rgba(58,130,255,0.2)" : "transparent",
                color: i === highlight ? "#cce0ff" : "#e6edf7",
              }}
            >
              <div style={{ fontWeight: 600 }}>{shortLabel(hit)}</div>
              <div style={{ fontSize: 10, color: "#7a8aab", marginTop: 2 }}>
                {hit.display_name}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function FloorPlanImageInput({ value, onChange, onOpacityDragStart, onOpacityDragEnd }) {
  const inputRef = useRef(null);
  const onFile = (file) => {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      toast("Image too large (>2 MB). Resize before uploading.", "error");
      return;
    }
    const reader = new FileReader();
    reader.onload = (e) =>
      onChange({ data_url: e.target.result, opacity: 0.7, filename: file.name });
    reader.readAsDataURL(file);
  };
  const filename = value?.filename;
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "0 8px 6px",
      }}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          title="Upload an architectural reference image for this area (PNG / JPG, ≤2 MB). Visual only - anchor placement happens in later steps."
          style={{
            padding: "4px 10px",
            background: "transparent",
            color: "#9ec3ff",
            border: "1px solid rgba(58,130,255,0.4)",
            borderRadius: 4,
            fontSize: 11,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            fontFamily: "ui-monospace, monospace",
            cursor: "pointer",
          }}
        >
          {filename ? "replace reference" : "+ reference image"}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          onChange={(e) => {
            onFile(e.target.files?.[0]);
            // Reset so re-uploading the same file fires `onChange` again.
            e.target.value = "";
          }}
          style={{ display: "none" }}
        />
        {filename && (
          <span
            style={{
              fontSize: 11,
              color: "#cce0ff",
              fontFamily: "ui-monospace, monospace",
              flex: 1,
              minWidth: 0,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={filename}
          >
            📎 {filename}
          </span>
        )}
        {value?.data_url && (
          <button
            type="button"
            onClick={() => onChange(null)}
            style={{
              padding: "2px 6px",
              background: "transparent",
              color: "#ff6b78",
              border: "1px solid #ff6b7855",
              borderRadius: 3,
              fontSize: 10,
              cursor: "pointer",
              fontFamily: "ui-monospace, monospace",
            }}
            title="Remove the floor-plan image"
          >
            ✕ remove
          </button>
        )}
      </div>
      {value?.data_url && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "60px 1fr 36px",
            alignItems: "center",
            gap: 8,
            padding: "4px 2px 0",
            borderTop: "1px solid rgba(255,255,255,0.04)",
          }}
        >
          <label
            style={{
              fontSize: 10,
              color: "#7a8aab",
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              fontFamily: "ui-monospace, monospace",
            }}
          >
            opacity
          </label>
          <input
            type="range"
            min="0.1"
            max="1"
            step="0.05"
            value={value.opacity ?? 0.7}
            onChange={(e) => onChange({ ...value, opacity: Number(e.target.value) })}
            onPointerDown={() => onOpacityDragStart?.()}
            onPointerUp={() => onOpacityDragEnd?.()}
            onPointerCancel={() => onOpacityDragEnd?.()}
            style={{ width: "100%" }}
          />
          <span
            style={{
              fontSize: 10,
              color: "#cce0ff",
              fontFamily: "ui-monospace, monospace",
              textAlign: "right",
            }}
          >
            {Math.round((value.opacity ?? 0.7) * 100)}%
          </span>
        </div>
      )}
    </div>
  );
}

// Snap helper for area edits - 0.5 m grid when enabled, free otherwise.
const AREA_SNAP_M = 0.5;
const snapM = (v, step = AREA_SNAP_M) => (step > 0 ? Math.round(v / step) * step : v);
const rad = (deg) => (deg * Math.PI) / 180;

// Pointer drag with a small dead-zone so a click (or a brushed-past handle
// during a map pan) does NOT begin a drag. The first onMove fires only once
// the pointer has travelled `threshold` pixels from the mousedown point. We
// also stop event propagation so the map's own drag handler doesn't pick up
// the same gesture and pan the world underneath.
const DRAG_THRESHOLD_PX = 8;
function startHandleDrag(e, onMove, { onStart, onEnd } = {}) {
  e.originalEvent.preventDefault();
  L.DomEvent.stopPropagation(e.originalEvent);
  const map = e.target._map;
  map.dragging.disable();
  const start = { x: e.originalEvent.clientX, y: e.originalEvent.clientY };
  let active = false;
  const move = (ev) => {
    if (!active) {
      const dx = ev.clientX - start.x;
      const dy = ev.clientY - start.y;
      if (dx * dx + dy * dy < DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX) return;
      active = true;
      onStart?.();
    }
    onMove(ev, map);
  };
  const up = () => {
    map.dragging.enable();
    window.removeEventListener("mousemove", move);
    window.removeEventListener("mouseup", up);
    if (active) onEnd?.();
  };
  window.addEventListener("mousemove", move);
  window.addEventListener("mouseup", up);
}

export const GeorefMap = forwardRef(function GeorefMap({
  floorPlan,
  anchors = [],
  onOriginChange,
  onFloorPlanImageChange,
  onDrawRectangle,
  onSelect,
  onEditCommit,
  // Called once when a handle-drag actually begins (i.e. past the dead-zone)
  // and again on release. Parent uses these to bracket the whole drag with
  // a single transient history step instead of one commit per pointer-move.
  onTransientStart,
  onTransientEnd,
  snapEnabled = true,
  showGrid = false,
}, ref) {
  const georef = floorPlan?.georef || {};
  const hasArea = Boolean(
    georef.latitude && georef.longitude &&
    Number(georef.width_m) > 0 && Number(georef.height_m) > 0
  );
  const origin = {
    latitude: georef.latitude || 45.064312,
    longitude: georef.longitude || 7.659154,
    azimuth_deg: georef.azimuth_deg || 0,
  };
  const room_w = Number(georef.width_m) || 10;
  const room_h = Number(georef.height_m) || 10;
  const floorImage = floorPlan?.image;
  const [flyTarget, setFlyTarget] = useState(null);
  // Two-stage activation, area-anchored (not toolbar-driven):
  //   1. click area → `selected` = true → contextual ✎ pencil appears on it
  //   2. click ✎ → `editing` = true → handles appear
  //   3. click ✓ done → leaves edit, area stays selected
  //   4. click anywhere outside the area → deselect + leave edit
  // Default state on load: not selected, not editing - area is read-only,
  // map pans/zooms freely without any handle to grab by accident.
  const [selected, _setSelected] = useState(false);
  const setSelected = (v) => {
    _setSelected(v);
    onSelect?.(v);
  };
  const [editing, _setEditing] = useState(false);
  const setEditing = (v) => {
    _setEditing(v);
    if (!v) {
      // Leaving edit mode also closes any active sub-tools.
      setCalibrate(null);
      onEditCommit?.();
    }
  };
  // OSM-snap preview. When non-null, the operator has triggered `+ snap to
  // building`; we draw the matched polygon + OMBB rectangle on the map and
  // surface a confirm/cancel panel. Nothing touches `floor_plans` until the
  // operator hits Apply, so a wrong match is a single click to cancel.
  //   shape: { candidates: [...], selectedIdx: int, rotate90: bool }
  const [snapPreview, setSnapPreview] = useState(null);
  // Two-point calibration tool. The operator picks two landmarks visible in
  // the floor-plan image, then picks where the same two landmarks sit on
  // the satellite - we solve for rotation + uniform scale + translation in
  // closed form. Replaces the old align-to-edge tool, which only did
  // rotation (and required the operator to remember which click order avoided
  // a 180° flip). With two correspondences you can recover the full 4-DOF
  // similarity transform - much more useful when the image's initial scale
  // was wrong.
  //   shape: { stage: 1|2|3|4|"preview",
  //            imgA, imgB,           // lat/lng of clicks on the image
  //            worldA, worldB,       // lat/lng of where those points belong
  //            proposed              // resolved georef patch + dims preview
  //          } | null
  const [calibrate, setCalibrate] = useState(null);
  // Transient "your click was rejected" message - shown in the status pill
  // when stages 1-2 receive a click outside the image. Auto-clears after a
  // short window.
  const [calibrateReject, setCalibrateReject] = useState(null);

  // Which basemap the operator is currently looking at. Stamped into the
  // georef as `calibrated_against` on calibration apply, because the
  // resulting alignment is only as absolute as that provider's image
  // registration. Leaflet emits `baselayerchange` with the display name.
  const [baseLayerSlug, setBaseLayerSlug] = useState(DEFAULT_BASEMAP_SLUG);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const onBase = (e) => {
      const bm = BASEMAP_ORDER.find((b) => b.name === e.name);
      setBaseLayerSlug(bm?.slug || e.name);
    };
    map.on("baselayerchange", onBase);
    return () => map.off("baselayerchange", onBase);
  });

  // Reference-point diagnostic tool. While `refPickMode` is true, clicks on
  // the map drop a labelled marker at that lat/lng. Used to cross-check our
  // georef against a vendor portal: pick the spot on our map, read the
  // coords, compare with the same physical point in the vendor UI.
  const [refPickMode, setRefPickMode] = useState(false);
  const [refPoints, setRefPoints] = useState([]);
  const refIdCounter = useRef(0);
  const addRefPoint = (pt) => {
    refIdCounter.current += 1;
    setRefPoints((arr) => [...arr, { id: refIdCounter.current, ...pt }]);
  };
  const removeRefPoint = (id) => {
    setRefPoints((arr) => arr.filter((p) => p.id !== id));
  };

  // Project an OMBB georef to the floor-plan georef we'd commit. The OMBB is
  // 90°-ambiguous on near-square footprints (and on T/L shapes it sometimes
  // picks the secondary axis), so the preview panel exposes a "↻ 90°" toggle
  // that swaps width/height and adjusts azimuth + BL accordingly. When an
  // image is loaded, we preserve the image's pixel aspect ratio and only
  // re-centre + re-orient instead of overwriting width/height.
  const projectSnapResult = (raw, rotate90) => {
    let { latitude, longitude, azimuth_deg, width_m, height_m } = raw;
    if (rotate90) {
      // The OMBB rectangle has 4-fold rotational symmetry. Rotating its local
      // frame by 90° CCW means: old +y becomes new +x. New width = old height,
      // new height = old width. The OLD top-left corner (which was at local
      // (0, old_h) in the OLD frame) becomes the NEW bottom-left corner.
      const azRad = (azimuth_deg * Math.PI) / 180;
      const cosA = Math.cos(azRad);
      const sinA = Math.sin(azRad);
      // Old TL → world east/north offset from old BL.
      const eOff = 0 * cosA + height_m * sinA; // == h*sinA
      const nOff = -0 * sinA + height_m * cosA; // == h*cosA
      const newBlLat = latitude + nOff / M_PER_DEG;
      const newBlLng = longitude + eOff / (M_PER_DEG * Math.cos((latitude * Math.PI) / 180));
      latitude = newBlLat;
      longitude = newBlLng;
      [width_m, height_m] = [height_m, width_m];
      azimuth_deg += 90;
      // Normalise to (-180, 180].
      while (azimuth_deg > 180) azimuth_deg -= 360;
      while (azimuth_deg <= -180) azimuth_deg += 360;
    }
    return { latitude, longitude, azimuth_deg, width_m, height_m };
  };

  // Compute the actual georef patch that would be committed for the current
  // preview state. Modes:
  //   "full"        → lat/lng + azimuth + (width/height if no image)
  //   "orientation" → azimuth only. Useful when the operator has already
  //                   placed the area against satellite imagery (which is the
  //                   visual source of truth) and only wants OSM's rotation -
  //                   OSM polygons routinely drift 5–20 m from ESRI tiles.
  const previewGeorefPatch = (cand, rotate90, mode = "full") => {
    if (!cand) return null;
    const g = projectSnapResult(cand.georef, rotate90);
    if (mode === "orientation") {
      return { azimuth_deg: g.azimuth_deg };
    }
    // No image OR no area defined yet → adopt the OMBB's dims directly.
    if (!floorImage?.data_url || room_w <= 0 || room_h <= 0) {
      return {
        latitude: g.latitude,
        longitude: g.longitude,
        azimuth_deg: g.azimuth_deg,
        width_m: g.width_m,
        height_m: g.height_m,
      };
    }
    // Image present: keep image dims, re-anchor BL so the area's centre
    // matches the building's OMBB centre.
    const azRad = (g.azimuth_deg * Math.PI) / 180;
    const cosA = Math.cos(azRad);
    const sinA = Math.sin(azRad);
    const eMidB = (g.width_m / 2) * cosA + (g.height_m / 2) * sinA;
    const nMidB = -(g.width_m / 2) * sinA + (g.height_m / 2) * cosA;
    const ctrLat = g.latitude + nMidB / M_PER_DEG;
    const ctrLng = g.longitude + eMidB / (M_PER_DEG * Math.cos((g.latitude * Math.PI) / 180));
    const eMidI = (room_w / 2) * cosA + (room_h / 2) * sinA;
    const nMidI = -(room_w / 2) * sinA + (room_h / 2) * cosA;
    const newLat = ctrLat - nMidI / M_PER_DEG;
    const newLng = ctrLng - eMidI / (M_PER_DEG * Math.cos((ctrLat * Math.PI) / 180));
    return {
      latitude: newLat,
      longitude: newLng,
      azimuth_deg: g.azimuth_deg,
    };
  };

  const applySnapPreview = () => {
    if (!snapPreview) return;
    const cand = snapPreview.candidates[snapPreview.selectedIdx];
    const patch = previewGeorefPatch(cand, snapPreview.rotate90, snapPreview.mode || "full");
    if (!patch) return;
    onOriginChange(patch);
    setSnapPreview(null);
  };

  // Invert the CURRENT floor-plan transform on a click lat/lng to get the
  // image-local position (in metres, where the rectangle is 0..width × 0..height).
  // The same image pixel is at the same NORMALISED position regardless of the
  // floor plan's scale, so once we know the local coords we can keep that
  // pixel anchored under the click point even after rotation + rescaling.
  const worldToImageLocal = (latLng) => {
    if (!hasArea) return null;
    const cosLat = Math.cos((origin.latitude * Math.PI) / 180);
    const dE = (latLng.lng - origin.longitude) * M_PER_DEG * cosLat;
    const dN = (latLng.lat - origin.latitude) * M_PER_DEG;
    const azRad = (origin.azimuth_deg * Math.PI) / 180;
    const cosA = Math.cos(azRad);
    const sinA = Math.sin(azRad);
    // [x_loc, y_loc] = R(az)^T [dE, dN]
    const x = dE * cosA - dN * sinA;
    const y = dE * sinA + dN * cosA;
    return { x, y };
  };

  // Fit a 4-DOF similarity transform (uniform scale, rotation, translation)
  // from N ≥ 2 correspondence pairs: image-local points p_i must land on the
  // basemap at world points q_i. Least-squares (2D Umeyama / Procrustes):
  //
  //   q_i = s · R(φ) · p_i + t      R = standard CCW rotation in (E, N)
  //
  //   φ = atan2( Σ p'×q' , Σ p'·q' )      (demeaned)
  //   s = |(Σ p'·q', Σ p'×q')| / Σ|p'|²
  //   t = q̄ − s·R·p̄
  //
  // Our azimuth convention (clockwise-from-north applied as
  // east = x·cosA + y·sinA) is R(−A), so azimuth = −φ. With exactly two
  // pairs the fit is exact (zero residuals) and reduces to the old
  // closed-form two-point solution; from three pairs the residuals measure
  // the real alignment error - clicks, image distortion, tile registration.
  const computeFit = (pairs) => {
    if (!pairs || pairs.length < 2) return null;
    const locals = pairs.map((pr) => worldToImageLocal(pr.img));
    if (locals.some((l) => !l)) return null;
    // World coords → metres east/north relative to the first world pick.
    const anchor = pairs[0].world;
    const cosLat = Math.cos((anchor.lat * Math.PI) / 180);
    const worlds = pairs.map((pr) => ({
      e: (pr.world.lng - anchor.lng) * M_PER_DEG * cosLat,
      n: (pr.world.lat - anchor.lat) * M_PER_DEG,
    }));
    const n = pairs.length;
    const pMean = {
      x: locals.reduce((s, p) => s + p.x, 0) / n,
      y: locals.reduce((s, p) => s + p.y, 0) / n,
    };
    const qMean = {
      e: worlds.reduce((s, q) => s + q.e, 0) / n,
      n: worlds.reduce((s, q) => s + q.n, 0) / n,
    };
    let a = 0, b = 0, normP = 0;
    for (let i = 0; i < n; i++) {
      const px = locals[i].x - pMean.x;
      const py = locals[i].y - pMean.y;
      const qe = worlds[i].e - qMean.e;
      const qn = worlds[i].n - qMean.n;
      a += px * qe + py * qn;
      b += px * qn - py * qe;
      normP += px * px + py * py;
    }
    if (normP < 0.01) return null; // image picks degenerate (coincident)
    const phi = Math.atan2(b, a);
    const s = Math.hypot(a, b) / normP;
    if (!(s > 0) || !isFinite(s)) return null;
    const cosP = Math.cos(phi);
    const sinP = Math.sin(phi);
    const tE = qMean.e - s * (cosP * pMean.x - sinP * pMean.y);
    const tN = qMean.n - s * (sinP * pMean.x + cosP * pMean.y);
    // Residual per pair, in metres on the basemap.
    const residuals = pairs.map((_, i) => {
      const fe = s * (cosP * locals[i].x - sinP * locals[i].y) + tE;
      const fn = s * (sinP * locals[i].x + cosP * locals[i].y) + tN;
      return Math.hypot(worlds[i].e - fe, worlds[i].n - fn);
    });
    const rms = Math.sqrt(residuals.reduce((acc, r) => acc + r * r, 0) / n);
    let azDeg = (-phi * 180) / Math.PI;
    while (azDeg > 180) azDeg -= 360;
    while (azDeg <= -180) azDeg += 360;
    // t is the world offset of the image-local origin (the BL corner).
    const newLat = anchor.lat + tN / M_PER_DEG;
    const newLng = anchor.lng + tE / (M_PER_DEG * cosLat);
    return {
      latitude: newLat,
      longitude: newLng,
      azimuth_deg: azDeg,
      width_m: s * room_w,
      height_m: s * room_h,
      scaleFactor: s,
      residuals,
      rms,
    };
  };

  const applyCalibration = () => {
    if (!calibrate?.proposed) return;
    const { latitude, longitude, azimuth_deg, width_m, height_m, rms } = calibrate.proposed;
    onOriginChange({
      latitude,
      longitude,
      azimuth_deg,
      width_m,
      height_m,
      // Provenance: which basemap the operator aligned against, how many
      // correspondence pairs, and the fit RMS. Absolute accuracy of the
      // georef is bounded by that provider's registration (1–5 m typical);
      // see docs/georeferencing.md for why this matters when comparing
      // against vendor-cloud coordinates.
      calibrated_against: baseLayerSlug,
      calibration_points: calibrate.pairs.length,
      calibration_rms_m: Number(rms.toFixed(3)),
    });
    setCalibrate(null);
  };

  // Swap the map container's cursor for a crosshair while calibration is
  // active. The default `leaflet-grab` cursor (a hand) is wrong for a
  // precision picking tool - the operator needs to see exactly which pixel
  // they're aiming at. Resets on cleanup so leaving the tool restores the
  // normal pan-grab cursor.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const c = map.getContainer();
    if (calibrate) {
      const prev = c.style.cursor;
      c.style.cursor = "crosshair";
      return () => { c.style.cursor = prev; };
    }
  }, [calibrate]);

  // Test whether a click falls inside the currently-rendered floor-plan
  // image (i.e. its image-local coords are within 0..width × 0..height).
  // Used to gate stages 1-2 of the calibration: those clicks must land on
  // the floor plan, otherwise the inferred image-local coordinate makes no
  // sense.
  const isPointOnFloorPlanImage = (latLng) => {
    const local = worldToImageLocal(latLng);
    if (!local) return false;
    return local.x >= 0 && local.x <= room_w && local.y >= 0 && local.y <= room_h;
  };

  // Step back one click of calibration, forgetting the most recently placed
  // point. Wired to the ↩ back button AND to Ctrl/Cmd+Z while the tool is
  // active. Layout-level undo is suppressed during calibration so the operator
  // can fix a misclick without affecting the rest of their history.
  const stepBackCalibrate = () => {
    setCalibrate((c) => {
      if (!c) return null;
      // Pending image pick → drop it.
      if (c.pendingImg) return { ...c, pendingImg: null, stage: "img" };
      // No pending, no pairs → exit the tool.
      if (!c.pairs || c.pairs.length === 0) return null;
      // Otherwise re-open the last pair: its world point is forgotten, its
      // image point becomes the pending pick again.
      const pairs = c.pairs.slice(0, -1);
      const last = c.pairs[c.pairs.length - 1];
      const proposed = pairs.length >= 2 ? computeFit(pairs) : null;
      return { ...c, pairs, pendingImg: last.img, stage: "world", proposed };
    });
  };
  // Live drag-tooltip content. Set by each handle's drag callback to a short
  // numeric readout (e.g. "13.5 × 32.0 m", "azimuth 12°", "45.06453, 7.65923")
  // so the operator can see the value snapping in real time without taking
  // their eyes off the map. Cleared on drag-end and on edit-exit.
  const [dragInfo, setDragInfo] = useState(null);
  const [imgNatural, setImgNatural] = useState(null);
  // Persisted "where am I" marker. Updated only when the user clicks the
  // 📍 me button; survives map pan/zoom so the operator keeps a reference
  // for their own position while dragging the floor-plan around.
  const [myLocation, setMyLocation] = useState(null);
  // Captured map instance - used by the upload + "draw rectangle" controls
  // to position the area at the current viewport.
  const mapRef = useRef(null);
  // Set to true for ~600 ms after a handle drag completes, so the spurious
  // "map click" Leaflet may emit on mouseup is ignored instead of
  // deselecting the area. Belt + braces: also install a one-shot capture
  // handler on `document` that stops the next click outright, since the
  // ref-based guard alone occasionally races against react-leaflet's
  // internal event registration order.
  const ignoreClickRef = useRef(false);
  const swallowNextClick = () => {
    ignoreClickRef.current = true;
    setTimeout(() => {
      ignoreClickRef.current = false;
    }, 600);
    const oneShot = (ev) => {
      ev.stopPropagation();
      ev.stopImmediatePropagation();
      document.removeEventListener("click", oneShot, true);
    };
    document.addEventListener("click", oneShot, true);
    // Guarantee removal even if no click ever fires.
    setTimeout(() => document.removeEventListener("click", oneShot, true), 700);
  };

  // Wrapper that auto-brackets every handle-drag with a single transient
  // history step. Caller's own onStart/onEnd (e.g. dragInfo readout, click
  // swallowing) still fires alongside. Used in place of `startHandleDrag`
  // for every drag interaction below - corner resize, edge resize, rotate,
  // image / polygon translate.
  const startHandleDragT = (e, onMove, opts = {}) => {
    startHandleDrag(e, onMove, {
      onStart: () => {
        onTransientStart?.();
        opts.onStart?.();
      },
      onEnd: () => {
        opts.onEnd?.();
        onTransientEnd?.();
      },
    });
  };

  // Load image natural dimensions whenever the data URL changes - needed
  // for the rotated DOM overlay's CSS matrix transform.
  useEffect(() => {
    if (!floorPlan?.image?.data_url) {
      setImgNatural(null);
      return;
    }
    const i = new Image();
    i.onload = () => setImgNatural({ w: i.naturalWidth, h: i.naturalHeight });
    i.onerror = () => setImgNatural(null);
    i.src = floorPlan.image.data_url;
  }, [floorPlan?.image?.data_url]);

  // Escape exits ref-pick mode first, independent of editing state.
  useEffect(() => {
    if (!refPickMode) return;
    const onKey = (ev) => {
      if (ev.key === "Escape") {
        setRefPickMode(false);
        ev.stopImmediatePropagation();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [refPickMode]);

  // Escape exits edit mode (parallels the Plan/Room sections where Esc
  // cancels the current draw). Selection itself is left alone - a single Esc
  // is "stop editing", a follow-up click outside the area deselects.
  useEffect(() => {
    if (!editing) return;
    const onKey = (ev) => {
      if (ev.key === "Escape") {
        // Esc cancels the calibrate sub-tool first (if active); otherwise
        // exits editing entirely.
        if (calibrate) {
          setCalibrate(null);
          ev.stopImmediatePropagation();
          return;
        }
        setEditing(false);
        setDragInfo(null);
        return;
      }
      // Ctrl/Cmd+Z while calibration is active: step back one click instead
      // of letting App.jsx's global handler pop the layout history. Capture
      // phase + stopImmediatePropagation ensures this runs before App's
      // listener so the underlying layout stays untouched.
      const metaZ =
        (ev.ctrlKey || ev.metaKey) &&
        ev.key.toLowerCase() === "z" &&
        !ev.shiftKey;
      if (metaZ && calibrate) {
        ev.preventDefault();
        ev.stopImmediatePropagation();
        stepBackCalibrate();
      }
    };
    window.addEventListener("keydown", onKey, true); // capture
    return () => window.removeEventListener("keydown", onKey, true);
  }, [editing, calibrate]);

  // Imperative API for the sidebar: the ▢ rectangle button lives outside the
  // map (next to width/height inputs), so the parent needs a way to ask the
  // map "draw a rectangle at your current centre".
  useImperativeHandle(
    ref,
    () => ({
      drawRectangle: () => {
        const map = mapRef.current;
        if (!map || !onDrawRectangle) return;
        const c = map.getCenter();
        onDrawRectangle({ lat: c.lat, lng: c.lng });
      },
      flyTo: (lat, lng, zoom = 19) => {
        setFlyTarget({ lat, lng, zoom });
      },
      getMapCentre: () => {
        const m = mapRef.current;
        if (!m) return null;
        const c = m.getCenter();
        return { lat: c.lat, lng: c.lng };
      },
    }),
    [onDrawRectangle]
  );

  const onUploadImage = (image) => {
    if (onFloorPlanImageChange) onFloorPlanImageChange(image);
    if (!image || !mapRef.current) return;
    // The image *is* the area. Its real-world footprint must follow the
    // image's pixel aspect ratio - squishing a rectangular floor plan into
    // a pre-existing 13×32 m box is exactly what we don't want.
    // Always overwrite width_m / height_m on upload so the image is laid out
    // at its native aspect (defaulting to 30 m on the longer side).
    const c = mapRef.current.getCenter();
    const img = new Image();
    img.onload = () => {
      const w = img.naturalWidth || 1;
      const h = img.naturalHeight || 1;
      const longSideM = 30;
      const widthM = w >= h ? longSideM : longSideM * (w / h);
      const heightM = h >= w ? longSideM : longSideM * (h / w);
      onOriginChange({
        latitude: c.lat,
        longitude: c.lng,
        width_m: Number(widthM.toFixed(2)),
        height_m: Number(heightM.toFixed(2)),
      });
    };
    img.onerror = () => {
      onOriginChange({ latitude: c.lat, longitude: c.lng, width_m: 30, height_m: 30 });
    };
    img.src = image.data_url;
  };

  const onPickFly = (target) => {
    setFlyTarget(target);
    if (target.accuracy_m != null) {
      setMyLocation({ lat: target.lat, lng: target.lng, accuracy_m: target.accuracy_m });
    }
  };

  const corners = useMemo(
    () => [
      localToGps(0, 0, origin),
      localToGps(room_w, 0, origin),
      localToGps(room_w, room_h, origin),
      localToGps(0, room_h, origin),
    ],
    [origin, room_w, room_h]
  );
  const centre = useMemo(
    () => localToGps(room_w / 2, room_h / 2, origin),
    [origin, room_w, room_h]
  );
  const azHandlePoint = useMemo(
    () => localToGps(room_w / 2, room_h * 1.1, origin),
    [origin, room_w, room_h]
  );

  // ImageOverlay accepts an axis-aligned bounds in lat/lng. To support a
  // rotated room we'd need a custom overlay; for now the image follows the
  // axis-aligned bounding box of the floor polygon and gets stretched when
  // azimuth != 0. Good enough as a placement aid (precise placement is done
  // in step 2 against the metric grid).
  const imageBounds = useMemo(() => {
    if (!floorImage?.data_url) return null;
    let minLat = Infinity, maxLat = -Infinity, minLng = Infinity, maxLng = -Infinity;
    for (const c of corners) {
      minLat = Math.min(minLat, c.lat);
      maxLat = Math.max(maxLat, c.lat);
      minLng = Math.min(minLng, c.lng);
      maxLng = Math.max(maxLng, c.lng);
    }
    return [[minLat, minLng], [maxLat, maxLng]];
  }, [floorImage, corners]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div
        style={{
          background: "rgba(10,18,40,0.6)",
          border: "1px solid rgba(255,255,255,0.06)",
          borderRadius: 8,
        }}
      >
        <div style={{ display: "flex", gap: 6, padding: "6px 8px 0", alignItems: "stretch", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 180 }}>
            <AddressSearch onPick={onPickFly} />
          </div>
          <MyLocationButton onPick={onPickFly} />
          <button
            type="button"
            onClick={() => setRefPickMode((m) => !m)}
            title="Drop reference markers on the map by clicking. Each marker shows its lat/lon so you can compare against a vendor portal or other map. Click again on the toolbar button to exit picking mode."
            style={{
              padding: "6px 10px",
              background: refPickMode ? "rgba(192,132,252,0.25)" : "rgba(10,18,40,0.6)",
              color: refPickMode ? "#dbc1ff" : "#cce0ff",
              border: `1px solid ${refPickMode ? "#c084fcaa" : "rgba(255,255,255,0.18)"}`,
              borderRadius: 6,
              fontSize: 11,
              fontFamily: "ui-monospace, monospace",
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            📍 ref point{refPoints.length > 0 ? ` · ${refPoints.length}` : ""}
          </button>
          {/* Snap-to-building is a cold-start aid only. Once the operator has
              placed an area (manually or otherwise), the satellite tile is
              the source of truth and OSM polygons add noise (registration
              drift, OMBB axis ambiguity). For fine rotation against an
              existing area, use the in-editor align-edge tool instead. */}
          {!hasArea && (
            <SnapToBuildingButton
              getCentre={() => {
                const c = mapRef.current?.getCenter();
                return c ? { lat: c.lat, lng: c.lng } : null;
              }}
              isPreviewOpen={Boolean(snapPreview)}
              onOpenPreview={(result) =>
                setSnapPreview({
                  candidates: result.candidates,
                  selectedIdx: 0,
                  rotate90: false,
                  mode: "full",
                })
              }
            />
          )}
        </div>
      </div>
      <div
        style={{
          height: "76vh",
          borderRadius: 10,
          overflow: "hidden",
          border: "1px solid rgba(58,130,255,0.2)",
          position: "relative",
        }}
      >
        {/* Editing-mode pill: floats top-right of the map, gives a clean exit
            affordance without cluttering the area with floating tooltips.
            ESC also exits (wired via document-level keydown). */}
        {editing && (
          <div
            style={{
              position: "absolute",
              top: 12,
              right: 56,
              zIndex: 600,
              display: "flex",
              alignItems: "center",
              gap: 6,
              background: "rgba(8,14,32,0.92)",
              border: "1px solid rgba(93,255,176,0.5)",
              borderRadius: 6,
              padding: "5px 10px",
              fontFamily: "ui-monospace, monospace",
              fontSize: 11,
              color: "#5dffb0",
              boxShadow: "0 4px 12px rgba(0,0,0,0.5)",
              userSelect: "none",
            }}
          >
            <span style={{ letterSpacing: "0.08em", textTransform: "uppercase" }}>editing</span>
            <button
              type="button"
              onClick={() =>
                setCalibrate(
                  calibrate ? null : { stage: "img", pairs: [], pendingImg: null, proposed: null }
                )
              }
              title="N-point calibrate: alternate clicks - a landmark on the image, then where it belongs on the basemap. Two pairs give an exact fit; add a third (or more) to measure the alignment error. The floor plan is rotated, scaled and translated to match. Esc to cancel."
              style={{
                padding: "2px 8px",
                background: calibrate ? "rgba(251,191,36,0.25)" : "transparent",
                color: calibrate ? "#fbbf24" : "#cce0ff",
                border: `1px solid ${calibrate ? "#fbbf2488" : "rgba(255,255,255,0.18)"}`,
                borderRadius: 4,
                fontSize: 10,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                fontFamily: "ui-monospace, monospace",
                cursor: "pointer",
              }}
            >
              ↔ calibrate
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              title="Finish editing (Esc)"
              style={{
                padding: "2px 8px",
                background: "rgba(93,255,176,0.18)",
                color: "#5dffb0",
                border: "1px solid #5dffb088",
                borderRadius: 4,
                fontSize: 10,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                fontFamily: "ui-monospace, monospace",
                cursor: "pointer",
              }}
            >
              ✓ done
            </button>
          </div>
        )}

        {/* Reference-point panel. Floats bottom-left when there is at least
            one point. Each row shows index + coords + copy/remove buttons.
            Independent from any other tool. */}
        {refPoints.length > 0 && (
          <div
            style={{
              position: "absolute",
              bottom: 12,
              left: 12,
              zIndex: 650,
              background: "rgba(8,14,32,0.96)",
              border: "1px solid rgba(192,132,252,0.5)",
              borderRadius: 8,
              padding: "10px 12px",
              fontFamily: "ui-monospace, monospace",
              fontSize: 11,
              color: "#cce0ff",
              maxWidth: 320,
              boxShadow: "0 8px 20px rgba(0,0,0,0.5)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 8,
                marginBottom: 6,
              }}
            >
              <span style={{ color: "#c084fc", letterSpacing: "0.08em", textTransform: "uppercase", fontSize: 10 }}>
                ref points · {refPoints.length}
              </span>
              <button
                type="button"
                onClick={() => setRefPoints([])}
                style={{
                  padding: "2px 8px",
                  background: "transparent",
                  color: "#9aa9c4",
                  border: "1px solid rgba(255,255,255,0.18)",
                  borderRadius: 4,
                  fontSize: 10,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  fontFamily: "ui-monospace, monospace",
                  cursor: "pointer",
                }}
              >
                clear
              </button>
            </div>
            {refPoints.map((p, idx) => {
              const text = `${p.lat.toFixed(7)}, ${p.lng.toFixed(7)}`;
              return (
                <div
                  key={p.id}
                  style={{ display: "flex", alignItems: "center", gap: 6, padding: "2px 0" }}
                >
                  <span style={{ color: "#c084fc", minWidth: 18 }}>#{idx + 1}</span>
                  <span style={{ flex: 1 }}>{text}</span>
                  <button
                    type="button"
                    onClick={() => navigator.clipboard?.writeText(text)}
                    title="Copy lat,lon"
                    style={{
                      padding: "1px 6px",
                      background: "transparent",
                      color: "#9aa9c4",
                      border: "1px solid rgba(255,255,255,0.18)",
                      borderRadius: 3,
                      fontSize: 10,
                      fontFamily: "ui-monospace, monospace",
                      cursor: "pointer",
                    }}
                  >
                    copy
                  </button>
                  <button
                    type="button"
                    onClick={() => removeRefPoint(p.id)}
                    title="Remove this point"
                    style={{
                      padding: "1px 6px",
                      background: "transparent",
                      color: "#ff6b78",
                      border: "1px solid #ff6b7855",
                      borderRadius: 3,
                      fontSize: 10,
                      fontFamily: "ui-monospace, monospace",
                      cursor: "pointer",
                    }}
                  >
                    ×
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {/* OSM snap-to-building preview panel. Floats top-left so the
            operator can review what Overpass returned + pick from the top-5
            candidates + flip the OMBB 90° before committing. Nothing in the
            layout changes until they hit Apply. */}
        {snapPreview && (() => {
          const cand = snapPreview.candidates[snapPreview.selectedIdx];
          const proj = projectSnapResult(cand.georef, snapPreview.rotate90);
          const osmHref = `https://www.openstreetmap.org/${cand.osm_type}/${cand.osm_id}`;
          const dimLine = `${proj.width_m.toFixed(1)} × ${proj.height_m.toFixed(1)} m · az ${proj.azimuth_deg.toFixed(0)}°`;
          // Distance between current area centre and OSM building centre,
          // in metres. Exposes the OSM-vs-satellite registration drift so
          // the operator can see *why* a full snap would move their image.
          let driftM = null;
          if (hasArea) {
            const azRadO = (proj.azimuth_deg * Math.PI) / 180;
            const ombCtrE = (proj.width_m / 2) * Math.cos(azRadO) + (proj.height_m / 2) * Math.sin(azRadO);
            const ombCtrN = -(proj.width_m / 2) * Math.sin(azRadO) + (proj.height_m / 2) * Math.cos(azRadO);
            const ombCtrLat = proj.latitude + ombCtrN / M_PER_DEG;
            const ombCtrLng =
              proj.longitude + ombCtrE / (M_PER_DEG * Math.cos((proj.latitude * Math.PI) / 180));
            const dN = (ombCtrLat - centre.lat) * M_PER_DEG;
            const dE = (ombCtrLng - centre.lng) * M_PER_DEG * Math.cos((centre.lat * Math.PI) / 180);
            driftM = Math.hypot(dN, dE);
          }
          const mode = snapPreview.mode || "full";
          return (
            <div
              style={{
                position: "absolute",
                top: 12,
                left: 12,
                zIndex: 700,
                background: "rgba(8,14,32,0.96)",
                border: "1px solid rgba(93,255,176,0.5)",
                borderRadius: 8,
                padding: "10px 12px",
                fontFamily: "ui-monospace, monospace",
                fontSize: 11,
                color: "#e6edf7",
                boxShadow: "0 8px 20px rgba(0,0,0,0.5)",
                minWidth: 280,
                maxWidth: 360,
              }}
            >
              <div
                style={{
                  fontSize: 10,
                  letterSpacing: "0.10em",
                  textTransform: "uppercase",
                  color: "#5dffb0",
                  marginBottom: 6,
                }}
              >
                ✦ snap preview · {snapPreview.candidates.length} candidate
                {snapPreview.candidates.length === 1 ? "" : "s"}
              </div>
              <div style={{ marginBottom: 8 }}>
                <label
                  style={{
                    fontSize: 10,
                    color: "#7a8aab",
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                  }}
                >
                  building
                </label>
                <select
                  value={snapPreview.selectedIdx}
                  onChange={(e) =>
                    setSnapPreview({
                      ...snapPreview,
                      selectedIdx: Number(e.target.value),
                      rotate90: false,
                    })
                  }
                  style={{
                    display: "block",
                    width: "100%",
                    marginTop: 3,
                    padding: "4px 6px",
                    background: "rgba(255,255,255,0.04)",
                    color: "#e6edf7",
                    border: "1px solid rgba(255,255,255,0.12)",
                    borderRadius: 4,
                    fontFamily: "ui-monospace, monospace",
                    fontSize: 11,
                  }}
                >
                  {snapPreview.candidates.map((c, i) => (
                    <option key={i} value={i} style={{ background: "#0c1428" }}>
                      #{i + 1} · {c.area_m2.toFixed(0)} m²
                      {c.name ? ` · ${c.name}` : ""}
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ marginBottom: 8, color: "#cce0ff" }}>
                {dimLine}
                {driftM != null && (
                  <div
                    style={{
                      color: driftM > 5 ? "#ffb347" : "#7a8aab",
                      fontSize: 10,
                      marginTop: 4,
                      lineHeight: 1.4,
                    }}
                    title="Distance between your current area's centre and the OSM building's centre. OSM polygons and satellite tiles often drift 5–20 m apart due to different geodetic reference frames. If the satellite tile looks right, prefer orientation-only mode."
                  >
                    OSM drift from current area: {driftM.toFixed(1)} m
                  </div>
                )}
                {floorImage?.data_url && room_w > 0 && mode === "full" && (
                  <div style={{ color: "#ffb347", fontSize: 10, marginTop: 4, lineHeight: 1.4 }}>
                    image present - only re-centre + re-orient (keep {room_w.toFixed(1)} × {room_h.toFixed(1)} m)
                  </div>
                )}
              </div>
              {/* Apply mode toggle. Default "full" snap is most useful for a
                  cold start (no area yet). "orientation only" keeps the
                  operator's manual placement against the satellite tile and
                  borrows just OSM's azimuth - the right choice when the OSM
                  polygon is drifted relative to ESRI imagery. */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 4,
                  marginBottom: 8,
                  border: "1px solid rgba(255,255,255,0.08)",
                  borderRadius: 4,
                  padding: 2,
                }}
              >
                {[
                  ["full", "full snap", "lat/lng + azimuth (+ size if no image)"],
                  ["orientation", "orient only", "only azimuth - keep current position"],
                ].map(([key, label, hint]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setSnapPreview({ ...snapPreview, mode: key })}
                    title={hint}
                    style={{
                      padding: "4px 6px",
                      background: mode === key ? "rgba(58,130,255,0.25)" : "transparent",
                      color: mode === key ? "#cce0ff" : "#7a8aab",
                      border: "none",
                      borderRadius: 3,
                      fontSize: 10,
                      letterSpacing: "0.06em",
                      textTransform: "uppercase",
                      fontFamily: "ui-monospace, monospace",
                      cursor: "pointer",
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
                <button
                  type="button"
                  onClick={() =>
                    setSnapPreview({ ...snapPreview, rotate90: !snapPreview.rotate90 })
                  }
                  title="Rotate the OMBB rectangle by 90°. Useful when the building's main axis is square-ish and the auto-orientation picked the wrong one."
                  style={{
                    flex: 1,
                    padding: "5px 8px",
                    background: snapPreview.rotate90
                      ? "rgba(58,130,255,0.25)"
                      : "transparent",
                    color: snapPreview.rotate90 ? "#cce0ff" : "#9ec3ff",
                    border: "1px solid rgba(58,130,255,0.4)",
                    borderRadius: 4,
                    fontSize: 11,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    fontFamily: "ui-monospace, monospace",
                    cursor: "pointer",
                  }}
                >
                  ↻ 90°{snapPreview.rotate90 ? " ✓" : ""}
                </button>
                <a
                  href={osmHref}
                  target="_blank"
                  rel="noreferrer"
                  title="Open the matched building on openstreetmap.org"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    padding: "5px 8px",
                    background: "transparent",
                    color: "#7a8aab",
                    border: "1px solid rgba(255,255,255,0.12)",
                    borderRadius: 4,
                    fontSize: 11,
                    fontFamily: "ui-monospace, monospace",
                    textDecoration: "none",
                  }}
                >
                  OSM ↗
                </a>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button
                  type="button"
                  onClick={applySnapPreview}
                  style={{
                    flex: 1,
                    padding: "6px 10px",
                    background: "rgba(93,255,176,0.18)",
                    color: "#5dffb0",
                    border: "1px solid #5dffb088",
                    borderRadius: 4,
                    fontSize: 11,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    fontFamily: "ui-monospace, monospace",
                    cursor: "pointer",
                  }}
                >
                  ✓ apply
                </button>
                <button
                  type="button"
                  onClick={() => setSnapPreview(null)}
                  style={{
                    flex: 1,
                    padding: "6px 10px",
                    background: "transparent",
                    color: "#9ec3ff",
                    border: "1px solid rgba(255,255,255,0.18)",
                    borderRadius: 4,
                    fontSize: 11,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    fontFamily: "ui-monospace, monospace",
                    cursor: "pointer",
                  }}
                >
                  ✕ cancel
                </button>
              </div>
            </div>
          );
        })()}

        {/* Two-point calibration stage hint. Floats top-centre while the
            tool is active so the operator always knows what the next click
            does. After 4 clicks, this is replaced by the Apply/Cancel panel
            below. */}
        {calibrate && editing && hasArea && (
          <div
            style={{
              position: "absolute",
              top: 12,
              left: "50%",
              transform: "translateX(-50%)",
              zIndex: 600,
              background: "rgba(8,14,32,0.95)",
              border: `1px solid ${
                calibrateReject ? "#ff6b78aa" : calibrate.stage === "world" ? "#5dffb088" : "#fbbf2488"
              }`,
              borderRadius: 6,
              padding: "5px 10px",
              fontFamily: "ui-monospace, monospace",
              fontSize: 11,
              color: calibrateReject
                ? "#ff6b78"
                : calibrate.stage === "world"
                ? "#5dffb0"
                : "#fbbf24",
              boxShadow: "0 4px 12px rgba(0,0,0,0.5)",
              userSelect: "none",
              whiteSpace: "nowrap",
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              display: "inline-flex",
              alignItems: "center",
              gap: 10,
            }}
          >
            <span>
              {calibrateReject ? (
                <>✕ {calibrateReject}</>
              ) : (
                <>
                  {calibrate.stage === "img" &&
                    (calibrate.pairs.length === 0
                      ? "↔ pair 1 - click a landmark on the image"
                      : `↔ pair ${calibrate.pairs.length + 1} - click another landmark on the image, or apply`)}
                  {calibrate.stage === "world" &&
                    `↔ pair ${calibrate.pairs.length + 1} - click where that landmark sits on the basemap`}
                </>
              )}
            </span>
            {(calibrate.pairs.length > 0 || calibrate.pendingImg) && !calibrateReject && (
              <button
                type="button"
                onClick={stepBackCalibrate}
                title="Drop the last placed point (Ctrl/Cmd+Z)"
                style={{
                  padding: "1px 7px",
                  background: "transparent",
                  color: "#9ec3ff",
                  border: "1px solid rgba(255,255,255,0.18)",
                  borderRadius: 3,
                  fontSize: 10,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  fontFamily: "ui-monospace, monospace",
                  cursor: "pointer",
                }}
              >
                ↩ back
              </button>
            )}
          </div>
        )}

        {/* Calibration fit panel - live from the second completed pair.
            Shows the proposed transform + per-pair residuals so the operator
            can SEE alignment quality before committing. With exactly two
            pairs the fit is exact by construction; the panel says so and
            nudges towards a third point. */}
        {calibrate?.proposed && (
          <div
            style={{
              position: "absolute",
              top: 12,
              left: 12,
              zIndex: 700,
              background: "rgba(8,14,32,0.96)",
              border: "1px solid rgba(93,255,176,0.5)",
              borderRadius: 8,
              padding: "10px 12px",
              fontFamily: "ui-monospace, monospace",
              fontSize: 11,
              color: "#e6edf7",
              boxShadow: "0 8px 20px rgba(0,0,0,0.5)",
              minWidth: 250,
            }}
          >
            <div
              style={{
                fontSize: 10,
                letterSpacing: "0.10em",
                textTransform: "uppercase",
                color: "#5dffb0",
                marginBottom: 6,
              }}
            >
              ↔ calibration fit · {calibrate.pairs.length} points · vs {baseLayerSlug}
            </div>
            <div style={{ marginBottom: 8, color: "#cce0ff", lineHeight: 1.5 }}>
              new dims: {calibrate.proposed.width_m.toFixed(1)} × {calibrate.proposed.height_m.toFixed(1)} m
              <br />
              azimuth: {calibrate.proposed.azimuth_deg.toFixed(1)}°
              <br />
              scale ×{calibrate.proposed.scaleFactor.toFixed(3)} vs current
            </div>
            {calibrate.pairs.length === 2 ? (
              <div style={{ marginBottom: 8, color: "#fbbf24", fontSize: 10, lineHeight: 1.5 }}>
                2 points = exact fit, error not measurable.
                <br />
                Add a 3rd pair to see the real alignment error.
              </div>
            ) : (
              <div style={{ marginBottom: 8, lineHeight: 1.5 }}>
                <span style={{ color: "#7a8aab", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  residuals
                </span>
                {calibrate.proposed.residuals.map((r, i) => (
                  <div key={i} style={{ color: r > 1.5 ? "#fbbf24" : "#cce0ff" }}>
                    #{i + 1}: {r.toFixed(2)} m{r > 1.5 ? "  ← check this pair" : ""}
                  </div>
                ))}
                <div style={{ color: "#5dffb0", marginTop: 2 }}>
                  RMS {calibrate.proposed.rms.toFixed(2)} m
                </div>
              </div>
            )}
            <div style={{ display: "flex", gap: 6 }}>
              <button
                type="button"
                onClick={applyCalibration}
                style={{
                  flex: 1,
                  padding: "6px 10px",
                  background: "rgba(93,255,176,0.18)",
                  color: "#5dffb0",
                  border: "1px solid #5dffb088",
                  borderRadius: 4,
                  fontSize: 11,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  fontFamily: "ui-monospace, monospace",
                  cursor: "pointer",
                }}
              >
                ✓ apply
              </button>
              <button
                type="button"
                onClick={() => setCalibrate(null)}
                style={{
                  flex: 1,
                  padding: "6px 10px",
                  background: "transparent",
                  color: "#9ec3ff",
                  border: "1px solid rgba(255,255,255,0.18)",
                  borderRadius: 4,
                  fontSize: 11,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  fontFamily: "ui-monospace, monospace",
                  cursor: "pointer",
                }}
              >
                ✕ cancel
              </button>
            </div>
          </div>
        )}

        {/* Live drag readout. Floats top-centre during a handle drag so the
            operator can see the value snap in real time. */}
        {dragInfo && (
          <div
            style={{
              position: "absolute",
              top: 12,
              left: "50%",
              transform: "translateX(-50%)",
              zIndex: 600,
              background: "rgba(8,14,32,0.95)",
              border: "1px solid rgba(255,255,255,0.18)",
              borderRadius: 6,
              padding: "5px 12px",
              fontFamily: "ui-monospace, monospace",
              fontSize: 12,
              color: "#e6edf7",
              boxShadow: "0 4px 12px rgba(0,0,0,0.5)",
              userSelect: "none",
              pointerEvents: "none",
              whiteSpace: "nowrap",
            }}
          >
            {dragInfo}
          </div>
        )}

        {!hasArea && !snapPreview && (
          <div
            style={{
              position: "absolute",
              top: 60,
              left: "50%",
              transform: "translateX(-50%)",
              zIndex: 600,
              background: "rgba(8,14,32,0.95)",
              border: "1px solid rgba(58,130,255,0.4)",
              borderRadius: 8,
              padding: "14px 18px",
              color: "#cce0ff",
              fontFamily: "ui-sans-serif, system-ui",
              fontSize: 12,
              boxShadow: "0 8px 20px rgba(0,0,0,0.5)",
              maxWidth: 360,
              textAlign: "center",
            }}
          >
            <div style={{ fontSize: 11, letterSpacing: "0.10em", textTransform: "uppercase", color: "#7a8aab" }}>
              no area defined yet
            </div>
            <div style={{ marginTop: 6, lineHeight: 1.4 }}>
              Either upload an architectural reference image (treated as the
              area at its actual scale), or draw a rectangle to bound the
              site manually.
            </div>
          </div>
        )}
        <MapContainer
          center={[origin.latitude || 0, origin.longitude || 0]}
          zoom={19}
          maxZoom={22}
          style={{ height: "100%", width: "100%" }}
          worldCopyJump
          // Smoother zoom UX: fractional zoom levels (`zoomSnap=0`) + slower
          // wheel response so a normal scroll-tick is a fraction of a zoom
          // level, not a full step. Doubles `wheelPxPerZoomLevel` so the
          // operator can ease in/out precisely. `zoomDelta` keeps +/- buttons
          // at half-step granularity.
          zoomSnap={0}
          zoomDelta={0.5}
          wheelDebounceTime={40}
          wheelPxPerZoomLevel={120}
          // Default Leaflet places +/- in the top-left, which competes with
          // the layers control and is unintuitive. Disable it and remount
          // bottom-right below, where most modern map UIs put it.
          zoomControl={false}
        >
          <ZoomControl position="bottomright" />
          <RefPointPicker active={refPickMode} onAdd={addRefPoint} />
          {refPoints.map((p, idx) => (
            <CircleMarker
              key={p.id}
              center={[p.lat, p.lng]}
              radius={7}
              pathOptions={{
                color: "#0c1428",
                fillColor: "#c084fc",
                fillOpacity: 1,
                weight: 2,
              }}
              eventHandlers={{ click: () => removeRefPoint(p.id) }}
            >
              <Tooltip permanent direction="top" offset={[0, -8]}>
                <div style={{ fontFamily: "ui-monospace, monospace", fontSize: 11, lineHeight: 1.3 }}>
                  <div style={{ color: "#c084fc", fontWeight: 600 }}>#{idx + 1}</div>
                  <div>{p.lat.toFixed(7)}, {p.lng.toFixed(7)}</div>
                </div>
              </Tooltip>
            </CircleMarker>
          ))}
          <LayersControl position="topright">
            {/* Preference order: Mapbox (highest-res, matches most vendor
                portals) when a token is configured, then Google satellite,
                Google hybrid, Esri, Street. The first AVAILABLE entry is the
                default - `BASEMAP_ORDER` is computed once at module load. */}
            {BASEMAP_ORDER.map((bm) => (
              <BaseLayer key={bm.name} checked={bm.isDefault} name={bm.name}>
                <TileLayer
                  attribution={bm.tile.attribution}
                  url={bm.tile.url}
                  maxZoom={22}
                  maxNativeZoom={bm.tile.maxNativeZoom}
                />
              </BaseLayer>
            ))}
          </LayersControl>
          {/* Rotated image overlay - DOM <img> in the overlayPane, driven
              by a CSS matrix built from TL/TR/BL corners so the picture
              rotates rigidly instead of stretching to an axis-aligned bbox.
              An invisible polygon over the same corners catches click + drag
              for selection / move (image itself has pointer-events none). */}
          {hasArea && floorImage?.data_url && imgNatural && (
            <RotatedImageOverlay
              url={floorImage.data_url}
              opacity={floorImage.opacity ?? 0.7}
              corners={{
                BL: corners[0],
                BR: corners[1],
                TR: corners[2],
                TL: corners[3],
              }}
              naturalSize={imgNatural}
            />
          )}
          {hasArea && floorImage?.data_url && (
            <Polygon
              key={calibrate ? "polygon-img-calibrate" : "polygon-img-edit"}
              positions={corners.map((c) => [c.lat, c.lng])}
              pathOptions={{
                color: selected ? "#fbbf24" : "#38bdf8",
                weight: selected ? 3 : 0,
                fill: true,
                fillColor: "#000",
                fillOpacity: 0,
              }}
              bubblingMouseEvents={false}
              interactive={!calibrate && !refPickMode}
              eventHandlers={{
                click: (e) => {
                  if (calibrate || refPickMode) return;
                  L.DomEvent.stopPropagation(e.originalEvent);
                  setSelected(true);
                },
                mousedown: (e) => {
                  if (!editing || calibrate) return;
                  // Capture where the operator GRABBED the rectangle (and
                  // the origin at that moment) so on each mousemove we
                  // translate by the cursor's displacement from that grab
                  // point. Previously we used the rectangle's centre as the
                  // reference, which made the first mousemove snap the
                  // centre to the cursor - impossible to place accurately.
                  const grabLat = e.latlng.lat;
                  const grabLng = e.latlng.lng;
                  const startLat = origin.latitude;
                  const startLng = origin.longitude;
                  startHandleDragT(
                    e,
                    (ev, map) => {
                      const ll = map.mouseEventToLatLng(ev);
                      const newLat = startLat + (ll.lat - grabLat);
                      const newLng = startLng + (ll.lng - grabLng);
                      onOriginChange({ latitude: newLat, longitude: newLng });
                      setDragInfo(`lat ${newLat.toFixed(6)} · lon ${newLng.toFixed(6)}`);
                    },
                    { onEnd: () => { setDragInfo(null); swallowNextClick(); } }
                  );
                },
              }}
            />
          )}

          <MapHandle onReady={(m) => (mapRef.current = m)} />
          <MapClickCatcher
            onClick={() => {
              // While editing, map clicks NEVER deselect / exit. Editing is
              // sticky - the operator confirms with the ✓ done pill or Esc.
              // This eliminates the entire class of "released mouse on map
              // by accident → lost edit state" bugs that no event-stop
              // hack fully avoids.
              if (editing) return;
              setSelected(false);
            }}
            shouldIgnore={() => ignoreClickRef.current || Boolean(calibrate)}
          />
          <FitOnFirstLoad origin={origin} />
          <FlyTo target={flyTarget} />
          <CoordsReadout />

          {/* N-point calibration picker - collects correspondence pairs. */}
          <CalibratePicker
            active={Boolean(calibrate && editing && hasArea)}
            calibrate={calibrate}
            setCalibrate={setCalibrate}
            computeFit={computeFit}
            isOnImage={isPointOnFloorPlanImage}
            onReject={(msg) => {
              setCalibrateReject(msg);
              setTimeout(() => setCalibrateReject(null), 1800);
            }}
          />

          {/* Preview rectangle for the proposed calibration: live from the
              second completed pair, refits on every additional pair. Cyan
              dashed to distinguish from the live yellow editing area. */}
          {calibrate?.proposed && (() => {
            const p = calibrate.proposed;
            const previewOrigin = {
              latitude: p.latitude,
              longitude: p.longitude,
              azimuth_deg: p.azimuth_deg,
            };
            const c = [
              localToGps(0, 0, previewOrigin),
              localToGps(p.width_m, 0, previewOrigin),
              localToGps(p.width_m, p.height_m, previewOrigin),
              localToGps(0, p.height_m, previewOrigin),
            ];
            return (
              <Polygon
                positions={c.map((q) => [q.lat, q.lng])}
                pathOptions={{
                  color: "#38bdf8",
                  weight: 2,
                  dashArray: "2 5",
                  fillColor: "#38bdf8",
                  fillOpacity: 0.08,
                }}
                interactive={false}
              />
            );
          })()}

          {/* OSM-snap preview layers. Renders only while the operator is in
              the preview flow (the panel above the map drives this state).
              Outlines the actual OSM polygon AND the OMBB rectangle that
              would be committed - distinct colours so they're not mistaken
              for the editor's own area polygon. */}
          {snapPreview && (() => {
            const cand = snapPreview.candidates[snapPreview.selectedIdx];
            if (!cand) return null;
            const g = projectSnapResult(cand.georef, snapPreview.rotate90);
            const mode = snapPreview.mode || "full";
            // In "orientation only" mode the preview rectangle stays at the
            // operator's current position; only the azimuth comes from OSM.
            // Otherwise it reflects the OMBB position + dims that would be
            // committed (using image dims if an image is loaded).
            let previewOrigin, w, h;
            if (mode === "orientation" && hasArea) {
              // Rotate the current rectangle around its centre to the new
              // azimuth, so the operator can preview the orientation change.
              const newAz = g.azimuth_deg;
              const azRad = (newAz * Math.PI) / 180;
              const halfW = room_w / 2;
              const halfH = room_h / 2;
              const eOff = halfW * Math.cos(azRad) + halfH * Math.sin(azRad);
              const nOff = -halfW * Math.sin(azRad) + halfH * Math.cos(azRad);
              const newLat = centre.lat - nOff / M_PER_DEG;
              const newLng =
                centre.lng - eOff / (M_PER_DEG * Math.cos((centre.lat * Math.PI) / 180));
              previewOrigin = { latitude: newLat, longitude: newLng, azimuth_deg: newAz };
              w = room_w;
              h = room_h;
            } else if (floorImage?.data_url && room_w > 0 && room_h > 0) {
              // Full snap with image present: keep image dims, centre on OSM.
              const azRad = (g.azimuth_deg * Math.PI) / 180;
              const cosA = Math.cos(azRad);
              const sinA = Math.sin(azRad);
              const eMidB = (g.width_m / 2) * cosA + (g.height_m / 2) * sinA;
              const nMidB = -(g.width_m / 2) * sinA + (g.height_m / 2) * cosA;
              const ctrLat = g.latitude + nMidB / M_PER_DEG;
              const ctrLng =
                g.longitude + eMidB / (M_PER_DEG * Math.cos((g.latitude * Math.PI) / 180));
              const eMidI = (room_w / 2) * cosA + (room_h / 2) * sinA;
              const nMidI = -(room_w / 2) * sinA + (room_h / 2) * cosA;
              const newLat = ctrLat - nMidI / M_PER_DEG;
              const newLng =
                ctrLng - eMidI / (M_PER_DEG * Math.cos((ctrLat * Math.PI) / 180));
              previewOrigin = { latitude: newLat, longitude: newLng, azimuth_deg: g.azimuth_deg };
              w = room_w;
              h = room_h;
            } else {
              previewOrigin = { latitude: g.latitude, longitude: g.longitude, azimuth_deg: g.azimuth_deg };
              w = g.width_m;
              h = g.height_m;
            }
            const rectCorners = [
              localToGps(0, 0, previewOrigin),
              localToGps(w, 0, previewOrigin),
              localToGps(w, h, previewOrigin),
              localToGps(0, h, previewOrigin),
            ];
            return (
              <>
                {/* OSM building polygon - what Overpass actually returned. */}
                <Polygon
                  positions={cand.polygon.map((p) => [p.lat, p.lng])}
                  pathOptions={{
                    color: "#5dffb0",
                    weight: 2,
                    dashArray: "6 4",
                    fillColor: "#5dffb0",
                    fillOpacity: 0.08,
                  }}
                  interactive={false}
                />
                {/* OMBB rectangle that would be applied (post-rotate90). */}
                <Polygon
                  positions={rectCorners.map((c) => [c.lat, c.lng])}
                  pathOptions={{
                    color: "#38bdf8",
                    weight: 2,
                    dashArray: "2 4",
                    fillColor: "#38bdf8",
                    fillOpacity: 0.1,
                  }}
                  interactive={false}
                />
              </>
            );
          })()}

          {/* "You are here" marker + browser-reported accuracy ring.
              Desktop geolocation often falls back to IP/Wi-Fi triangulation,
              so the accuracy ring is usually large - that is the operator's
              cue that the reading is rough and they should verify on the
              map manually. */}
          {myLocation && (
            <>
              <Circle
                center={[myLocation.lat, myLocation.lng]}
                radius={Math.max(1, myLocation.accuracy_m || 0)}
                pathOptions={{
                  color: "#3a82ff",
                  fillColor: "#3a82ff",
                  fillOpacity: 0.12,
                  weight: 1,
                  dashArray: "4 4",
                }}
              />
              <CircleMarker
                center={[myLocation.lat, myLocation.lng]}
                radius={6}
                pathOptions={{
                  color: "#fff",
                  fillColor: "#3a82ff",
                  fillOpacity: 1,
                  weight: 2,
                }}
              >
                <Tooltip permanent direction="bottom" offset={[0, 8]}>
                  you are here · ±{Math.round(myLocation.accuracy_m || 0)} m
                </Tooltip>
              </CircleMarker>
            </>
          )}

          {/* Area polygon. Only when the area is defined AND there is no
              image (image takes its place as the area visualisation). */}
          {hasArea && !floorImage?.data_url && (
            <Polygon
              key={calibrate ? "polygon-noimg-calibrate" : "polygon-noimg-edit"}
              positions={corners.map((c) => [c.lat, c.lng])}
              pathOptions={{
                color: selected ? "#fbbf24" : "#38bdf8",
                weight: selected ? 4 : 3,
                fillColor: selected ? "#fbbf24" : "#38bdf8",
                fillOpacity: selected ? 0.18 : 0.14,
              }}
              bubblingMouseEvents={false}
              interactive={!calibrate && !refPickMode}
              eventHandlers={{
                click: (e) => {
                  if (calibrate || refPickMode) return;
                  L.DomEvent.stopPropagation(e.originalEvent);
                  setSelected(true);
                },
                mousedown: (e) => {
                  if (!editing || calibrate) return;
                  // Capture where the operator GRABBED the rectangle (and
                  // the origin at that moment) so on each mousemove we
                  // translate by the cursor's displacement from that grab
                  // point. Previously we used the rectangle's centre as the
                  // reference, which made the first mousemove snap the
                  // centre to the cursor - impossible to place accurately.
                  const grabLat = e.latlng.lat;
                  const grabLng = e.latlng.lng;
                  const startLat = origin.latitude;
                  const startLng = origin.longitude;
                  startHandleDragT(
                    e,
                    (ev, map) => {
                      const ll = map.mouseEventToLatLng(ev);
                      const newLat = startLat + (ll.lat - grabLat);
                      const newLng = startLng + (ll.lng - grabLng);
                      onOriginChange({ latitude: newLat, longitude: newLng });
                      setDragInfo(`lat ${newLat.toFixed(6)} · lon ${newLng.toFixed(6)}`);
                    },
                    { onEnd: () => { setDragInfo(null); swallowNextClick(); } }
                  );
                },
              }}
            />
          )}


          {/* Anchors as colored markers */}
          {(anchors || []).map((a) => {
            const p = localToGps(a.x, a.y, origin);
            const tech = a.technology || "wifi";
            return (
              <CircleMarker
                key={a.id}
                center={[p.lat, p.lng]}
                radius={5}
                pathOptions={{
                  color: techColors[tech] || techColors.wifi,
                  fillColor: techColors[tech] || techColors.wifi,
                  fillOpacity: 0.9,
                  weight: 1,
                }}
              >
                <Tooltip direction="top">{a.id} · {tech}</Tooltip>
              </CircleMarker>
            );
          })}

          {/* Contextual edit affordance - themed HTML pill anchored above
              the area's top edge. Stays in the visual theme (matches the
              header buttons) instead of looking like a stray tooltip. */}
          {hasArea && selected && !editing && (() => {
            const top = localToGps(room_w / 2, room_h * 1.08, origin);
            const icon = L.divIcon({
              className: "floor-edit-pill",
              html: `
                <div style="
                  display:inline-flex;align-items:center;gap:6px;
                  padding:5px 12px;
                  background:rgba(8,14,32,0.95);
                  color:#5dffb0;
                  border:1px solid #5dffb088;
                  border-radius:6px;
                  font-family:ui-monospace,monospace;
                  font-size:11px;
                  letter-spacing:0.06em;text-transform:uppercase;
                  box-shadow:0 4px 12px rgba(0,0,0,0.5);
                  cursor:pointer;white-space:nowrap;
                ">✎ edit floor</div>
              `,
              iconSize: [110, 28],
              iconAnchor: [55, 14],
            });
            return (
              <Marker
                position={[top.lat, top.lng]}
                icon={icon}
                bubblingMouseEvents={false}
                eventHandlers={{
                  click: (e) => {
                    L.DomEvent.stopPropagation(e.originalEvent);
                    setEditing(true);
                  },
                }}
              />
            );
          })()}


          {/* Azimuth rotation handle. Rotation pivots around the area's
              CENTRE (not the lower-left origin). To pull this off we keep
              the centre fixed in world coords and recompute the BL origin
              after each azimuth change. Hidden during calibration so the
              handle doesn't intercept clicks meant for the image. */}
          {hasArea && editing && !calibrate && (
            <CircleMarker
              center={[azHandlePoint.lat, azHandlePoint.lng]}
              radius={10}
              pathOptions={{ color: "#fff", fillColor: "#ffb347", fillOpacity: 1, weight: 2 }}
              bubblingMouseEvents={false}
              eventHandlers={{
                mousedown: (e) =>
                  startHandleDragT(
                    e,
                    (ev, map) => {
                      const ll = map.mouseEventToLatLng(ev);
                      const dLat = ll.lat - centre.lat;
                      const dLng = ll.lng - centre.lng;
                      const dNorth = dLat * M_PER_DEG;
                      const dEast =
                        dLng * M_PER_DEG * Math.cos((centre.lat * Math.PI) / 180);
                      const azRad = Math.atan2(dEast, dNorth);
                      const az = snapEnabled ? snapM((azRad * 180) / Math.PI, 1) : (azRad * 180) / Math.PI;
                      // Keep centre fixed: origin_new = centre_world - R(az) * (w/2, h/2)
                      // in local-east/north coords.
                      const azNew = rad(az);
                      const cosA = Math.cos(azNew);
                      const sinA = Math.sin(azNew);
                      const halfW = room_w / 2;
                      const halfH = room_h / 2;
                      const eastOffset = halfW * cosA + halfH * sinA;
                      const northOffset = -halfW * sinA + halfH * cosA;
                      const newLat = centre.lat - northOffset / M_PER_DEG;
                      const newLng =
                        centre.lng - eastOffset / (M_PER_DEG * Math.cos((centre.lat * Math.PI) / 180));
                      onOriginChange({
                        azimuth_deg: az,
                        latitude: newLat,
                        longitude: newLng,
                      });
                      setDragInfo(`azimuth ${az.toFixed(0)}°`);
                    },
                    { onEnd: () => { setDragInfo(null); swallowNextClick(); } }
                  ),
              }}
            />
          )}

          {/* 4 corner resize handles. Drag a corner → opposite corner stays
              put → new width/height (and origin if needed) follow the mouse.
              Snap to 0.5 m. */}
          {hasArea && editing && !calibrate && (() => {
            // Local rectangle corners (in the local floor-plan frame).
            const localCorners = {
              BL: { x: 0, y: 0 },       // origin (lower-left)
              BR: { x: room_w, y: 0 },
              TR: { x: room_w, y: room_h },
              TL: { x: 0, y: room_h },
            };
            const opposite = { BL: "TR", BR: "TL", TR: "BL", TL: "BR" };
            const cornerWgs = (key) => localToGps(localCorners[key].x, localCorners[key].y, origin);

            const aspectLocked = Boolean(floorImage?.data_url);
            const aspectRatio = room_w / room_h;
            const onResize = (cornerKey) => (e) => {
              const oppWgs = cornerWgs(opposite[cornerKey]);
              const az = rad(origin.azimuth_deg || 0);
              const cosA = Math.cos(az);
              const sinA = Math.sin(az);
              startHandleDragT(
                e,
                (ev, map) => {
                  const ll = map.mouseEventToLatLng(ev);
                  const dLat = ll.lat - oppWgs.lat;
                  const dLng = ll.lng - oppWgs.lng;
                  const dNorth = dLat * M_PER_DEG;
                  const dEast = dLng * M_PER_DEG * Math.cos((oppWgs.lat * Math.PI) / 180);
                  const localX = dEast * cosA - dNorth * sinA;
                  const localY = dEast * sinA + dNorth * cosA;
                  let newW, newH;
                  if (aspectLocked) {
                    // Image must keep its native aspect ratio. Pick the
                    // larger projection (relative to ratio) and derive the
                    // other dimension from it.
                    const projW = Math.abs(localX);
                    const projH = Math.abs(localY);
                    if (projW / aspectRatio >= projH) {
                      newW = projW;
                      newH = newW / aspectRatio;
                    } else {
                      newH = projH;
                      newW = newH * aspectRatio;
                    }
                    if (snapEnabled) {
                      newW = snapM(newW);
                      newH = newW / aspectRatio;
                    }
                  } else {
                    newW = snapEnabled ? snapM(Math.abs(localX)) : Math.abs(localX);
                    newH = snapEnabled ? snapM(Math.abs(localY)) : Math.abs(localY);
                  }
                  newW = Math.max(0.5, newW);
                  newH = Math.max(0.5, newH);
                  const oppLocalNew = {
                    BL: { x: 0, y: 0 },
                    BR: { x: newW, y: 0 },
                    TR: { x: newW, y: newH },
                    TL: { x: 0, y: newH },
                  }[opposite[cornerKey]];
                  const oppEast = oppLocalNew.x * cosA + oppLocalNew.y * sinA;
                  const oppNorth = -oppLocalNew.x * sinA + oppLocalNew.y * cosA;
                  const newLat = oppWgs.lat - oppNorth / M_PER_DEG;
                  const newLng =
                    oppWgs.lng - oppEast / (M_PER_DEG * Math.cos((oppWgs.lat * Math.PI) / 180));
                  onOriginChange({
                    latitude: newLat,
                    longitude: newLng,
                    width_m: newW,
                    height_m: newH,
                  });
                  setDragInfo(`${newW.toFixed(1)} × ${newH.toFixed(1)} m`);
                },
                { onEnd: () => setDragInfo(null) }
              );
            };

            return ["BL", "BR", "TR", "TL"].map((k) => {
              const p = cornerWgs(k);
              return (
                <CircleMarker
                  key={k}
                  center={[p.lat, p.lng]}
                  radius={11}
                  pathOptions={{
                    color: "#0c1428",
                    fillColor: "#fbbf24",
                    fillOpacity: 1,
                    weight: 2,
                  }}
                  bubblingMouseEvents={false}
                  eventHandlers={{ mousedown: onResize(k) }}
                />
              );
            });
          })()}

          {/* Edge midpoint handles + dimension labels - drag a single edge
              to resize only width OR only height. The opposite edge stays
              fixed in world coords; the local frame's origin (BL) is
              recomputed when the opposite edge is north or east. Hidden
              when the area is an image, because per-axis resize would
              distort the image's aspect ratio. */}
          {hasArea && editing && !floorImage?.data_url && !calibrate && (() => {
            const az = rad(origin.azimuth_deg || 0);
            const cosA = Math.cos(az);
            const sinA = Math.sin(az);
            const edges = [
              { key: "E", x: room_w,     y: room_h / 2, oppX: 0,         oppY: room_h / 2, dim: "width",  value: room_w },
              { key: "W", x: 0,          y: room_h / 2, oppX: room_w,    oppY: room_h / 2, dim: "width",  value: room_w },
              { key: "N", x: room_w / 2, y: room_h,     oppX: room_w / 2, oppY: 0,         dim: "height", value: room_h },
              { key: "S", x: room_w / 2, y: 0,          oppX: room_w / 2, oppY: room_h,    dim: "height", value: room_h },
            ];
            return edges.map((e) => {
              const p = localToGps(e.x, e.y, origin);
              const onEdgeDrag = (mev) => {
                const oppWgs = localToGps(e.oppX, e.oppY, origin);
                startHandleDragT(
                  mev,
                  (drev, map) => {
                    const ll = map.mouseEventToLatLng(drev);
                    const dLat = ll.lat - oppWgs.lat;
                    const dLng = ll.lng - oppWgs.lng;
                    const dNorth = dLat * M_PER_DEG;
                    const dEast = dLng * M_PER_DEG * Math.cos((oppWgs.lat * Math.PI) / 180);
                    const localX = dEast * cosA - dNorth * sinA;
                    const localY = dEast * sinA + dNorth * cosA;
                    if (e.key === "E") {
                      const newW = Math.max(0.5, snapEnabled ? snapM(Math.abs(localX)) : Math.abs(localX));
                      onOriginChange({ width_m: newW });
                      setDragInfo(`width ${newW.toFixed(1)} m`);
                    } else if (e.key === "W") {
                      const newW = Math.max(0.5, snapEnabled ? snapM(Math.abs(localX)) : Math.abs(localX));
                      const halfH = room_h / 2;
                      const eOff = newW * cosA + halfH * sinA;
                      const nOff = -newW * sinA + halfH * cosA;
                      const newLat = oppWgs.lat - nOff / M_PER_DEG;
                      const newLng = oppWgs.lng - eOff / (M_PER_DEG * Math.cos((oppWgs.lat * Math.PI) / 180));
                      onOriginChange({ width_m: newW, latitude: newLat, longitude: newLng });
                      setDragInfo(`width ${newW.toFixed(1)} m`);
                    } else if (e.key === "N") {
                      const newH = Math.max(0.5, snapEnabled ? snapM(Math.abs(localY)) : Math.abs(localY));
                      onOriginChange({ height_m: newH });
                      setDragInfo(`height ${newH.toFixed(1)} m`);
                    } else if (e.key === "S") {
                      const newH = Math.max(0.5, snapEnabled ? snapM(Math.abs(localY)) : Math.abs(localY));
                      const halfW = room_w / 2;
                      const eOff = halfW * cosA + newH * sinA;
                      const nOff = -halfW * sinA + newH * cosA;
                      const newLat = oppWgs.lat - nOff / M_PER_DEG;
                      const newLng = oppWgs.lng - eOff / (M_PER_DEG * Math.cos((oppWgs.lat * Math.PI) / 180));
                      onOriginChange({ height_m: newH, latitude: newLat, longitude: newLng });
                      setDragInfo(`height ${newH.toFixed(1)} m`);
                    }
                  },
                  { onEnd: () => { setDragInfo(null); swallowNextClick(); } }
                );
              };
              return (
                <CircleMarker
                  key={`edge-${e.key}`}
                  center={[p.lat, p.lng]}
                  radius={9}
                  pathOptions={{
                    color: "#0c1428",
                    fillColor: "#38bdf8",
                    fillOpacity: 1,
                    weight: 2,
                  }}
                  bubblingMouseEvents={false}
                  eventHandlers={{ mousedown: onEdgeDrag }}
                >
                  <Tooltip
                    permanent
                    direction={
                      e.key === "N" ? "bottom" :
                      e.key === "S" ? "bottom" :
                      e.key === "E" ? "right" :
                      "left"
                    }
                    offset={
                      e.key === "N" ? [0, 4] :
                      e.key === "S" ? [0, 4] :
                      e.key === "E" ? [4, 0] :
                      [-4, 0]
                    }
                    className="edge-dim-tooltip"
                  >
                    {e.dim} {e.value.toFixed(1)} m
                  </Tooltip>
                </CircleMarker>
              );
            });
          })()}

          {/* Precision grid overlay - 1 m grid lines inside the area when
              the operator wants visual feedback for measurement work. Off
              by default; toggled via the header `grid` checkbox. */}
          {hasArea && editing && showGrid && (() => {
            const step = 1;
            const lines = [];
            for (let x = step; x < room_w; x += step) {
              const a = localToGps(x, 0, origin);
              const b = localToGps(x, room_h, origin);
              lines.push({ key: `gx-${x}`, p: [[a.lat, a.lng], [b.lat, b.lng]] });
            }
            for (let y = step; y < room_h; y += step) {
              const a = localToGps(0, y, origin);
              const b = localToGps(room_w, y, origin);
              lines.push({ key: `gy-${y}`, p: [[a.lat, a.lng], [b.lat, b.lng]] });
            }
            return lines.map((l) => (
              <Polyline
                key={l.key}
                positions={l.p}
                pathOptions={{ color: "#38bdf8", weight: 0.5, opacity: 0.35 }}
              />
            ));
          })()}
        </MapContainer>
      </div>
    </div>
  );
});
