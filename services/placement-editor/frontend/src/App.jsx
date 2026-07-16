import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { loadLayout, saveLayout } from "./api.js";
import { CalibrationPanel } from "./CalibrationPanel.jsx";
import { FloorPlanImageInput, GeorefMap, localToGps } from "./GeorefMap.jsx";
import { PlanCanvas } from "./PlanCanvas.jsx";
import { VendorSyncPanel } from "./VendorSyncPanel.jsx";
import { ToastHost } from "./ToastHost.jsx";
import {
  bboxOfPolygon,
  centroidOfPolygon,
  DEFAULT_FP_ID,
  DEFAULT_OPENING_HEIGHT_M,
  DEFAULT_ROOM_ID,
  DEFAULT_WALL_HEIGHT_M,
  denormalizeForCompat,
  emptyLayoutV2,
  findFloorPlan,
  findRoom,
  normalizeLayout,
  perimeterEdges,
} from "./schema.js";
import { useEditorHistory } from "./useEditorHistory.js";
import { snap, validateLayout, wallLength } from "./validation.js";

const MARGIN_M = 4;
const DEFAULT_SNAP_M = 0.5;
const NUDGE_SMALL = 0.1;
const NUDGE_LARGE = 1.0;
const DEFAULT_WALL_THICKNESS_M = 0.2;

// Technology registry. Anchors with an unknown technology fall back to the
// `wifi` entry's color/icon so old layout files still render sensibly.
//
// NOTE: `fiveg` and `gnss` are placeholders - they exist here (and in the
// 3D demo's TECH_PALETTE) so operators can lay out future anchors of those
// technologies in the editor, but no adapter currently feeds positions from
// either source. Devices routed to a non-existent adapter return 404 from
// the engine, which is the intended safe-by-default behaviour. See
// docs/adapters.md#status-by-technology.
const TECH_REGISTRY = {
  wifi:   { label: "WiFi",  color: "#ffb347", text: "#ffd089", hotkey: "a", default_height_m: 2.7,  default_coverage_m: 30  },
  wittra: { label: "UWB",   color: "#5dffb0", text: "#aaffd6", hotkey: "u", default_height_m: 3.0,  default_coverage_m: 15  },
  fiveg:  { label: "5G",    color: "#c084fc", text: "#dbc1ff", hotkey: "g", default_height_m: 10.0, default_coverage_m: 500 },
  gnss:   { label: "GNSS",  color: "#fbbf24", text: "#fde68a", hotkey: "n", default_height_m: 0.0,  default_coverage_m: 0   },
};
const TECH_KEYS = ["wifi", "wittra", "fiveg", "gnss"];
const DEFAULT_TECH = "wifi";
const techOf = (a) => (a && a.technology) || DEFAULT_TECH;
const techMeta = (key) => TECH_REGISTRY[key] || TECH_REGISTRY[DEFAULT_TECH];
const techColor = (a) => techMeta(techOf(a)).color;
const techText = (a) => techMeta(techOf(a)).text;
// Tool strings: "select" | "wall" | "room" | `anchor:<tech>`
const isAnchorTool = (t) => typeof t === "string" && t.startsWith("anchor:");
const toolTech = (t) => (isAnchorTool(t) ? t.split(":")[1] : null);

const shell = {
  // height + overflow:hidden contain the page to one screen. Anything that
  // needs to scroll (long sidebar) scrolls inside its own area, not the
  // whole document - otherwise the action bar / canvas drift off-screen
  // when the sidebar happens to be tall.
  height: "100vh",
  background: "linear-gradient(180deg, #050816 0%, #0a1228 100%)",
  color: "#e6edf7",
  fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif",
  display: "grid",
  gridTemplateColumns: "320px minmax(0, 1fr)",
  gridTemplateRows: "auto 1fr",
  overflow: "hidden",
};
const header = {
  gridColumn: "1 / -1",
  display: "flex",
  alignItems: "center",
  gap: 12,
  padding: "14px 20px",
  borderBottom: "1px solid rgba(255,255,255,0.06)",
  background: "rgba(10,18,40,0.6)",
};
const sidebar = {
  padding: "16px 14px",
  borderRight: "1px solid rgba(255,255,255,0.06)",
  background: "rgba(8,14,32,0.5)",
  overflowY: "auto",
};
const sectionTitle = {
  fontSize: 10,
  color: "#7a8aab",
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  margin: "16px 0 8px 4px",
};
const field = {
  display: "grid",
  gridTemplateColumns: "70px 1fr",
  alignItems: "center",
  gap: 8,
  marginBottom: 6,
  fontSize: 12,
};
const label = { color: "#7a8aab", fontSize: 11 };
// Action-bar button style. One source of truth for the canvas-top
// toolbar - the bar previously hard-coded the same six-property style
// block per button, which made it impossible to tweak the bar's look
// without grepping. `accent` is the tech / accent colour; `active`
// flips it into a filled state; `secondary` drops weight + size for
// de-prioritised techs (currently used by the "+ more ▾" trigger).
const toolBtnStyle = ({ accent = "#9aa9c4", active = false, secondary = false } = {}) => ({
  padding: secondary ? "4px 10px" : "5px 12px",
  fontSize: secondary ? 10 : 11,
  fontWeight: secondary ? 400 : 600,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  fontFamily: "ui-monospace, monospace",
  background: active ? `${accent}26` : "transparent",
  color: accent,
  border: `1px solid ${accent}${active ? "88" : "55"}`,
  borderRadius: 4,
  cursor: "pointer",
});
const inputStyle = (invalid) => ({
  background: "rgba(255,255,255,0.04)",
  border: `1px solid ${invalid ? "#ff6b78" : "rgba(255,255,255,0.1)"}`,
  color: "#e6edf7",
  padding: "4px 8px",
  borderRadius: 4,
  fontFamily: "ui-monospace, monospace",
  fontSize: 12,
  width: "100%",
  boxSizing: "border-box",
  // Hints the browser to render native dropdown / colour pickers / scroll
  // indicators in dark mode. Without this, <select> option lists default to
  // a light system theme - white background + dim selected text - which is
  // unreadable inside the editor's dark UI.
  colorScheme: "dark",
});
const btn = (variant = "primary", disabled = false) => ({
  padding: "6px 12px",
  borderRadius: 6,
  border: "1px solid",
  cursor: disabled ? "not-allowed" : "pointer",
  fontSize: 12,
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  fontFamily: "ui-monospace, monospace",
  opacity: disabled ? 0.45 : 1,
  background: variant === "primary" ? "rgba(58,130,255,0.2)" : "transparent",
  color: variant === "primary" ? "#9ec3ff" : "#e6edf7",
  borderColor: variant === "primary" ? "rgba(58,130,255,0.5)" : "rgba(255,255,255,0.15)",
});
const apRow = (selected, invalid) => ({
  padding: "8px 10px",
  marginBottom: 4,
  borderRadius: 6,
  cursor: "pointer",
  background: selected ? "rgba(255,179,71,0.1)" : "rgba(255,255,255,0.03)",
  border: `1px solid ${
    invalid ? "#ff6b78" : selected ? "rgba(255,179,71,0.5)" : "rgba(255,255,255,0.05)"
  }`,
  display: "grid",
  gridTemplateColumns: "1fr auto",
  alignItems: "center",
  gap: 6,
  fontSize: 12,
});
const canvasWrap = {
  padding: 20,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  // overflow: hidden contains the floating selection panel + any future
  // canvas-internal overlays. Without it, the absolute-positioned panel
  // pushes the page wider than the viewport when the sidebar is full and
  // the canvas is at max width.
  overflow: "hidden",
  minWidth: 0,
};

const emptyLayout = emptyLayoutV2();

function nextId(items, prefix) {
  const re = new RegExp(`^${prefix}(\\d+)$`);
  const nums = (items || [])
    .map((it) => re.exec(it.id)?.[1])
    .filter(Boolean)
    .map(Number);
  const next = (nums.length ? Math.max(...nums) : 0) + 1;
  return `${prefix}${String(next).padStart(2, "0")}`;
}

const nextApId = (aps) => nextId(aps, "AP");
const nextWallId = (walls) => nextId(walls, "W");
const nextOpeningId = (openings) => nextId(openings, "O");
const nextPerimeterOpeningId = (openings) => nextId(openings, "P");

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

// Controlled numeric input that commits to history only on blur / Enter,
// not on every keystroke. Keeps the keyboard-typing path from flooding undo.
function NumberInput({ value, onCommit, invalid, step = "0.1", min, ...rest }) {
  const [draft, setDraft] = useState(String(value));
  const lastValueRef = useRef(value);

  useEffect(() => {
    // External change (undo/redo/load) - resync.
    if (value !== lastValueRef.current) {
      lastValueRef.current = value;
      setDraft(String(value));
    }
  }, [value]);

  function commitDraft() {
    const n = Number(draft);
    if (Number.isFinite(n) && (min === undefined || n >= min) && n !== value) {
      lastValueRef.current = n;
      onCommit(n);
    } else {
      setDraft(String(value));
    }
  }

  return (
    <input
      {...rest}
      type="number"
      step={step}
      min={min}
      style={inputStyle(invalid)}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commitDraft}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          e.currentTarget.blur();
        } else if (e.key === "Escape") {
          setDraft(String(value));
          e.currentTarget.blur();
        }
      }}
    />
  );
}

function TextInput({ value, onCommit, invalid, ...rest }) {
  const [draft, setDraft] = useState(value || "");
  const lastValueRef = useRef(value || "");

  useEffect(() => {
    if ((value || "") !== lastValueRef.current) {
      lastValueRef.current = value || "";
      setDraft(value || "");
    }
  }, [value]);

  function commitDraft() {
    if (draft !== value) {
      lastValueRef.current = draft;
      onCommit(draft);
    }
  }

  return (
    <input
      {...rest}
      type="text"
      style={inputStyle(invalid)}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commitDraft}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          e.currentTarget.blur();
        } else if (e.key === "Escape") {
          setDraft(value || "");
          e.currentTarget.blur();
        }
      }}
    />
  );
}

// Reusable two-step delete control. First click of the danger button arms a
// confirm UI; second click commits. The parent owns the "armed" id so all
// confirm buttons on the page collapse back when another is armed or the
// selection changes. Used by the floating selected-anchor and selected-wall
// blocks; pull it here so the pattern lives in exactly one place.
function ConfirmDelete({ armed, label, onArm, onConfirm, onCancel }) {
  if (armed) {
    return (
      <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
        <button
          type="button"
          onClick={onConfirm}
          style={{
            flex: 1,
            padding: "5px 8px",
            background: "rgba(255,107,120,0.15)",
            color: "#ff6b78",
            border: "1px solid #ff6b78",
            borderRadius: 4,
            fontSize: 11,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            fontFamily: "ui-monospace, monospace",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          confirm delete
        </button>
        <button
          type="button"
          onClick={onCancel}
          style={{
            padding: "5px 8px",
            background: "transparent",
            color: "#7a8aab",
            border: "1px solid rgba(255,255,255,0.15)",
            borderRadius: 4,
            fontSize: 11,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            fontFamily: "ui-monospace, monospace",
            cursor: "pointer",
          }}
        >
          cancel
        </button>
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={onArm}
      title={`${label} (click again to confirm)`}
      style={{
        marginTop: 12,
        width: "100%",
        padding: "5px 8px",
        background: "transparent",
        color: "#ff6b78",
        border: "1px solid rgba(255,107,120,0.4)",
        borderRadius: 4,
        fontSize: 11,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        fontFamily: "ui-monospace, monospace",
        cursor: "pointer",
      }}
    >
      ✕ {label}
    </button>
  );
}

// Lock / unlock toggle for the floating selection panel. Locked is the
// default state on every new selection so a single click on an anchor
// inspects it without enabling drag. The operator must explicitly
// unlock - that gate is what stops UWB anchors from drifting under
// stray pointer events.
function EditLockToggle({ unlocked, onToggle, accent }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      title={unlocked ? "Lock to prevent accidental drag" : "Unlock to allow drag on the canvas"}
      style={{
        width: "100%",
        padding: "6px 8px",
        margin: "8px 0 6px",
        background: unlocked ? `${accent}26` : "transparent",
        color: unlocked ? accent : "#7a8aab",
        border: `1px solid ${unlocked ? accent : "rgba(255,255,255,0.15)"}`,
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        fontFamily: "ui-monospace, monospace",
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
      }}
    >
      <span style={{ fontSize: 13 }}>{unlocked ? "🔓" : "🔒"}</span>
      <span>{unlocked ? "editing · click to lock" : "locked · click to edit"}</span>
    </button>
  );
}

export function App() {
  const history = useEditorHistory(emptyLayout);
  const layout = history.value;

  const [loadError, setLoadError] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState(null);
  // Selection: { kind: "ap" | "wall", id }. Null = nothing selectedAp.
  const [selection, setSelection] = useState(null);
  const [snapEnabled, setSnapEnabled] = useState(true);
  // Visible 1 m grid overlay while editing - independent from snap. Helps
  // measurement / alignment work; off by default to keep the satellite
  // tile uncluttered.
  const [showGrid, setShowGrid] = useState(false);
  // Tool mode for canvas pointer-down: "select" | "wall" | "room" | "calibrate".
  const [tool, setTool] = useState("select");
  const [drawingPreview, setDrawingPreview] = useState(null);
  // WiFi calibration state. While `tool === "calibrate"`, a click on the
  // section-3 canvas pushes a {x_m, y_m} into `pendingCalibrationClick`;
  // the CalibrationPanel picks it up, opens a capture session against the
  // adapter, then clears it. `calibrationSamples` mirrors what the
  // adapter has on disk so the canvas can render markers for past points.
  const [pendingCalibrationClick, setPendingCalibrationClick] = useState(null);
  const [calibrationSamples, setCalibrationSamples] = useState([]);
  // Vendor sync state. While `tool === "vendorsync"`, the right rail
  // takes over with the VendorSyncPanel; the canvas overlays ghost
  // markers for every cloud-known device so the operator can see where
  // the vendor thinks they sit before pressing import.
  const [vendorSyncPreview, setVendorSyncPreview] = useState([]);
  // Live adapter capabilities from the engine registry (proxied). Drives the
  // toolbar: CALIBRATE shows only when an adapter advertises `calibration`,
  // and one SYNC button appears per adapter advertising `discover`. No
  // hardcoded wifi / wittra. Refetched when the operator changes section/tool.
  const [adapterCaps, setAdapterCaps] = useState([]);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/capabilities");
        if (!resp.ok) {
          if (!cancelled) setAdapterCaps([]);
          return;
        }
        const body = await resp.json();
        if (!cancelled) setAdapterCaps(Array.isArray(body?.adapters) ? body.adapters : []);
      } catch {
        if (!cancelled) setAdapterCaps([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tool]);
  const calibrationCap = adapterCaps.find((a) => a?.capabilities?.calibration);
  const discoverCaps = adapterCaps.filter((a) => a?.capabilities?.discover);
  const [savedSnapshot, setSavedSnapshot] = useState(emptyLayout);
  // Progressive section: "geo" (drop the building onto the world map) or
  // "plan" (work inside the metric room: walls + anchors). Each step has its
  // own canvas + sidebar, so the user is never forced to think about lat/lon
  // and indoor placement at the same time.
  // 3-section progressive flow: world → plan → room. Each layer aligns to
  // the one above it.
  const [section, setSection] = useState("world");
  // Selection across sections - defaults to the legacy single fp/room ids.
  const [selectedFpId, setSelectedFpId] = useState(DEFAULT_FP_ID);
  const [selectedRoomId, setSelectedRoomId] = useState(DEFAULT_ROOM_ID);
  // Whether the operator has explicitly engaged a floor plan (clicked it on
  // the map or selected it from the sidebar list). The detailed inputs in
  // the World sidebar are hidden until this is true: a floor's georeference
  // / dimensions are meaningless if no floor has been picked yet.
  const [floorEngaged, setFloorEngaged] = useState(false);
  // Inline delete confirmation - the id of the floor plan whose row is
  // currently asking "delete?". Cleared on confirm / cancel. Keeps the
  // confirmation contextual to the row, instead of a modal window.confirm.
  const [confirmDeleteFpId, setConfirmDeleteFpId] = useState(null);
  // Section 2 polygon-trace mode flag. When true, PlanCanvas captures clicks
  // as polygon vertices for the currently-selected room. Toggled from the
  // selected-room sidebar; committed via the trace tool's own controls.
  const [tracingPolygonForRoomId, setTracingPolygonForRoomId] = useState(null);
  // Fit-to-corners tool (Plan section): two loupe-refined clicks on opposite
  // corners of the room on the image → bbox set exactly. Mutually exclusive
  // with trace + scale calibration.
  const [fitCorners, setFitCorners] = useState(null);
  // Action-bar "+ more ▾" dropdown for the de-prioritised technologies
  // (5G, GNSS). Closes on outside click / Esc so it doesn't trap focus.
  const [moreTechOpen, setMoreTechOpen] = useState(false);
  // Sidebar collapsible tech groups. Map of techKey → collapsed?. Default
  // expanded; the operator collapses what they don't care about right now
  // (e.g. hide WiFi while wiring up UWB anchors).
  const [collapsedTech, setCollapsedTech] = useState({});
  // Walls section in the sidebar collapses to a single header by default -
  // the wall list is rarely the operator's working surface (they edit walls
  // on the canvas) but one row per wall used to dominate the rail.
  const [wallsCollapsed, setWallsCollapsed] = useState(true);
  // Collapsed-by-default perimeter-openings section - most rooms have one
  // or two doors, so it's not a hot-traffic surface, but discoverable when
  // the operator wants to model corridor continuations.
  const [perimeterCollapsed, setPerimeterCollapsed] = useState(true);
  // Edit-lock guard on canvas drag. Selecting an item leaves it locked -
  // the user must explicitly click the panel's edit toggle to enable drag
  // for the current selection. UWB-precision tools should not let a stray
  // grab nudge an anchor that was just clicked to inspect it. Reset on
  // any selection or section change so the next item starts locked.
  const [editUnlocked, setEditUnlocked] = useState(false);
  // Delete-confirm token. Stores the id (anchor/wall) currently awaiting a
  // second click on the delete button. Cleared on confirm / cancel /
  // selection change / 3-second timeout.
  const [confirmDelete, setConfirmDelete] = useState(null);
  // Floor-plan-image background under the section 3 grid. Crops the
  // section 2 reference image to the current room's footprint so the
  // operator places anchors against the real floor outline (doors, walls,
  // pillars) instead of an empty grid. The image renders BELOW the grid
  // and the room outline, at user-set opacity. Both default off so the
  // grid stays clean for screenshots.
  const [bgImageEnabled, setBgImageEnabled] = useState(false);
  const [bgImageOpacity, setBgImageOpacity] = useState(0.55);
  // Outside-click closes the "+ more" dropdown. Listening on document
  // means any click that isn't inside the dropdown collapses it.
  useEffect(() => {
    if (!moreTechOpen) return;
    function onDocClick(e) {
      const closest = e.target.closest?.("[data-more-tech]");
      if (!closest) setMoreTechOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [moreTechOpen]);
  // Reset confirm-delete state when selection changes or after a quiet
  // 3-second window, so a stray pending confirm doesn't surprise the
  // operator later.
  useEffect(() => {
    if (!confirmDelete) return;
    const t = setTimeout(() => setConfirmDelete(null), 3000);
    return () => clearTimeout(t);
  }, [confirmDelete]);
  useEffect(() => setConfirmDelete(null), [selection, section]);
  useEffect(() => setEditUnlocked(false), [selection, section]);
  // Section 2 edit mode - mirrors the World step's pencil/done pattern.
  // While `editingRoomId` matches the currently-selected room, the canvas
  // exposes drag-to-move + corner/edge resize + arrow-key nudge. Otherwise
  // the room is read-only (click to select, but no accidental mutations).
  const [editingRoomId, setEditingRoomId] = useState(null);
  // Section 2 scale-calibration tool. Operator picks pairs of points on the
  // image and types the known real-world distance between each pair; the
  // editor averages the implied scale factors and applies a single uniform
  // rescale to the floor plan. Designed for UWB precision work where the
  // operator has multiple tape-measured references (walls, doorways, etc.)
  // and wants every one of them contributing to the scale.
  //   shape: { fpId,
  //            picking: "p1" | "p2" | null,        // current click stage
  //            pendingP1: [x, y] | null,           // first click waiting on second
  //            pendingP2: [x, y] | null,           // second click waiting on known-distance entry
  //            refs: [{ id, p1, p2, distNow, knownM }] }
  const [scaleCal, setScaleCal] = useState(null);

  const svgRef = useRef(null);
  const dragRef = useRef(null);
  const drawRef = useRef(null);
  const georefRef = useRef(null);
  // Hidden <input type="file"> used by the Import button. Clicking the
  // visible Import button programmatically clicks this; the file's text
  // is parsed in onImportFileChosen below.
  const importFileRef = useRef(null);
  // Flag set while the user is dragging the opacity slider. While true, image
  // mutations from the slider route through `applyTransient` so the entire
  // drag collapses into a single undoable step instead of one per pixel.
  const opacityDragRef = useRef(false);
  // Mirror flag for area-handle drags in the World step (corner / edge /
  // rotate / image translate). Lets `onOriginChange` mutate via transient
  // history during a drag instead of committing on every mousemove sample.
  const geoDragRef = useRef(false);

  // Initial load.
  useEffect(() => {
    loadLayout()
      .then((data) => {
        const initial = normalizeLayout(data) || emptyLayout;
        history.replace(initial);
        setSavedSnapshot(initial);
        // Land on the first floor plan / first room of the new layout so
        // the section selectors point at something sensible.
        if (initial.floor_plans?.[0]) setSelectedFpId(initial.floor_plans[0].id);
        if (initial.rooms?.[0]) setSelectedRoomId(initial.rooms[0].id);
        setLoaded(true);
      })
      .catch((err) => {
        setLoadError(err.message);
        setLoaded(true);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty = useMemo(() => !deepEqual(layout, savedSnapshot), [layout, savedSnapshot]);
  const errors = useMemo(() => validateLayout(layout), [layout]);
  const errorByField = useMemo(() => {
    const m = new Map();
    for (const e of errors) m.set(e.field, e.message);
    return m;
  }, [errors]);
  const isValid = errors.length === 0;

  // v2 selectors: derive current floor-plan + current room from the layout
  // tree, then expose aps/walls/gps_origin as flat shims so the existing
  // render + mutation logic keeps working unchanged.
  const currentFp = findFloorPlan(layout, selectedFpId) || layout.floor_plans?.[0] || null;
  const currentRoom = findRoom(layout, selectedRoomId) || layout.rooms?.[0] || null;
  const aps = currentRoom?.anchors || [];
  const walls = currentRoom?.walls || [];

  const apById = useCallback(
    (id) => aps.find((a) => a.id === id),
    [aps]
  );
  const wallById = useCallback(
    (id) => walls.find((w) => w.id === id),
    [walls]
  );

  // Scoped mutations: replace the matching floor-plan / room in place so
  // every commit hits exactly one element in its array.
  const mutateFp = useCallback(
    (mutator) => {
      history.commit((l) => ({
        ...l,
        floor_plans: (l.floor_plans || []).map((fp) =>
          fp.id === (currentFp?.id ?? selectedFpId) ? mutator(fp) : fp
        ),
      }));
    },
    [history, currentFp, selectedFpId]
  );
  const mutateRoom = useCallback(
    (mutator) => {
      history.commit((l) => ({
        ...l,
        rooms: (l.rooms || []).map((r) =>
          r.id === (currentRoom?.id ?? selectedRoomId) ? mutator(r) : r
        ),
      }));
    },
    [history, currentRoom, selectedRoomId]
  );
  const selectedApId = selection?.kind === "ap" ? selection.id : null;
  const selectedWallId = selection?.kind === "wall" ? selection.id : null;
  const selectedAp = selectedApId ? apById(selectedApId) : null;
  const selectedWall = selectedWallId ? wallById(selectedWallId) : null;
  const selectAp = useCallback((id) => setSelection(id ? { kind: "ap", id } : null), []);
  const selectWall = useCallback(
    (id) => setSelection(id ? { kind: "wall", id } : null),
    []
  );

  // --- Mutations ---

  // Room dimensions live on the room entry (v2). Mapping `room_w` / `room_h`
  // back to width_m / height_m keeps the existing UI inputs working.
  const updateRoom = useCallback(
    (field, value) => {
      const map = { room_w: "width_m", room_h: "height_m" };
      const target = map[field] || field;
      mutateRoom((r) => ({ ...r, [target]: value }));
    },
    [mutateRoom]
  );

  // Georeference: the floor-plan's georef record (lat, lon, azimuth,
  // altitude, width_m, height_m). One calibration point shared by every
  // anchor on this floor plan, so positioning error is bounded by *one*
  // survey instead of per-AP placement on a global map.
  const updateGeo = useCallback(
    (field, value) => {
      mutateFp((fp) => ({
        ...fp,
        georef: { ...(fp.georef || {}), [field]: value },
      }));
    },
    [mutateFp]
  );

  // Room dimensions (on the current room). Used by step 3.
  const updateRoomDim = useCallback(
    (field, value) => {
      mutateRoom((r) => ({ ...r, [field]: value }));
    },
    [mutateRoom]
  );

  // Floor-plan dimensions on georef.width_m / height_m. Used by step 1.
  const updateFpDim = useCallback(
    (field, value) => {
      updateGeo(field, value);
    },
    [updateGeo]
  );

  const addFloor = useCallback(() => {
    const used = new Set((layout.floor_plans || []).map((fp) => fp.id));
    let i = 1;
    let id = `fp-${String(i).padStart(2, "0")}`;
    while (used.has(id)) {
      i += 1;
      id = `fp-${String(i).padStart(2, "0")}`;
    }
    const newFp = {
      id,
      label: `Floor ${i}`,
      image: null,
      georef: {
        latitude: 0,
        longitude: 0,
        azimuth_deg: 0,
        altitude_m: 0,
        width_m: 0,
        height_m: 0,
      },
    };
    history.commit((l) => ({ ...l, floor_plans: [...(l.floor_plans || []), newFp] }));
    setSelectedFpId(id);
    setFloorEngaged(true);
  }, [layout.floor_plans, history]);

  // Removing a floor plan. Blocked if any rooms are attached - the operator
  // must move those rooms to another floor (or delete them) first. Orphan
  // rooms would otherwise leak through into step 2 with no obvious owner
  // and confuse the room→floor assignment flow.
  const removeFloor = useCallback(
    (id) => {
      const rooms = (layout.rooms || []).filter((r) => r.floor_plan_id === id);
      if (rooms.length > 0) return false;
      history.commit((l) => ({
        ...l,
        floor_plans: (l.floor_plans || []).filter((fp) => fp.id !== id),
      }));
      if (selectedFpId === id) {
        const remaining = (layout.floor_plans || []).filter((fp) => fp.id !== id);
        setSelectedFpId(remaining[0]?.id || null);
        setFloorEngaged(false);
      }
      return true;
    },
    [history, layout.floor_plans, layout.rooms, selectedFpId]
  );

  const addRoom = useCallback(() => {
    if (!currentFp) return;
    const usedIds = new Set((layout.rooms || []).map((r) => r.id));
    let i = 1;
    let id = `room-${String(i).padStart(2, "0")}`;
    while (usedIds.has(id)) {
      i += 1;
      id = `room-${String(i).padStart(2, "0")}`;
    }
    const fpW = Number(currentFp.georef?.width_m) || 50;
    const fpH = Number(currentFp.georef?.height_m) || 50;
    const newRoom = {
      id,
      label: `Room ${i}`,
      floor_plan_id: currentFp.id,
      x_m: snap(fpW / 4, DEFAULT_SNAP_M),
      y_m: snap(fpH / 4, DEFAULT_SNAP_M),
      width_m: Math.min(10, fpW / 2),
      height_m: Math.min(10, fpH / 2),
      rotation_deg: 0,
      anchors: [],
      walls: [],
    };
    history.commit((l) => ({ ...l, rooms: [...(l.rooms || []), newRoom] }));
    setSelectedRoomId(id);
  }, [currentFp, layout.rooms, history]);

  const removeRoom = useCallback(
    (id) => {
      history.commit((l) => ({ ...l, rooms: (l.rooms || []).filter((r) => r.id !== id) }));
      if (selectedRoomId === id) {
        const remaining = (layout.rooms || []).filter((r) => r.id !== id);
        setSelectedRoomId(remaining[0]?.id || null);
      }
    },
    [history, layout.rooms, selectedRoomId]
  );

  // Rescale the entire floor plan (and everything inside it) by a uniform
  // factor so that the named room ends up at the given target dimensions.
  // Used when the operator knows a room's real-world size precisely (e.g.
  // measured with a tape) and wants to correct the floor-plan scale that
  // calibration left slightly off.
  //
  // Coordinates and footprint metres scale; physical-property metres don't:
  //   scaled - floor_plan.width_m/height_m, room.x_m/y_m/width_m/height_m,
  //            room.shape vertex coords, anchor.x/y, wall.x1/y1/x2/y2
  //   kept   - anchor.height_m (real mounting height), anchor.coverage_m
  //            (real coverage radius), wall.thickness, room.rotation_deg,
  //            georef.latitude/longitude/azimuth_deg (the calibration anchor
  //            point, NOT the scale)
  // Uniform-scale rescale of a whole floor plan. Used by the section 2
  // scale-calibration tool (averaged from N reference measurements).
  //
  // Coordinates and footprint metres scale; physical-property metres don't:
  //   scaled - floor_plan.width_m/height_m, room.x_m/y_m/width_m/height_m,
  //            room.shape vertex coords, anchor.x/y, wall.x1/y1/x2/y2,
  //            scale_calibration_refs[].p1/p2 (so they stay anchored to the
  //            same physical features on the image as the plan rescales)
  //   kept   - anchor.height_m (real mounting height), anchor.coverage_m
  //            (real coverage radius), wall.thickness, room.rotation_deg,
  //            georef.latitude/longitude/azimuth_deg, scale_calibration_refs[].knownM
  //
  // When `newRefs` is provided, the floor plan's stored refs are REPLACED
  // (then scaled). When null, existing refs are scaled in place. Callers in
  // the calibration apply path pass `newRefs = scaleCal.refs` so the session's
  // add/remove edits land alongside the scale correction in a single commit.
  const rescaleFloorPlan = useCallback(
    (fpId, s, newRefs = null) => {
      if (!fpId || !(s > 0)) return;
      history.commit((l) => ({
        ...l,
        floor_plans: (l.floor_plans || []).map((fp) => {
          if (fp.id !== fpId) return fp;
          const refSource = newRefs ?? fp.scale_calibration_refs ?? [];
          const scaledRefs = refSource.map(({ id, p1, p2, knownM }) => ({
            id,
            p1: [p1[0] * s, p1[1] * s],
            p2: [p2[0] * s, p2[1] * s],
            knownM,
          }));
          return {
            ...fp,
            georef: {
              ...(fp.georef || {}),
              width_m: (Number(fp.georef?.width_m) || 0) * s,
              height_m: (Number(fp.georef?.height_m) || 0) * s,
            },
            scale_calibration_refs: scaledRefs,
          };
        }),
        rooms: (l.rooms || []).map((r) => {
          if (r.floor_plan_id !== fpId) return r;
          const scaled = {
            ...r,
            x_m: Number(r.x_m) * s,
            y_m: Number(r.y_m) * s,
            width_m: Number(r.width_m) * s,
            height_m: Number(r.height_m) * s,
            anchors: (r.anchors || []).map((a) => ({
              ...a,
              x: Number(a.x) * s,
              y: Number(a.y) * s,
            })),
            walls: (r.walls || []).map((w) => ({
              ...w,
              x1: Number(w.x1) * s,
              y1: Number(w.y1) * s,
              x2: Number(w.x2) * s,
              y2: Number(w.y2) * s,
            })),
          };
          if (Array.isArray(r.shape)) {
            scaled.shape = r.shape.map(([x, y]) => [x * s, y * s]);
          }
          return scaled;
        }),
      }));
    },
    [history]
  );

  const updateAp = useCallback(
    (id, fields) => {
      mutateRoom((r) => ({
        ...r,
        anchors: (r.anchors || []).map((a) => (a.id === id ? { ...a, ...fields } : a)),
      }));
    },
    [mutateRoom]
  );

  const renameAp = useCallback(
    (oldId, newId) => {
      mutateRoom((r) => ({
        ...r,
        anchors: (r.anchors || []).map((a) => (a.id === oldId ? { ...a, id: newId } : a)),
      }));
      if (selectedApId === oldId) selectAp(newId);
    },
    [mutateRoom, selectedApId]
  );

  const addAnchor = useCallback(
    (tech = DEFAULT_TECH) => {
      const meta = techMeta(tech);
      const id = nextApId(aps);
      mutateRoom((r) => {
        const anchor = {
          id,
          technology: tech,
          x: snap((r.width_m || 10) / 2, snapEnabled ? DEFAULT_SNAP_M : 0),
          y: snap((r.height_m || 10) / 2, snapEnabled ? DEFAULT_SNAP_M : 0),
          height_m: meta.default_height_m,
          coverage_m: meta.default_coverage_m,
          vendor: "",
          model: "",
        };
        // No invented RF defaults: vendor/model/band/channel/tx are left unset
        // and only filled if the operator types them, or derived by calibration.
        return { ...r, anchors: [...(r.anchors || []), anchor] };
      });
      selectAp(id);
    },
    [aps, mutateRoom, snapEnabled]
  );

  const removeAp = useCallback(
    (id) => {
      mutateRoom((r) => ({ ...r, anchors: (r.anchors || []).filter((a) => a.id !== id) }));
      if (selectedApId === id) selectAp(null);
    },
    [mutateRoom, selectedApId]
  );

  // --- Wall mutations ---

  const updateWall = useCallback(
    (id, fields) => {
      mutateRoom((r) => ({
        ...r,
        walls: (r.walls || []).map((w) => (w.id === id ? { ...w, ...fields } : w)),
      }));
    },
    [mutateRoom]
  );

  const renameWall = useCallback(
    (oldId, newId) => {
      mutateRoom((r) => ({
        ...r,
        walls: (r.walls || []).map((w) => (w.id === oldId ? { ...w, id: newId } : w)),
      }));
      if (selectedWallId === oldId) selectWall(newId);
    },
    [mutateRoom, selectedWallId]
  );

  const removeWall = useCallback(
    (id) => {
      mutateRoom((r) => ({ ...r, walls: (r.walls || []).filter((w) => w.id !== id) }));
      if (selectedWallId === id) selectWall(null);
    },
    [mutateRoom, selectedWallId]
  );

  // Openings are cut-outs along a wall: door / window / pass-through. Each
  // opening lives in wall-local 1-D space - `start_m` and `end_m` are
  // distances along the wall from its (x1, y1) endpoint. `height_m` +
  // `sill_m` give the vertical extent (sill = bottom offset from floor, so
  // a door has sill 0 and a window has sill ~1 m).
  const addOpening = useCallback(
    (wallId, opening) => {
      mutateRoom((r) => ({
        ...r,
        walls: (r.walls || []).map((w) =>
          w.id === wallId
            ? { ...w, openings: [...(w.openings || []), opening] }
            : w
        ),
      }));
    },
    [mutateRoom]
  );

  const updateOpening = useCallback(
    (wallId, openingId, fields) => {
      mutateRoom((r) => ({
        ...r,
        walls: (r.walls || []).map((w) =>
          w.id !== wallId
            ? w
            : {
                ...w,
                openings: (w.openings || []).map((o) =>
                  o.id === openingId ? { ...o, ...fields } : o
                ),
              }
        ),
      }));
    },
    [mutateRoom]
  );

  const removeOpening = useCallback(
    (wallId, openingId) => {
      mutateRoom((r) => ({
        ...r,
        walls: (r.walls || []).map((w) =>
          w.id !== wallId
            ? w
            : {
                ...w,
                openings: (w.openings || []).filter((o) => o.id !== openingId),
              }
        ),
      }));
    },
    [mutateRoom]
  );

  // Perimeter openings: doors / corridor stubs on the auto-derived room
  // perimeter (N/E/S/W). Stored on the room itself because the perimeter
  // isn't an explicit wall in the schema; the 3D scene + downstream
  // consumers derive the four sides from width_m / height_m and split them
  // around these openings.
  const addPerimeterOpening = useCallback(
    (opening) => {
      mutateRoom((r) => ({
        ...r,
        perimeter_openings: [...(r.perimeter_openings || []), opening],
      }));
    },
    [mutateRoom]
  );

  const updatePerimeterOpening = useCallback(
    (openingId, fields) => {
      mutateRoom((r) => ({
        ...r,
        perimeter_openings: (r.perimeter_openings || []).map((o) =>
          o.id === openingId ? { ...o, ...fields } : o
        ),
      }));
    },
    [mutateRoom]
  );

  const removePerimeterOpening = useCallback(
    (openingId) => {
      mutateRoom((r) => ({
        ...r,
        perimeter_openings: (r.perimeter_openings || []).filter(
          (o) => o.id !== openingId
        ),
      }));
    },
    [mutateRoom]
  );

  const commitWall = useCallback(
    (x1, y1, x2, y2) => {
      if (Math.hypot(x2 - x1, y2 - y1) < 0.1) return;
      let createdId = null;
      mutateRoom((r) => {
        const id = nextWallId(r.walls || []);
        createdId = id;
        return {
          ...r,
          walls: [
            ...(r.walls || []),
            { id, x1, y1, x2, y2, thickness: DEFAULT_WALL_THICKNESS_M },
          ],
        };
      });
      if (createdId) selectWall(createdId);
    },
    [mutateRoom]
  );

  // Commit four walls forming an axis-aligned rectangle in one mutation
  // → one undo step. The operator uses this to carve a sub-room (office,
  // server closet, lab annex) inside the area without drawing four walls
  // one at a time. The four walls are independent records so each can be
  // edited, deleted, or have its own openings later.
  const commitBoxRoom = useCallback(
    (x1, y1, x2, y2) => {
      const minX = Math.min(x1, x2);
      const minY = Math.min(y1, y2);
      const maxX = Math.max(x1, x2);
      const maxY = Math.max(y1, y2);
      if (maxX - minX < 0.2 || maxY - minY < 0.2) return;
      mutateRoom((r) => {
        const existing = [...(r.walls || [])];
        const sides = [
          { x1: minX, y1: minY, x2: maxX, y2: minY }, // top
          { x1: maxX, y1: minY, x2: maxX, y2: maxY }, // right
          { x1: maxX, y1: maxY, x2: minX, y2: maxY }, // bottom
          { x1: minX, y1: maxY, x2: minX, y2: minY }, // left
        ];
        for (const side of sides) {
          const id = nextWallId(existing);
          existing.push({
            id,
            x1: +side.x1.toFixed(2),
            y1: +side.y1.toFixed(2),
            x2: +side.x2.toFixed(2),
            y2: +side.y2.toFixed(2),
            thickness: DEFAULT_WALL_THICKNESS_M,
          });
        }
        return { ...r, walls: existing };
      });
    },
    [mutateRoom]
  );

  // --- Drag ---

  function clientToWorld(evt) {
    const svg = svgRef.current;
    if (!svg) return null;
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const local = pt.matrixTransform(ctm.inverse());
    return { x: local.x, y: local.y };
  }

  function onApPointerDown(evt, ap) {
    // Select-then-unlock-then-drag. Clicking an unselected anchor just
    // selects it. The drag only fires once the operator has explicitly
    // unlocked the selection via the panel's edit toggle. UWB anchor
    // positions must not drift under stray clicks.
    if (ap.id !== selectedApId) {
      evt.stopPropagation();
      selectAp(ap.id);
      return;
    }
    if (!editUnlocked) {
      evt.stopPropagation();
      return;
    }
    evt.target.setPointerCapture(evt.pointerId);
    const world = clientToWorld(evt);
    if (!world) return;
    dragRef.current = {
      id: ap.id,
      offsetX: ap.x - world.x,
      offsetY: ap.y - world.y,
      moved: false,
    };
    history.beginTransient();
  }

  function onApPointerMove(evt) {
    const drag = dragRef.current;
    if (!drag) return;
    const world = clientToWorld(evt);
    if (!world) return;
    const rawX = world.x + drag.offsetX;
    const rawY = world.y + drag.offsetY;
    const useSnap = snapEnabled && !evt.altKey;
    const step = useSnap ? DEFAULT_SNAP_M : NUDGE_SMALL;
    const x = +snap(rawX, step).toFixed(2);
    const y = +snap(rawY, step).toFixed(2);
    drag.moved = true;
    const roomId = currentRoom?.id ?? selectedRoomId;
    history.applyTransient((l) => ({
      ...l,
      rooms: (l.rooms || []).map((r) =>
        r.id !== roomId
          ? r
          : {
              ...r,
              anchors: (r.anchors || []).map((a) =>
                a.id === drag.id ? { ...a, x, y } : a
              ),
            }
      ),
    }));
  }

  function onApPointerUp() {
    if (!dragRef.current) return;
    history.endTransient();
    dragRef.current = null;
  }

  // --- Wall endpoint drag (select tool only) ---

  function onWallEndpointPointerDown(evt, wall, which) {
    // Endpoint handles render only when the wall is already selected, so
    // the select-first half of the gate is implicit. We still require the
    // unlock so endpoint drag matches the rest of the canvas.
    if (!editUnlocked) {
      evt.stopPropagation();
      return;
    }
    evt.target.setPointerCapture(evt.pointerId);
    evt.stopPropagation();
    selectWall(wall.id);
    dragRef.current = { kind: "wall-endpoint", id: wall.id, which };
    history.beginTransient();
  }

  function onWallEndpointPointerMove(evt) {
    const drag = dragRef.current;
    if (!drag || drag.kind !== "wall-endpoint") return;
    const world = clientToWorld(evt);
    if (!world) return;
    const useSnap = snapEnabled && !evt.altKey;
    const step = useSnap ? DEFAULT_SNAP_M : NUDGE_SMALL;
    const x = +snap(world.x, step).toFixed(2);
    const y = +snap(world.y, step).toFixed(2);
    const roomId = currentRoom?.id ?? selectedRoomId;
    history.applyTransient((l) => ({
      ...l,
      rooms: (l.rooms || []).map((r) =>
        r.id !== roomId
          ? r
          : {
              ...r,
              walls: (r.walls || []).map((w) =>
                w.id !== drag.id
                  ? w
                  : drag.which === "start"
                  ? { ...w, x1: x, y1: y }
                  : { ...w, x2: x, y2: y }
              ),
            }
      ),
    }));
  }

  // Wall body drag - translates both endpoints by the same delta, so the
  // wall keeps its length and orientation. Only fires after the wall is
  // already selected, same click-first-then-drag pattern as anchors. Snap
  // applies to the DELTA, not the endpoints, so the wall doesn't morph
  // into half-grid increments.
  function onWallBodyPointerDown(evt, wall) {
    if (tool !== "select") return;
    evt.stopPropagation();
    if (wall.id !== selectedWallId) {
      selectWall(wall.id);
      return;
    }
    if (!editUnlocked) return;
    evt.target.setPointerCapture?.(evt.pointerId);
    const world = clientToWorld(evt);
    if (!world) return;
    dragRef.current = {
      kind: "wall-body",
      id: wall.id,
      grabX: world.x,
      grabY: world.y,
      startX1: wall.x1,
      startY1: wall.y1,
      startX2: wall.x2,
      startY2: wall.y2,
    };
    history.beginTransient();
  }

  function onWallBodyPointerMove(evt) {
    const drag = dragRef.current;
    if (!drag || drag.kind !== "wall-body") return;
    const world = clientToWorld(evt);
    if (!world) return;
    const useSnap = snapEnabled && !evt.altKey;
    const step = useSnap ? DEFAULT_SNAP_M : NUDGE_SMALL;
    const dx = +snap(world.x - drag.grabX, step).toFixed(2);
    const dy = +snap(world.y - drag.grabY, step).toFixed(2);
    const roomId = currentRoom?.id ?? selectedRoomId;
    history.applyTransient((l) => ({
      ...l,
      rooms: (l.rooms || []).map((r) =>
        r.id !== roomId
          ? r
          : {
              ...r,
              walls: (r.walls || []).map((w) =>
                w.id !== drag.id
                  ? w
                  : {
                      ...w,
                      x1: +(drag.startX1 + dx).toFixed(2),
                      y1: +(drag.startY1 + dy).toFixed(2),
                      x2: +(drag.startX2 + dx).toFixed(2),
                      y2: +(drag.startY2 + dy).toFixed(2),
                    }
              ),
            }
      ),
    }));
  }

  // --- Canvas pointer-down: tool-aware ---

  function onCanvasPointerDown(evt) {
    if (evt.target !== svgRef.current) return; // clicked something else
    if (tool === "select") {
      setSelection(null);
      return;
    }
    const world = clientToWorld(evt);
    if (!world) return;
    const useSnap = snapEnabled && !evt.altKey;
    const step = useSnap ? DEFAULT_SNAP_M : NUDGE_SMALL;
    const x = +snap(world.x, step).toFixed(2);
    const y = +snap(world.y, step).toFixed(2);

    if (tool === "calibrate") {
      // Hand off to the calibration panel. It opens a capture session
      // against the adapter, polls until done, refreshes the samples.
      setPendingCalibrationClick({ x_m: x, y_m: y, ts: Date.now() });
      return;
    }

    if (isAnchorTool(tool)) {
      const tech = toolTech(tool);
      const meta = techMeta(tech);
      const id = nextApId(aps);
      mutateRoom((r) => {
        const anchor = {
          id,
          technology: tech,
          x,
          y,
          height_m: meta.default_height_m,
          coverage_m: meta.default_coverage_m,
          vendor: "",
          model: "",
        };
        // No invented RF defaults (see addAnchor): only operator-typed or
        // calibration-derived RF lives on the anchor.
        return { ...r, anchors: [...(r.anchors || []), anchor] };
      });
      selectAp(id);
      setTool("select");
      return;
    }

    if (tool === "wall" || tool === "boxroom") {
      evt.target.setPointerCapture?.(evt.pointerId);
      drawRef.current = { kind: tool, x1: x, y1: y };
      setDrawingPreview({ kind: tool, x1: x, y1: y, x2: x, y2: y });
    }
  }

  function onCanvasPointerMove(evt) {
    if (dragRef.current) {
      if (dragRef.current.kind === "wall-endpoint") {
        onWallEndpointPointerMove(evt);
      } else if (dragRef.current.kind === "wall-body") {
        onWallBodyPointerMove(evt);
      } else {
        onApPointerMove(evt);
      }
      return;
    }
    const draw = drawRef.current;
    if (!draw) return;
    const world = clientToWorld(evt);
    if (!world) return;
    const useSnap = snapEnabled && !evt.altKey;
    const step = useSnap ? DEFAULT_SNAP_M : NUDGE_SMALL;
    let x = +snap(world.x, step).toFixed(2);
    let y = +snap(world.y, step).toFixed(2);
    // Shift while drawing a wall constrains its angle to 15° increments
    // from the start point - same convention as most CAD tools. Length
    // follows the cursor; angle locks.
    if (draw.kind === "wall" && evt.shiftKey) {
      const dx = x - draw.x1;
      const dy = y - draw.y1;
      const len = Math.hypot(dx, dy);
      if (len > 0.001) {
        const rawAngle = Math.atan2(dy, dx);
        const stepRad = Math.PI / 12; // 15°
        const snappedAngle = Math.round(rawAngle / stepRad) * stepRad;
        x = +(draw.x1 + len * Math.cos(snappedAngle)).toFixed(2);
        y = +(draw.y1 + len * Math.sin(snappedAngle)).toFixed(2);
      }
    }
    setDrawingPreview({ kind: draw.kind, x1: draw.x1, y1: draw.y1, x2: x, y2: y });
  }

  function onCanvasPointerUp() {
    if (dragRef.current) {
      if (dragRef.current.kind === "wall-endpoint") {
        history.endTransient();
      } else {
        history.endTransient();
      }
      dragRef.current = null;
      return;
    }
    const draw = drawRef.current;
    if (!draw) return;
    const preview = drawingPreview;
    drawRef.current = null;
    setDrawingPreview(null);
    if (!preview) return;
    if (draw.kind === "wall") commitWall(preview.x1, preview.y1, preview.x2, preview.y2);
    if (draw.kind === "boxroom") commitBoxRoom(preview.x1, preview.y1, preview.x2, preview.y2);
    setTool("select");
  }

  // --- Save ---

  // --- Export / Import (portable blueprint) ---
  //
  // The blueprint is the only output that travels between machines: from
  // the editor (where it's authored) to another cluster, another laptop
  // demo, a backup drive. It carries geometry only - no BSSIDs / MACs /
  // per-venue secrets. The cluster operator joins it to a separate
  // bindings file at deploy time (see docs/data-contracts.md).
  const onExportBlueprint = useCallback(() => {
    const payload = denormalizeForCompat(layout);
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const stamp = new Date()
      .toISOString()
      .replace(/[:.]/g, "-")
      .slice(0, 19);
    a.href = url;
    a.download = `blueprint-${stamp}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [layout]);

  const onImportBlueprint = useCallback(() => {
    importFileRef.current?.click();
  }, []);

  const onImportFileChosen = useCallback(
    async (evt) => {
      const file = evt.target.files?.[0];
      evt.target.value = ""; // allow re-picking the same file later
      if (!file) return;
      try {
        const text = await file.text();
        const parsed = JSON.parse(text);
        const normalized = normalizeLayout(parsed);
        // Commit pushes the current value onto the undo stack so Ctrl+Z
        // restores whatever was on screen before the import.
        history.commit(normalized);
      } catch (e) {
        setSaveMessage(`import failed: ${e.message || e}`);
      }
    },
    [history]
  );

  const onSave = useCallback(async () => {
    if (!isValid || !dirty || saving) return;
    setSaving(true);
    setSaveMessage(null);
    try {
      await saveLayout(denormalizeForCompat(layout));
      setSavedSnapshot(layout);
      setSaveMessage("saved");
    } catch (err) {
      setSaveMessage(`error: ${err.message}`);
    } finally {
      setSaving(false);
    }
  }, [isValid, dirty, saving, layout]);

  // Auto-save: every layout change schedules a debounced save 600 ms later.
  // The explicit SAVE button is gone - the operator finishes an action
  // (finish edit, draw, drop image) and the layout flows to disk on its own.
  // Errors still surface via the header status pill so operators can
  // recover.
  useEffect(() => {
    if (!loaded || !dirty || !isValid || saving) return;
    const t = setTimeout(() => {
      onSave();
    }, 600);
    return () => clearTimeout(t);
  }, [loaded, dirty, isValid, saving, layout, onSave]);

  // --- Keyboard ---

  useEffect(() => {
    function onKey(e) {
      const meta = e.ctrlKey || e.metaKey;
      const isTextField =
        e.target instanceof HTMLElement &&
        ["INPUT", "TEXTAREA"].includes(e.target.tagName);

      if (meta && e.key.toLowerCase() === "z" && !e.shiftKey) {
        e.preventDefault();
        history.undo();
        return;
      }
      if (meta && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) {
        e.preventDefault();
        history.redo();
        return;
      }
      if (meta && e.key.toLowerCase() === "s") {
        e.preventDefault();
        onSave();
        return;
      }

      if (isTextField) return;

      // Tool hotkeys.
      if (!meta && !e.shiftKey) {
        const k = e.key.toLowerCase();
        if (k === "v") { setTool("select"); return; }
        if (k === "w") { setTool("wall"); return; }
        // Per-technology anchor hotkeys (a=WiFi, u=UWB, g=5G, n=GNSS).
        for (const techKey of TECH_KEYS) {
          if (k === techMeta(techKey).hotkey) {
            setTool(`anchor:${techKey}`);
            return;
          }
        }
      }

      if (
        section === "room" &&
        selectedApId &&
        ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)
      ) {
        e.preventDefault();
        const step = e.shiftKey ? NUDGE_LARGE : NUDGE_SMALL;
        const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
        const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
        mutateRoom((r) => ({
          ...r,
          anchors: (r.anchors || []).map((a) =>
            a.id === selectedApId
              ? { ...a, x: +(a.x + dx).toFixed(2), y: +(a.y + dy).toFixed(2) }
              : a
          ),
        }));
        return;
      }

      // Plan section: arrow keys nudge the selected ROOM's BL position by
      // 0.1 m (or 1 m with Shift) when no input field has focus AND the
      // room is in edit mode. The mode gate matches the canvas drag-to-move
      // behaviour - view mode is hands-off, edit mode allows precise nudge.
      if (
        section === "plan" &&
        currentRoom &&
        editingRoomId === currentRoom.id &&
        ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)
      ) {
        e.preventDefault();
        const step = e.shiftKey ? NUDGE_LARGE : NUDGE_SMALL;
        const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
        const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
        mutateRoom((r) => ({
          ...r,
          x_m: +(Number(r.x_m) + dx).toFixed(2),
          y_m: +(Number(r.y_m) + dy).toFixed(2),
        }));
        return;
      }

      if (selectedApId && (e.key === "Delete" || e.key === "Backspace")) {
        e.preventDefault();
        removeAp(selectedApId);
        return;
      }
      if (selectedWallId && (e.key === "Delete" || e.key === "Backspace")) {
        e.preventDefault();
        removeWall(selectedWallId);
        return;
      }
      if (e.key === "Escape") {
        // Section 2/3 edit-mode exit takes precedence over the global
        // tool/selection reset - the operator clearly intended to "stop
        // editing this room/anchors", not to clear unrelated state.
        if (section === "plan" && editingRoomId) {
          setEditingRoomId(null);
          return;
        }
        setTool("select");
        setSelection(null);
        drawRef.current = null;
        setDrawingPreview(null);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [history, selectedApId, selectedWallId, onSave, removeAp, removeWall, section, currentRoom, editingRoomId, mutateRoom]);

  // --- beforeunload guard ---

  useEffect(() => {
    if (!dirty) return;
    function handler(e) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  // Block ctrl/cmd + wheel from zooming the page when the cursor is over
  // the room canvas. The canvas content is fixed-scale; there is nothing
  // to zoom INTO at the page level, so the browser's pinch-zoom only
  // pushes the toolbar / sidebar out of position and irritates the user.
  // Listener is attached non-passive (default React onWheel is passive
  // and cannot preventDefault).
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    function onWheel(e) {
      if (e.ctrlKey || e.metaKey) e.preventDefault();
    }
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [section]);

  // --- Render ---

  if (loadError)
    return <div style={{ ...shell, padding: 24, color: "#ff6b78" }}>{loadError}</div>;
  if (!loaded)
    return <div style={{ ...shell, padding: 24, color: "#7a8aab" }}>Loading…</div>;

  const w = Number(currentRoom?.width_m) || 10;
  const h = Number(currentRoom?.height_m) || 10;
  const vb = `${-MARGIN_M} ${-MARGIN_M} ${w + 2 * MARGIN_M} ${h + 2 * MARGIN_M}`;

  const apIdInvalid = (ap) => errorByField.has(`ap:${ap.id}`);

  return (
    <div style={shell}>
      <header style={header}>
        <h2
          style={{
            margin: 0,
            fontSize: 14,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          Placement Editor
        </h2>
        <span style={{ color: "#7a8aab", fontSize: 11, letterSpacing: "0.08em" }}>
          · ⌘Z undo · ⌘S save · Esc cancel · V select · W wall · A/U/G/N tech
        </span>
        <div
          style={{
            marginLeft: 16,
            display: "inline-flex",
            borderRadius: 6,
            border: "1px solid rgba(58,130,255,0.4)",
            overflow: "hidden",
          }}
        >
          {[
            ["world", "① World"],
            ["plan", "② Plan"],
            ["room", "③ Room"],
          ].map(([key, label]) => (
            <button
              key={key}
              onClick={() => setSection(key)}
              style={{
                padding: "6px 14px",
                fontSize: 11,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                fontFamily: "ui-monospace, monospace",
                background: section === key ? "rgba(58,130,255,0.25)" : "transparent",
                color: section === key ? "#cce0ff" : "#7a8aab",
                border: "none",
                cursor: "pointer",
                fontWeight: section === key ? 600 : 400,
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          <button
            style={btn("ghost", !history.canUndo)}
            onClick={() => history.undo()}
            disabled={!history.canUndo}
            title="Undo (Ctrl+Z)"
          >
            ↶ undo
          </button>
          <button
            style={btn("ghost", !history.canRedo)}
            onClick={() => history.redo()}
            disabled={!history.canRedo}
            title="Redo (Ctrl+Shift+Z)"
          >
            ↷ redo
          </button>
          <button
            style={btn("ghost")}
            onClick={onExportBlueprint}
            title="Download the current layout as a portable JSON blueprint. Use this to move the building config between clusters, share with another operator, or back it up locally. The blueprint contains geometry only - no BSSIDs, MACs, or per-venue secrets."
          >
            ↓ export
          </button>
          <button
            style={btn("ghost")}
            onClick={onImportBlueprint}
            title="Replace the current layout with a previously-exported blueprint JSON. The current edits are pushed to undo history so Ctrl+Z restores them."
          >
            ↑ import
          </button>
          <input
            ref={importFileRef}
            type="file"
            accept="application/json,.json"
            style={{ display: "none" }}
            onChange={onImportFileChosen}
          />
          <label
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: 11,
              color: "#7a8aab",
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              fontFamily: "ui-monospace, monospace",
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={snapEnabled}
              onChange={(e) => setSnapEnabled(e.target.checked)}
            />
            snap 0.5m
          </label>
          <label
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: 11,
              color: "#7a8aab",
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              fontFamily: "ui-monospace, monospace",
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={showGrid}
              onChange={(e) => setShowGrid(e.target.checked)}
            />
            grid 1m
          </label>
          {/* Auto-save status pill - the explicit "save" button is gone,
              changes flow to disk after every committed action. */}
          {!isValid ? (
            <span
              title={errors.map((e) => e.message).join("\n")}
              style={{
                color: "#ff6b78",
                fontSize: 11,
                fontFamily: "ui-monospace, monospace",
              }}
            >
              {errors.length} err · not saving
            </span>
          ) : saving ? (
            <span
              style={{
                color: "#ffb347",
                fontSize: 11,
                fontFamily: "ui-monospace, monospace",
              }}
            >
              saving…
            </span>
          ) : dirty ? (
            <span
              style={{
                color: "#ffb347",
                fontSize: 11,
                fontFamily: "ui-monospace, monospace",
              }}
            >
              unsaved
            </span>
          ) : (
            <span
              style={{
                color: "#5dffb0",
                fontSize: 11,
                fontFamily: "ui-monospace, monospace",
              }}
            >
              {saveMessage || "saved"}
            </span>
          )}
        </div>
      </header>

      <aside style={sidebar}>
        {section === "world" && (
          <div style={{ fontSize: 11, color: "#7a8aab", padding: "0 4px 12px", lineHeight: 1.4 }}>
            <strong style={{ color: "#cce0ff", letterSpacing: "0.06em", textTransform: "uppercase", fontSize: 10 }}>
              Step 1 · floor footprint on the map
            </strong>
            <div style={{ marginTop: 6 }}>
              Pick a floor from the list - or add one. Each floor gets its
              own georeference. Rooms (step 2) and anchors (step 3) live
              inside the engaged floor.
            </div>
          </div>
        )}
        {section === "world" && (
          <>
        <h3 style={sectionTitle}>Floor plans · {(layout.floor_plans || []).length}</h3>
        {(layout.floor_plans || []).length === 0 && (
          <div style={{ fontSize: 11, color: "#7a8aab", padding: "0 4px 6px", fontStyle: "italic", lineHeight: 1.4 }}>
            No floor plans yet. Add one to start.
          </div>
        )}
        {(layout.floor_plans || []).map((fp) => {
          const sel = fp.id === selectedFpId && floorEngaged;
          const hasGeo = Number(fp.georef?.latitude) && Number(fp.georef?.longitude);
          const w = Number(fp.georef?.width_m) || 0;
          const h = Number(fp.georef?.height_m) || 0;
          const roomCount = (layout.rooms || []).filter((r) => r.floor_plan_id === fp.id).length;
          const confirming = confirmDeleteFpId === fp.id;
          const canDelete = roomCount === 0;
          return (
            <div
              key={fp.id}
              style={{
                marginBottom: 6,
                borderRadius: 6,
                border: `1px solid ${sel ? "#5dffb088" : "rgba(255,255,255,0.08)"}`,
                background: sel ? "rgba(93,255,176,0.06)" : "rgba(255,255,255,0.02)",
                fontFamily: "ui-monospace, monospace",
                overflow: "hidden",
              }}
            >
              <div
                onClick={() => {
                  if (confirming) return;
                  setSelectedFpId(fp.id);
                  setFloorEngaged(true);
                  if (hasGeo) {
                    georefRef.current?.flyTo(
                      Number(fp.georef.latitude),
                      Number(fp.georef.longitude),
                      19
                    );
                  }
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "9px 10px",
                  cursor: confirming ? "default" : "pointer",
                }}
              >
                <div style={{ flex: 1, overflow: "hidden" }}>
                  <div
                    style={{
                      color: sel ? "#aaffd6" : "#cce0ff",
                      fontWeight: 600,
                      fontSize: 13,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {fp.label || fp.id}
                  </div>
                  <div style={{ color: "#7a8aab", fontSize: 10, marginTop: 2 }}>
                    {w > 0 && h > 0 ? `${w.toFixed(1)}×${h.toFixed(1)} m` : fp.image?.data_url ? "image" : "empty"}
                    {" · "}
                    {roomCount} room{roomCount === 1 ? "" : "s"}
                  </div>
                  {fp.georef?.calibrated_against && (
                    <div style={{ color: "#5dffb0", fontSize: 9, marginTop: 2, opacity: 0.8 }}>
                      cal vs {fp.georef.calibrated_against}
                      {fp.georef.calibration_points >= 3 &&
                        ` · ${fp.georef.calibration_points}pt · rms ${fp.georef.calibration_rms_m}m`}
                      {fp.georef.calibration_points === 2 && " · 2pt (exact)"}
                    </div>
                  )}
                </div>
                {!confirming && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirmDeleteFpId(fp.id);
                    }}
                    title="Remove this floor plan"
                    style={{
                      padding: "4px 6px",
                      background: "transparent",
                      color: "#7a8aab",
                      border: "none",
                      borderRadius: 4,
                      fontSize: 14,
                      cursor: "pointer",
                      fontFamily: "ui-monospace, monospace",
                      opacity: 0.6,
                    }}
                  >
                    🗑
                  </button>
                )}
              </div>
              {confirming && (
                <div
                  style={{
                    padding: "8px 10px",
                    borderTop: "1px solid rgba(255,107,120,0.3)",
                    background: "rgba(255,107,120,0.06)",
                    fontSize: 11,
                  }}
                >
                  {canDelete ? (
                    <>
                      <div style={{ color: "#cce0ff", marginBottom: 6 }}>
                        Remove this floor plan?
                      </div>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button
                          type="button"
                          onClick={() => {
                            removeFloor(fp.id);
                            setConfirmDeleteFpId(null);
                          }}
                          style={{
                            flex: 1,
                            padding: "5px 8px",
                            background: "rgba(255,107,120,0.2)",
                            color: "#ff6b78",
                            border: "1px solid #ff6b7888",
                            borderRadius: 4,
                            fontSize: 11,
                            letterSpacing: "0.06em",
                            textTransform: "uppercase",
                            fontFamily: "ui-monospace, monospace",
                            cursor: "pointer",
                          }}
                        >
                          delete
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteFpId(null)}
                          style={{
                            flex: 1,
                            padding: "5px 8px",
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
                          cancel
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div style={{ color: "#ffb347", marginBottom: 6, lineHeight: 1.4 }}>
                        Can't remove: {roomCount} room{roomCount === 1 ? "" : "s"} attached.
                        Reassign or delete them in step 2 first.
                      </div>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteFpId(null)}
                        style={{
                          width: "100%",
                          padding: "5px 8px",
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
                        ok
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
        <button
          type="button"
          onClick={addFloor}
          style={{
            width: "100%",
            marginTop: 4,
            padding: "7px 10px",
            background: "transparent",
            color: "#9ec3ff",
            border: "1px dashed rgba(58,130,255,0.4)",
            borderRadius: 6,
            fontSize: 11,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            fontFamily: "ui-monospace, monospace",
            cursor: "pointer",
          }}
        >
          + add floor plan
        </button>

        {!floorEngaged || !currentFp ? (
          <div style={{ fontSize: 11, color: "#7a8aab", padding: "14px 4px 6px", fontStyle: "italic", lineHeight: 1.4 }}>
            Pick a floor above to edit it - or click the area on the map.
          </div>
        ) : (
          <>
        <h3 style={sectionTitle}>Name</h3>
        <div style={{ fontSize: 10, color: "#7a8aab", padding: "0 4px 6px", lineHeight: 1.4 }}>
          What to call this floor in the sidebar list, room selector, and any
          downstream consumer (positioning-demo, configs).
        </div>
        <div style={{ padding: "0 4px 8px" }}>
          <TextInput
            value={currentFp?.label || ""}
            onCommit={(v) => mutateFp((fp) => ({ ...fp, label: v }))}
            placeholder="e.g. Electrum - floor 5"
          />
        </div>
        <h3 style={sectionTitle}>Reference image</h3>
        <div style={{ fontSize: 10, color: "#7a8aab", padding: "0 4px 6px", lineHeight: 1.4 }}>
          Optional architectural drawing of the floor, dropped on the map at
          real-world scale.
        </div>
        <FloorPlanImageInput
          value={currentFp?.image}
          onOpacityDragStart={() => {
            opacityDragRef.current = true;
            history.beginTransient();
          }}
          onOpacityDragEnd={() => {
            if (!opacityDragRef.current) return;
            opacityDragRef.current = false;
            history.endTransient();
          }}
          onChange={(image) => {
            if (!image) {
              mutateFp((fp) => ({ ...fp, image: null }));
              return;
            }
            // Opacity-only edit: same pixels, different alpha. Skip the
            // image-load + georef recompute so size/position the operator
            // already set survive the slider drag.
            if (currentFp?.image?.data_url === image.data_url) {
              const fpId = currentFp?.id ?? selectedFpId;
              const patch = (l) => ({
                ...l,
                floor_plans: (l.floor_plans || []).map((fp) =>
                  fp.id === fpId ? { ...fp, image } : fp
                ),
              });
              // Slider drag: keep the whole gesture as one undo step. The
              // begin/end transient bookends are wired on pointer-down/up.
              if (opacityDragRef.current) history.applyTransient(patch);
              else history.commit(patch);
              return;
            }
            // The image *is* the area. Its real-world footprint must follow
            // the image's pixel aspect ratio - squishing a rectangular floor
            // plan into a pre-existing 13×32 m box is exactly what we don't
            // want. Always overwrite width_m / height_m on upload so the
            // image is laid out at its native aspect (longest side 30 m).
            const centre = georefRef.current?.getMapCentre();
            const img = new Image();
            img.onload = () => {
              const w = img.naturalWidth || 1;
              const h = img.naturalHeight || 1;
              const longSideM = 30;
              const widthM = w >= h ? longSideM : longSideM * (w / h);
              const heightM = h >= w ? longSideM : longSideM * (h / w);
              mutateFp((fp) => ({
                ...fp,
                image,
                georef: {
                  ...(fp.georef || {}),
                  latitude: centre?.lat ?? fp.georef?.latitude ?? 0,
                  longitude: centre?.lng ?? fp.georef?.longitude ?? 0,
                  width_m: Number(widthM.toFixed(2)),
                  height_m: Number(heightM.toFixed(2)),
                },
              }));
              setFloorEngaged(true);
            };
            img.onerror = () => {
              mutateFp((fp) => ({
                ...fp,
                image,
                georef: {
                  ...(fp.georef || {}),
                  latitude: centre?.lat ?? fp.georef?.latitude ?? 0,
                  longitude: centre?.lng ?? fp.georef?.longitude ?? 0,
                  width_m: 30,
                  height_m: 30,
                },
              }));
              setFloorEngaged(true);
            };
            img.src = image.data_url;
          }}
        />
        <h3 style={sectionTitle}>Floor size (metres)</h3>
        <div style={{ fontSize: 10, color: "#7a8aab", padding: "0 4px 6px", lineHeight: 1.4 }}>
          {currentFp?.image?.data_url
            ? "Derived from the uploaded image's aspect ratio. Adjust by re-uploading at a different real-world scale."
            : "Real-world footprint of the building / floor. Rooms are placed inside this in step 2."}
        </div>
        <div style={field}>
          <span style={label}>width</span>
          <NumberInput
            value={Number(currentFp?.georef?.width_m ?? 0)}
            min={0.5}
            step="0.5"
            onCommit={(v) => updateFpDim("width_m", v)}
          />
        </div>
        <div style={field}>
          <span style={label}>height</span>
          <NumberInput
            value={Number(currentFp?.georef?.height_m ?? 0)}
            min={0.5}
            step="0.5"
            onCommit={(v) => updateFpDim("height_m", v)}
          />
        </div>
        {!currentFp?.image?.data_url && !(
          Number(currentFp?.georef?.width_m) > 0 &&
          Number(currentFp?.georef?.height_m) > 0
        ) ? (
          <button
            type="button"
            onClick={() => georefRef.current?.drawRectangle()}
            title="Draw a 20×20 m rectangle at the current map centre. Resize from the corners after."
            style={{
              marginTop: 6,
              width: "100%",
              padding: "6px 10px",
              background: "rgba(93,255,176,0.12)",
              color: "#5dffb0",
              border: "1px solid #5dffb055",
              borderRadius: 4,
              fontSize: 11,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              fontFamily: "ui-monospace, monospace",
              cursor: "pointer",
            }}
          >
            ▢ draw rectangle on map
          </button>
        ) : (
          <button
            type="button"
            onClick={() =>
              mutateFp((fp) => ({
                ...fp,
                image: null,
                georef: { ...(fp.georef || {}), width_m: 0, height_m: 0 },
              }))
            }
            title="Reset the area definition (drops image + clears dimensions). Lat/lon/azimuth stay."
            style={{
              marginTop: 6,
              width: "100%",
              padding: "6px 10px",
              background: "transparent",
              color: "#ff6b78",
              border: "1px solid rgba(255,107,120,0.4)",
              borderRadius: 4,
              fontSize: 11,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              fontFamily: "ui-monospace, monospace",
              cursor: "pointer",
            }}
          >
            ✕ clear area
          </button>
        )}

        <h3 style={sectionTitle}>Georeference</h3>
        <div style={{ fontSize: 10, color: "#7a8aab", padding: "0 4px 6px", lineHeight: 1.4 }}>
          Where the area's lower-left corner sits in the world, plus its
          bearing. Calibrated once - every room and anchor below inherits this
          anchor point.
        </div>
        <div style={field}>
          <span style={label}>lat</span>
          <NumberInput
            value={Number(currentFp?.georef?.latitude ?? 0)}
            step="0.000001"
            onCommit={(v) => updateGeo("latitude", v)}
          />
        </div>
        <div style={field}>
          <span style={label}>lon</span>
          <NumberInput
            value={Number(currentFp?.georef?.longitude ?? 0)}
            step="0.000001"
            onCommit={(v) => updateGeo("longitude", v)}
          />
        </div>
        <div style={field}>
          <span style={label}>azimuth°</span>
          <NumberInput
            value={Number(currentFp?.georef?.azimuth_deg ?? 0)}
            step="0.5"
            onCommit={(v) => updateGeo("azimuth_deg", v)}
          />
        </div>
        <div style={field}>
          <span style={label}>altitude m</span>
          <NumberInput
            value={Number(currentFp?.georef?.altitude_m ?? 0)}
            step="0.5"
            onCommit={(v) => updateGeo("altitude_m", v)}
          />
        </div>
          </>
        )}
          </>
        )}

        {section === "plan" && (
          <>
            <div style={{ fontSize: 11, color: "#7a8aab", padding: "0 4px 12px", lineHeight: 1.4 }}>
              <strong style={{ color: "#cce0ff", letterSpacing: "0.06em", textTransform: "uppercase", fontSize: 10 }}>
                Step 2 · rooms on the floor plan
              </strong>
              <div style={{ marginTop: 6 }}>
                Pick the floor to work on, then position rooms inside it.
                Each room gets its own anchor placement in step 3.
              </div>
            </div>
            <h3 style={sectionTitle}>Floor</h3>
            {(layout.floor_plans || []).length === 0 ? (
              <div style={{ fontSize: 11, color: "#ffb347", padding: "0 4px 12px", lineHeight: 1.4 }}>
                No floor plans defined. Go to step 1 to add one.
              </div>
            ) : (
              <select
                value={selectedFpId || ""}
                onChange={(e) => setSelectedFpId(e.target.value)}
                style={{
                  width: "100%",
                  marginBottom: 12,
                  padding: "6px 8px",
                  background: "rgba(255,255,255,0.04)",
                  color: "#e6edf7",
                  border: "1px solid rgba(255,255,255,0.12)",
                  borderRadius: 4,
                  fontFamily: "ui-monospace, monospace",
                  fontSize: 12,
                }}
              >
                {(layout.floor_plans || []).map((fp) => (
                  <option key={fp.id} value={fp.id} style={{ background: "#0c1428" }}>
                    {fp.label || fp.id}
                  </option>
                ))}
              </select>
            )}
            <h3 style={sectionTitle}>
              Rooms · {(layout.rooms || []).filter((r) => r.floor_plan_id === currentFp?.id).length}
            </h3>
            {(layout.rooms || [])
              .filter((r) => r.floor_plan_id === currentFp?.id)
              .map((r) => {
                const sel = r.id === currentRoom?.id;
                return (
                  <div
                    key={r.id}
                    onClick={() => setSelectedRoomId(r.id)}
                    style={{
                      padding: "8px 10px",
                      marginBottom: 4,
                      borderRadius: 6,
                      cursor: "pointer",
                      // Cyan when selected - matches the canvas highlight so
                      // the operator can see at a glance which row corresponds
                      // to the bright rectangle on the floor plan.
                      background: sel ? "rgba(56,189,248,0.10)" : "rgba(255,255,255,0.03)",
                      border: `1px solid ${sel ? "#38bdf888" : "rgba(255,255,255,0.05)"}`,
                      display: "grid",
                      gridTemplateColumns: "1fr auto",
                      alignItems: "center",
                      gap: 6,
                      fontFamily: "ui-monospace, monospace",
                    }}
                  >
                    <div style={{ overflow: "hidden" }}>
                      <div
                        style={{
                          color: sel ? "#cce0ff" : "#e6edf7",
                          fontWeight: 600,
                          fontSize: 13,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {r.label || r.id}
                      </div>
                      <div style={{ color: "#7a8aab", fontSize: 10, marginTop: 2 }}>
                        {r.label && r.label !== r.id ? `${r.id} · ` : ""}
                        {Number(r.x_m).toFixed(1)}, {Number(r.y_m).toFixed(1)} ·{" "}
                        {Number(r.width_m).toFixed(1)}×{Number(r.height_m).toFixed(1)} m
                      </div>
                    </div>
                    <button
                      style={{ ...btn("ghost"), padding: "2px 6px", fontSize: 10 }}
                      onClick={(e) => {
                        e.stopPropagation();
                        removeRoom(r.id);
                      }}
                      title="Remove this room"
                    >
                      🗑
                    </button>
                  </div>
                );
              })}
            {/* Orphan rooms - those whose floor_plan_id was cleared or set
                to a non-existent floor. Surfaced here so the operator can
                reassign them; otherwise they'd be invisible and step 1's
                "can't delete: rooms attached" guard would feel arbitrary. */}
            {(() => {
              const fpIds = new Set((layout.floor_plans || []).map((fp) => fp.id));
              const orphans = (layout.rooms || []).filter(
                (r) => !r.floor_plan_id || !fpIds.has(r.floor_plan_id)
              );
              if (orphans.length === 0) return null;
              return (
                <>
                  <h3 style={{ ...sectionTitle, color: "#ffb347" }}>
                    Orphan rooms · {orphans.length}
                  </h3>
                  <div style={{ fontSize: 10, color: "#7a8aab", padding: "0 4px 6px", lineHeight: 1.4 }}>
                    Not attached to any floor. Reassign or delete.
                  </div>
                  {orphans.map((r) => (
                    <div key={r.id} style={apRow(false, true)}>
                      <span>
                        <strong style={{ color: "#ffb347", letterSpacing: "0.04em" }}>{r.id}</strong>
                        <span style={{ color: "#7a8aab", marginLeft: 6, fontFamily: "ui-monospace, monospace" }}>
                          {Number(r.width_m).toFixed(1)}×{Number(r.height_m).toFixed(1)} m
                        </span>
                      </span>
                      <select
                        value=""
                        onChange={(e) => {
                          const newFp = e.target.value;
                          history.commit((l) => ({
                            ...l,
                            rooms: (l.rooms || []).map((rr) =>
                              rr.id === r.id ? { ...rr, floor_plan_id: newFp } : rr
                            ),
                          }));
                        }}
                        style={{
                          padding: "2px 4px",
                          background: "rgba(255,255,255,0.04)",
                          color: "#e6edf7",
                          border: "1px solid rgba(255,255,255,0.12)",
                          borderRadius: 3,
                          fontSize: 10,
                          fontFamily: "ui-monospace, monospace",
                        }}
                      >
                        <option value="" disabled style={{ background: "#0c1428" }}>
                          assign to…
                        </option>
                        {(layout.floor_plans || []).map((fp) => (
                          <option key={fp.id} value={fp.id} style={{ background: "#0c1428" }}>
                            {fp.label || fp.id}
                          </option>
                        ))}
                      </select>
                      <button
                        style={{ ...btn("ghost"), padding: "2px 6px", fontSize: 10 }}
                        onClick={(e) => {
                          e.stopPropagation();
                          removeRoom(r.id);
                        }}
                        title="Delete this orphan room"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </>
              );
            })()}
            <button
              style={{ ...btn("ghost"), marginTop: 6, width: "100%" }}
              onClick={addRoom}
              disabled={!currentFp}
            >
              + add room
            </button>

            {/* Scale calibration - entry point only. The actual wizard
                lives as a floating panel on the canvas (PlanCanvas owns
                it) so the operator's focus stays on the floor-plan image. */}
            {currentFp && (
              <>
                <h3 style={sectionTitle}>Scale calibration</h3>
                {scaleCal && scaleCal.fpId === currentFp.id ? (
                  <div
                    style={{
                      fontSize: 10,
                      color: "#9ec3ff",
                      padding: "6px 10px",
                      background: "rgba(56,189,248,0.08)",
                      border: "1px solid rgba(56,189,248,0.3)",
                      borderRadius: 4,
                      fontFamily: "ui-monospace, monospace",
                      letterSpacing: "0.06em",
                      textTransform: "uppercase",
                    }}
                  >
                    in progress · panel above canvas
                  </div>
                ) : (
                  <>
                    <div
                      style={{
                        fontSize: 10,
                        color: "#7a8aab",
                        padding: "0 4px 6px",
                        lineHeight: 1.4,
                      }}
                    >
                      Take known measurements on the image (walls, doorways,
                      annotated dimensions). Multiple references → averaged
                      scale → lower error.
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        // Load previously-saved references for this floor
                        // plan so the operator can resume calibration where
                        // they left off and add more refs to improve confidence.
                        const saved = (currentFp.scale_calibration_refs || []).map(
                          (r) => ({
                            id: r.id,
                            p1: [r.p1[0], r.p1[1]],
                            p2: [r.p2[0], r.p2[1]],
                            knownM: r.knownM,
                            distNow: Math.hypot(r.p2[0] - r.p1[0], r.p2[1] - r.p1[1]),
                          })
                        );
                        setScaleCal({
                          fpId: currentFp.id,
                          picking: "p1",
                          pendingP1: null,
                          pendingP2: null,
                          refs: saved,
                        });
                      }}
                      style={{
                        width: "100%",
                        padding: "5px 8px",
                        background: "transparent",
                        color: "#9ec3ff",
                        border: "1px dashed rgba(58,130,255,0.4)",
                        borderRadius: 4,
                        fontSize: 11,
                        letterSpacing: "0.06em",
                        textTransform: "uppercase",
                        fontFamily: "ui-monospace, monospace",
                        cursor: "pointer",
                      }}
                    >
                      ↹ calibrate scale
                      {(currentFp.scale_calibration_refs || []).length > 0 && (
                        <span style={{ color: "#7a8aab", marginLeft: 6 }}>
                          ({(currentFp.scale_calibration_refs || []).length} saved)
                        </span>
                      )}
                    </button>
                  </>
                )}
              </>
            )}

            {currentRoom && (
              <>
                <h3 style={sectionTitle}>Selected · {currentRoom.id}</h3>

                {/* Edit-mode toggle - mirrors the World step's pencil/done
                    pattern. View mode is read-only on the canvas (click
                    selects, no drag); edit mode unlocks drag, corner/edge
                    handles and arrow-key nudge. Numeric inputs below are
                    always live - they're explicit, not gesture-based. */}
                <div style={{ padding: "0 4px 8px" }}>
                  <button
                    type="button"
                    onClick={() =>
                      setEditingRoomId(
                        editingRoomId === currentRoom.id ? null : currentRoom.id
                      )
                    }
                    title={
                      editingRoomId === currentRoom.id
                        ? "Lock the room - clicks on the canvas just select, no accidental drag."
                        : "Unlock the room - drag-to-move, corner/edge resize, and arrow-key nudge become active on the canvas."
                    }
                    style={{
                      width: "100%",
                      padding: "5px 8px",
                      background:
                        editingRoomId === currentRoom.id
                          ? "rgba(93,255,176,0.18)"
                          : "transparent",
                      color:
                        editingRoomId === currentRoom.id ? "#5dffb0" : "#9ec3ff",
                      border: `1px solid ${
                        editingRoomId === currentRoom.id
                          ? "#5dffb088"
                          : "rgba(58,130,255,0.4)"
                      }`,
                      borderRadius: 4,
                      fontSize: 11,
                      letterSpacing: "0.06em",
                      textTransform: "uppercase",
                      fontFamily: "ui-monospace, monospace",
                      cursor: "pointer",
                    }}
                  >
                    {editingRoomId === currentRoom.id ? "✓ done editing" : "✎ edit room"}
                  </button>
                </div>

                {/* Identity - the human-facing name. The id is read-only +
                    surfaced in the section title above. */}
                <div
                  style={{
                    fontSize: 9,
                    color: "#7a8aab",
                    letterSpacing: "0.10em",
                    textTransform: "uppercase",
                    margin: "6px 4px 4px",
                  }}
                >
                  · identity
                </div>
                <div style={field}>
                  <span style={label}>label</span>
                  <TextInput
                    value={currentRoom.label}
                    onCommit={(v) => mutateRoom((r) => ({ ...r, label: v }))}
                  />
                </div>

                {/* Size - intrinsic dimensions of the room (independent of
                    where it sits). Grouped first because operators usually
                    start by deciding "how big is this room?" before "where". */}
                <div
                  style={{
                    fontSize: 9,
                    color: "#7a8aab",
                    letterSpacing: "0.10em",
                    textTransform: "uppercase",
                    margin: "10px 4px 4px",
                  }}
                >
                  · size (m)
                </div>
                <div style={field}>
                  <span style={label}>width</span>
                  <NumberInput
                    value={Number(currentRoom.width_m)}
                    min={0.5}
                    step="0.5"
                    onCommit={(v) => mutateRoom((r) => ({ ...r, width_m: v }))}
                  />
                </div>
                <div style={field}>
                  <span style={label}>height</span>
                  <NumberInput
                    value={Number(currentRoom.height_m)}
                    min={0.5}
                    step="0.5"
                    onCommit={(v) => mutateRoom((r) => ({ ...r, height_m: v }))}
                  />
                </div>

                {/* Position - where the room's lower-left corner sits in the
                    floor plan's local frame. Always relative to the floor
                    plan, never to the world (the world rotation is baked
                    into section 1's calibration). */}
                <div
                  style={{
                    fontSize: 9,
                    color: "#7a8aab",
                    letterSpacing: "0.10em",
                    textTransform: "uppercase",
                    margin: "10px 4px 4px",
                  }}
                >
                  · position (m, from floor plan ⌐)
                </div>
                <div style={field}>
                  <span style={label}>x</span>
                  <NumberInput
                    value={Number(currentRoom.x_m)}
                    step="0.1"
                    onCommit={(v) => mutateRoom((r) => ({ ...r, x_m: v }))}
                  />
                </div>
                <div style={field}>
                  <span style={label}>y</span>
                  <NumberInput
                    value={Number(currentRoom.y_m)}
                    step="0.1"
                    onCommit={(v) => mutateRoom((r) => ({ ...r, y_m: v }))}
                  />
                </div>

                {/* Rotation - angle of the room within the floor plan's
                    local frame (NOT the world). Use this for rooms that sit
                    at an angle relative to the building's main axes (e.g. a
                    diagonal wing). 0° means axis-aligned to the floor plan
                    image as uploaded. The world rotation is separate, set
                    by section 1's calibration. */}
                <div
                  style={{
                    fontSize: 9,
                    color: "#7a8aab",
                    letterSpacing: "0.10em",
                    textTransform: "uppercase",
                    margin: "10px 4px 4px",
                  }}
                >
                  · rotation (° in floor plan)
                </div>
                <div style={field}>
                  <span style={label}>angle</span>
                  <NumberInput
                    value={Number(currentRoom.rotation_deg) || 0}
                    step="1"
                    onCommit={(v) => mutateRoom((r) => ({ ...r, rotation_deg: v }))}
                  />
                </div>
                {/* Polygon shape - for irregular rooms (L/T/H, courtyards,
                    rooms with angled walls). Critical for UWB precision: a
                    rectangular approximation puts anchors on the wrong side
                    of phantom walls. Toggle the trace tool; it captures
                    vertex clicks in the canvas and replaces the rectangle. */}
                <div
                  style={{
                    fontSize: 9,
                    color: "#7a8aab",
                    letterSpacing: "0.10em",
                    textTransform: "uppercase",
                    margin: "10px 4px 4px",
                  }}
                >
                  · shape
                </div>
                <div style={{ padding: "0 4px 8px", fontSize: 11 }}>
                  {Array.isArray(currentRoom.shape) && currentRoom.shape.length >= 3 ? (
                    <div style={{ color: "#cce0ff", marginBottom: 6, lineHeight: 1.4 }}>
                      polygon · {currentRoom.shape.length} vertices
                    </div>
                  ) : (
                    <div style={{ color: "#7a8aab", marginBottom: 6, lineHeight: 1.4 }}>
                      rectangle (use trace for irregular rooms)
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 4 }}>
                    <button
                      type="button"
                      onClick={() => {
                        setTracingPolygonForRoomId(null);
                        setScaleCal(null);
                        setFitCorners((cur) => (cur ? null : { p1: null }));
                      }}
                      title="Set the room rectangle from two precise clicks on opposite corners of the room as drawn on the image. Each click opens the magnifier loupe for pixel-level refinement."
                      style={{
                        flex: 1,
                        padding: "5px 8px",
                        background: fitCorners ? "rgba(56,189,248,0.25)" : "transparent",
                        color: fitCorners ? "#38bdf8" : "#9ec3ff",
                        border: `1px solid ${fitCorners ? "#38bdf888" : "rgba(58,130,255,0.4)"}`,
                        borderRadius: 4,
                        fontSize: 11,
                        letterSpacing: "0.06em",
                        textTransform: "uppercase",
                        fontFamily: "ui-monospace, monospace",
                        cursor: "pointer",
                      }}
                    >
                      ⌖ fit corners
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setFitCorners(null);
                        setTracingPolygonForRoomId((cur) =>
                          cur === currentRoom.id ? null : currentRoom.id
                        );
                      }}
                      style={{
                        flex: 1,
                        padding: "5px 8px",
                        background: tracingPolygonForRoomId === currentRoom.id
                          ? "rgba(251,191,36,0.25)"
                          : "transparent",
                        color: tracingPolygonForRoomId === currentRoom.id
                          ? "#fbbf24"
                          : "#9ec3ff",
                        border: `1px solid ${
                          tracingPolygonForRoomId === currentRoom.id
                            ? "#fbbf2488"
                            : "rgba(58,130,255,0.4)"
                        }`,
                        borderRadius: 4,
                        fontSize: 11,
                        letterSpacing: "0.06em",
                        textTransform: "uppercase",
                        fontFamily: "ui-monospace, monospace",
                        cursor: "pointer",
                      }}
                    >
                      ↪ trace polygon
                    </button>
                    {Array.isArray(currentRoom.shape) && currentRoom.shape.length >= 3 && (
                      <button
                        type="button"
                        onClick={() =>
                          mutateRoom((r) => {
                            const { shape: _, ...rest } = r;
                            return rest;
                          })
                        }
                        title="Discard the polygon and revert to the axis-aligned bbox"
                        style={{
                          padding: "5px 8px",
                          background: "transparent",
                          color: "#ff6b78",
                          border: "1px solid rgba(255,107,120,0.4)",
                          borderRadius: 4,
                          fontSize: 11,
                          letterSpacing: "0.06em",
                          textTransform: "uppercase",
                          fontFamily: "ui-monospace, monospace",
                          cursor: "pointer",
                        }}
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </div>

                {/* World-position sanity check. The room's centre projected
                    back through section 1's calibration so the operator can
                    confirm the locally-defined rectangle lands where they
                    expect on the planet. Read-only - to move the room
                    elsewhere, edit x/y above (local frame) or recalibrate
                    the floor plan in section 1. */}
                {currentFp?.georef?.latitude != null &&
                  currentFp?.georef?.longitude != null &&
                  Number(currentFp.georef.width_m) > 0 &&
                  Number(currentFp.georef.height_m) > 0 && (() => {
                    // Use polygon centroid when present (area-weighted, so
                    // it's the geometric centre even for L/T/H shapes).
                    let cx, cy;
                    if (Array.isArray(currentRoom.shape) && currentRoom.shape.length >= 3) {
                      const c = centroidOfPolygon(currentRoom.shape);
                      cx = c?.x ?? Number(currentRoom.x_m) + Number(currentRoom.width_m) / 2;
                      cy = c?.y ?? Number(currentRoom.y_m) + Number(currentRoom.height_m) / 2;
                    } else {
                      cx = Number(currentRoom.x_m) + Number(currentRoom.width_m) / 2;
                      cy = Number(currentRoom.y_m) + Number(currentRoom.height_m) / 2;
                    }
                    const w = localToGps(cx, cy, {
                      latitude: Number(currentFp.georef.latitude),
                      longitude: Number(currentFp.georef.longitude),
                      azimuth_deg: Number(currentFp.georef.azimuth_deg) || 0,
                    });
                    return (
                      <>
                        <h3 style={sectionTitle}>World position · room centre</h3>
                        <div
                          style={{
                            fontFamily: "ui-monospace, monospace",
                            fontSize: 11,
                            color: "#9ec3ff",
                            padding: "0 4px 6px",
                            lineHeight: 1.5,
                          }}
                        >
                          lat {w.lat.toFixed(6)}
                          <br />
                          lon {w.lng.toFixed(6)}
                        </div>
                        <div
                          style={{
                            fontSize: 10,
                            color: "#7a8aab",
                            padding: "0 4px 6px",
                            lineHeight: 1.4,
                          }}
                        >
                          Read-only - derived from section 1's calibration. If
                          this looks wrong, recalibrate the floor plan rather
                          than nudging the room.
                        </div>
                      </>
                    );
                  })()}
              </>
            )}
          </>
        )}

        {section === "room" && (() => {
          const fpRooms = (layout.rooms || []).filter(
            (r) => r.floor_plan_id === currentFp?.id
          );
          return (
          <>
        {/* Room picker - first thing the operator does in step 3 is choose
            which room to place anchors in. Compact dropdown, falls back to
            "no rooms" if the floor plan has none yet. */}
        <div style={{ padding: "0 4px 12px" }}>
          <div
            style={{
              fontSize: 9,
              color: "#7a8aab",
              letterSpacing: "0.10em",
              textTransform: "uppercase",
              marginBottom: 4,
            }}
          >
            · room
          </div>
          {fpRooms.length === 0 ? (
            <div
              style={{
                fontSize: 11,
                color: "#7a8aab",
                padding: "6px 8px",
                background: "rgba(255,179,71,0.06)",
                border: "1px solid rgba(255,179,71,0.25)",
                borderRadius: 4,
              }}
            >
              No rooms yet - draw one in step 2.
            </div>
          ) : (
            <select
              style={inputStyle(false)}
              value={currentRoom?.id || ""}
              onChange={(e) => setSelectedRoomId(e.target.value)}
            >
              {fpRooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label || r.id} · {Number(r.width_m).toFixed(1)}×{Number(r.height_m).toFixed(1)} m
                </option>
              ))}
            </select>
          )}
          {currentRoom && (
            <div
              style={{
                marginTop: 6,
                fontSize: 10,
                color: "#7a8aab",
                fontFamily: "ui-monospace, monospace",
              }}
            >
              {Number(w).toFixed(2)} × {Number(h).toFixed(2)} m ·{" "}
              <button
                type="button"
                onClick={() => setSection("plan")}
                title="Edit the room's size, position, or shape in step 2."
                style={{
                  padding: 0,
                  background: "transparent",
                  color: "#cce0ff",
                  border: "none",
                  fontSize: 10,
                  fontFamily: "ui-monospace, monospace",
                  cursor: "pointer",
                  textDecoration: "underline",
                  textUnderlineOffset: 2,
                }}
              >
                edit in step 2
              </button>
            </div>
          )}
          {currentRoom && (
            <div
              style={{
                marginTop: 8,
                display: "grid",
                gridTemplateColumns: "auto 70px auto",
                alignItems: "center",
                gap: 6,
                fontSize: 10,
                color: "#7a8aab",
                fontFamily: "ui-monospace, monospace",
              }}
            >
              <span>ceiling</span>
              <NumberInput
                value={currentRoom.wall_height_m ?? DEFAULT_WALL_HEIGHT_M}
                step="0.1"
                min={0.5}
                onCommit={(v) =>
                  mutateRoom((r) => ({ ...r, wall_height_m: v }))
                }
              />
              <span>m</span>
            </div>
          )}
        </div>

        <h3 style={sectionTitle}>Anchors · {aps.length}</h3>
        {aps.length === 0 && (
          <div style={{ color: "#7a8aab", fontSize: 12, padding: "4px 10px" }}>
            none yet - pick a technology in the toolbar and click on the canvas
          </div>
        )}
        {(() => {
          // Group anchors by technology. Unknown technologies still render
          // under a fallback group so legacy layouts keep working.
          const groups = new Map();
          for (const tech of TECH_KEYS) groups.set(tech, []);
          for (const ap of aps) {
            const k = techOf(ap);
            if (!groups.has(k)) groups.set(k, []);
            groups.get(k).push(ap);
          }
          return [...groups.entries()].map(([tech, items]) => {
            if (items.length === 0) return null;
            const meta = techMeta(tech);
            const collapsed = !!collapsedTech[tech];
            return (
              <div key={tech} style={{ marginBottom: 8 }}>
                {/* Tech-group header doubles as a collapse toggle. Caret
                    rotates; clicking collapses just this group so the
                    operator can focus on one tech while wiring another. */}
                <button
                  type="button"
                  onClick={() =>
                    setCollapsedTech((cur) => ({ ...cur, [tech]: !cur[tech] }))
                  }
                  title={
                    collapsed
                      ? `Show ${meta.label} anchors (also un-ghosts them on the canvas)`
                      : `Hide ${meta.label} anchors (also ghosts them on the canvas)`
                  }
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    width: "100%",
                    fontSize: 11,
                    fontWeight: 600,
                    letterSpacing: "0.10em",
                    textTransform: "uppercase",
                    color: collapsed ? `${meta.color}88` : meta.color,
                    margin: "10px 0 6px",
                    padding: "6px 8px",
                    background: collapsed
                      ? "transparent"
                      : `${meta.color}10`,
                    border: `1px solid ${
                      collapsed ? "rgba(255,255,255,0.06)" : `${meta.color}40`
                    }`,
                    borderRadius: 4,
                    fontFamily: "ui-monospace, monospace",
                    cursor: "pointer",
                    textAlign: "left",
                  }}
                >
                  <span
                    style={{
                      display: "inline-block",
                      width: 12,
                      fontSize: 14,
                      lineHeight: 1,
                      transform: collapsed ? "rotate(-90deg)" : "rotate(0deg)",
                      transition: "transform 0.12s",
                    }}
                  >
                    ▾
                  </span>
                  <span style={{ flex: 1 }}>{meta.label}</span>
                  <span style={{ opacity: 0.7 }}>{items.length}</span>
                </button>
                {!collapsed && items.map((ap) => (
                  <div
                    key={ap.id}
                    style={apRow(ap.id === selectedApId, apIdInvalid(ap))}
                    onClick={() => selectAp(ap.id)}
                    title={apIdInvalid(ap) ? errorByField.get(`ap:${ap.id}`) : undefined}
                  >
                    <span>
                      <strong style={{ color: meta.color, letterSpacing: "0.04em" }}>{ap.id}</strong>
                      <span
                        style={{
                          color: "#7a8aab",
                          marginLeft: 6,
                          fontFamily: "ui-monospace, monospace",
                        }}
                      >
                        {Number(ap.x).toFixed(2)}, {Number(ap.y).toFixed(2)}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            );
          });
        })()}

        {/* Walls section. Same collapsible-group pattern as anchors -
            collapsed by default because the operator edits walls on the
            canvas, not in the list. Header doubles as toggle. */}
        <div style={{ marginTop: 4 }}>
          <button
            type="button"
            onClick={() => setWallsCollapsed((v) => !v)}
            title={wallsCollapsed ? "Show walls" : "Hide walls"}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              width: "100%",
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: "0.10em",
              textTransform: "uppercase",
              color: wallsCollapsed ? "#9ec3ff88" : "#9ec3ff",
              margin: "10px 0 6px",
              padding: "6px 8px",
              background: wallsCollapsed ? "transparent" : "#9ec3ff10",
              border: `1px solid ${
                wallsCollapsed ? "rgba(255,255,255,0.06)" : "#9ec3ff40"
              }`,
              borderRadius: 4,
              fontFamily: "ui-monospace, monospace",
              cursor: "pointer",
              textAlign: "left",
            }}
          >
            <span
              style={{
                display: "inline-block",
                width: 12,
                fontSize: 14,
                lineHeight: 1,
                transform: wallsCollapsed ? "rotate(-90deg)" : "rotate(0deg)",
                transition: "transform 0.12s",
              }}
            >
              ▾
            </span>
            <span style={{ flex: 1 }}>walls</span>
            <span style={{ opacity: 0.7 }}>{walls.length}</span>
          </button>
          {!wallsCollapsed && walls.length === 0 && (
            <div style={{ color: "#7a8aab", fontSize: 11, padding: "4px 10px" }}>
              click <strong>+ Wall</strong> in the toolbar, then drag on the canvas
            </div>
          )}
          {!wallsCollapsed &&
            walls.map((wall) => {
              const invalid = errorByField.has(`wall:${wall.id}`);
              const sel = wall.id === selectedWallId;
              return (
                <div
                  key={wall.id}
                  style={apRow(sel, invalid)}
                  onClick={() => selectWall(wall.id)}
                  title={invalid ? errorByField.get(`wall:${wall.id}`) : undefined}
                >
                  <span>
                    <strong style={{ color: "#9ec3ff", letterSpacing: "0.04em" }}>{wall.id}</strong>
                    <span
                      style={{
                        color: "#7a8aab",
                        marginLeft: 6,
                        fontFamily: "ui-monospace, monospace",
                      }}
                    >
                      {wallLength(wall).toFixed(2)} m
                    </span>
                  </span>
                </div>
              );
            })}
        </div>

        {/* Perimeter openings - doors / corridor stubs on the room
            boundary. Indexed per edge so the same UI works for axis-aligned
            rectangles (4 edges, hinted N/E/S/W) and polygon-shaped rooms
            (N edges, no cardinal hint). Click "+ edge i" to seed a 1 m
            opening centred on that edge. */}
        {(() => {
          const ros = currentRoom?.perimeter_openings || [];
          const edges = perimeterEdges(currentRoom);
          return (
            <div style={{ marginTop: 4 }}>
              <button
                type="button"
                onClick={() => setPerimeterCollapsed((v) => !v)}
                title={
                  perimeterCollapsed
                    ? "Show perimeter openings (doors / corridor stubs on the boundary)"
                    : "Hide perimeter openings"
                }
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  width: "100%",
                  fontSize: 11,
                  fontWeight: 600,
                  letterSpacing: "0.10em",
                  textTransform: "uppercase",
                  color: perimeterCollapsed ? "#9ec3ff88" : "#9ec3ff",
                  margin: "10px 0 6px",
                  padding: "6px 8px",
                  background: perimeterCollapsed ? "transparent" : "#9ec3ff10",
                  border: `1px solid ${
                    perimeterCollapsed ? "rgba(255,255,255,0.06)" : "#9ec3ff40"
                  }`,
                  borderRadius: 4,
                  fontFamily: "ui-monospace, monospace",
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                <span
                  style={{
                    display: "inline-block",
                    width: 12,
                    fontSize: 14,
                    lineHeight: 1,
                    transform: perimeterCollapsed ? "rotate(-90deg)" : "rotate(0deg)",
                    transition: "transform 0.12s",
                  }}
                >
                  ▾
                </span>
                <span style={{ flex: 1 }}>perimeter doors</span>
                <span style={{ opacity: 0.7 }}>{ros.length}</span>
              </button>
              {!perimeterCollapsed && (
                <div style={{ padding: "0 4px" }}>
                  {edges.length === 0 ? (
                    <div
                      style={{
                        color: "#5a6987",
                        fontSize: 10,
                        padding: "4px 0",
                        fontFamily: "ui-monospace, monospace",
                      }}
                    >
                      room has no perimeter yet
                    </div>
                  ) : (
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns:
                          edges.length <= 4 ? `repeat(${edges.length}, 1fr)` : "repeat(4, 1fr)",
                        gap: 4,
                        marginBottom: 8,
                      }}
                    >
                      {edges.map((edge, idx) => (
                        <button
                          key={idx}
                          type="button"
                          title={`Add a door on edge ${idx}${
                            edge.label ? ` (${edge.label})` : ""
                          } - ${edge.length.toFixed(2)} m`}
                          onClick={() => {
                            if (edge.length < 0.4) return;
                            const center = edge.length / 2;
                            const span = Math.min(1.0, Math.max(0.3, edge.length * 0.2));
                            addPerimeterOpening({
                              id: nextPerimeterOpeningId(ros),
                              edge_index: idx,
                              start_m: +(center - span / 2).toFixed(2),
                              end_m: +(center + span / 2).toFixed(2),
                              height_m: DEFAULT_OPENING_HEIGHT_M,
                              sill_m: 0,
                            });
                          }}
                          style={{
                            padding: "5px 4px",
                            fontSize: 10,
                            fontWeight: 600,
                            letterSpacing: "0.04em",
                            textTransform: "uppercase",
                            fontFamily: "ui-monospace, monospace",
                            background: "transparent",
                            color: "#9ec3ff",
                            border: "1px solid #9ec3ff55",
                            borderRadius: 3,
                            cursor: edge.length < 0.4 ? "not-allowed" : "pointer",
                            opacity: edge.length < 0.4 ? 0.5 : 1,
                          }}
                        >
                          + {edge.label || idx}
                        </button>
                      ))}
                    </div>
                  )}
                  {ros.length === 0 && (
                    <div
                      style={{
                        color: "#5a6987",
                        fontSize: 10,
                        padding: "4px 0",
                        fontFamily: "ui-monospace, monospace",
                      }}
                    >
                      none - solid perimeter
                    </div>
                  )}
                  {ros.map((o) => {
                    const edge = edges[o.edge_index];
                    const len = edge?.length ?? 0;
                    const tag = edge?.label ?? `edge ${o.edge_index}`;
                    return (
                      <div
                        key={o.id}
                        style={{
                          marginBottom: 6,
                          padding: "6px 8px",
                          borderRadius: 4,
                          background: "rgba(158,195,255,0.05)",
                          border: "1px solid rgba(158,195,255,0.15)",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: 6,
                            marginBottom: 4,
                          }}
                        >
                          <strong
                            style={{
                              color: "#9ec3ff",
                              fontSize: 10,
                              fontFamily: "ui-monospace, monospace",
                              letterSpacing: "0.04em",
                            }}
                          >
                            {o.id} · {tag}
                          </strong>
                          <button
                            type="button"
                            onClick={() => removePerimeterOpening(o.id)}
                            title="Delete opening"
                            style={{
                              padding: "1px 5px",
                              background: "transparent",
                              color: "#ff6b78",
                              border: "1px solid rgba(255,107,120,0.4)",
                              borderRadius: 3,
                              fontSize: 10,
                              fontFamily: "ui-monospace, monospace",
                              cursor: "pointer",
                            }}
                          >
                            ✕
                          </button>
                        </div>
                        <div style={field}>
                          <span style={label}>start m</span>
                          <NumberInput
                            value={o.start_m}
                            step="0.1"
                            min={0}
                            max={len}
                            onCommit={(v) =>
                              updatePerimeterOpening(o.id, { start_m: v })
                            }
                          />
                        </div>
                        <div style={field}>
                          <span style={label}>end m</span>
                          <NumberInput
                            value={o.end_m}
                            step="0.1"
                            min={0}
                            max={len}
                            onCommit={(v) =>
                              updatePerimeterOpening(o.id, { end_m: v })
                            }
                          />
                        </div>
                        <div style={field}>
                          <span style={label}>height</span>
                          <NumberInput
                            value={o.height_m ?? DEFAULT_OPENING_HEIGHT_M}
                            step="0.1"
                            min={0.1}
                            onCommit={(v) =>
                              updatePerimeterOpening(o.id, { height_m: v })
                            }
                          />
                        </div>
                        <div style={field}>
                          <span style={label}>sill</span>
                          <NumberInput
                            value={o.sill_m ?? 0}
                            step="0.1"
                            min={0}
                            onCommit={(v) =>
                              updatePerimeterOpening(o.id, { sill_m: v })
                            }
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })()}

          </>
          );
        })()}
      </aside>

      <div style={canvasWrap}>
        {section === "world" && (
          <div style={{ width: "100%" }}>
            <GeorefMap
              ref={georefRef}
              floorPlan={currentFp}
              snapEnabled={snapEnabled}
              showGrid={showGrid}
              onSelect={(isSelected) => {
                setFloorEngaged(isSelected);
              }}
              onEditCommit={() => onSave()}
              /* Step 1 is the area-layer view: anchors and per-room details
                  do not belong here. They are read-only at this abstraction
                  level - the operator looks at the building footprint, not
                  the wiring. */
              anchors={[]}
              onTransientStart={() => {
                geoDragRef.current = true;
                history.beginTransient();
              }}
              onTransientEnd={() => {
                if (!geoDragRef.current) return;
                geoDragRef.current = false;
                history.endTransient();
              }}
              onOriginChange={(patch) => {
                const fpId = currentFp?.id ?? selectedFpId;
                const mutator = (l) => ({
                  ...l,
                  floor_plans: (l.floor_plans || []).map((fp) =>
                    fp.id === fpId
                      ? { ...fp, georef: { ...(fp.georef || {}), ...patch } }
                      : fp
                  ),
                });
                // Drag in progress: stream into transient history so the
                // whole gesture collapses to one undo step on release.
                if (geoDragRef.current) history.applyTransient(mutator);
                else history.commit(mutator);
              }}
              onFloorPlanImageChange={(image) => {
                mutateFp((fp) => ({ ...fp, image }));
                setFloorEngaged(true);
              }}
              onDrawRectangle={({ lat, lng }) => {
                mutateFp((fp) => ({
                  ...fp,
                  georef: {
                    ...(fp.georef || {}),
                    latitude: lat,
                    longitude: lng,
                    azimuth_deg: fp.georef?.azimuth_deg || 0,
                    width_m: 20,
                    height_m: 20,
                  },
                }));
                setFloorEngaged(true);
              }}
            />
          </div>
        )}
        {section === "plan" && (
          <div style={{ width: "100%", padding: "12px 20px 20px" }}>
            <PlanCanvas
              floorPlan={currentFp}
              rooms={(layout.rooms || []).filter((r) => r.floor_plan_id === currentFp?.id)}
              selectedRoomId={currentRoom?.id}
              onSelectRoom={(id) => {
                setSelectedRoomId(id);
                // Selecting a different room exits any active edit mode -
                // the operator should consciously re-enter editing on the
                // new selection (mirrors section 1's "deselect-on-other"
                // behaviour for the area handles).
                if (id !== editingRoomId) setEditingRoomId(null);
              }}
              editingRoomId={editingRoomId}
              onExitEdit={() => setEditingRoomId(null)}
              snapEnabled={snapEnabled}
              showGrid={showGrid}
              traceActive={Boolean(tracingPolygonForRoomId && tracingPolygonForRoomId === currentRoom?.id)}
              scaleCal={scaleCal && scaleCal.fpId === currentFp?.id ? scaleCal : null}
              setScaleCal={setScaleCal}
              onScaleCalClick={(pt) => {
                if (!scaleCal || scaleCal.fpId !== currentFp?.id) return;
                // Two-stage click capture: first click → pendingP1, second
                // click → pendingP2. The floating guided panel takes over
                // for the known-distance entry.
                if (!scaleCal.pendingP1) {
                  setScaleCal({ ...scaleCal, pendingP1: pt, picking: "p2" });
                } else if (!scaleCal.pendingP2) {
                  setScaleCal({ ...scaleCal, pendingP2: pt, picking: null });
                }
              }}
              onScaleCalApply={(sAvg) => {
                if (!(sAvg > 0) || !currentFp) return;
                // Pass the session's refs through so any add/remove edits
                // land in the same commit as the scale correction.
                rescaleFloorPlan(currentFp.id, sAvg, scaleCal?.refs || []);
                setScaleCal(null);
              }}
              fitCorners={currentRoom ? fitCorners : null}
              setFitCorners={setFitCorners}
              onFitCornersCommit={(rect) => {
                // The fitted rectangle replaces both the bbox AND any
                // polygon shape - the tool's contract is "this room IS this
                // rectangle".
                mutateRoom((r) => {
                  const { shape: _, ...rest } = r;
                  return { ...rest, ...rect };
                });
                setFitCorners(null);
              }}
              onTraceCommit={(verts) => {
                // Sync the polygon AND the bbox so section 3 + engine see a
                // consistent frame. The bbox is the AABB of the polygon.
                const bbox = bboxOfPolygon(verts);
                if (!bbox) return;
                mutateRoom((r) => ({
                  ...r,
                  shape: verts.map(([x, y]) => [x, y]),
                  x_m: bbox.x_m,
                  y_m: bbox.y_m,
                  width_m: bbox.width_m,
                  height_m: bbox.height_m,
                }));
                setTracingPolygonForRoomId(null);
              }}
              onTraceCancel={() => setTracingPolygonForRoomId(null)}
              onRoomDragStart={() => history.beginTransient()}
              onRoomDragMove={(roomId, fields) => {
                // When a polygon-shaped room is being translated, the
                // `shape` array is included in fields and the bbox follows.
                // Keep them in lock-step.
                const merged = { ...fields };
                if (Array.isArray(merged.shape)) {
                  const bb = bboxOfPolygon(merged.shape);
                  if (bb) {
                    merged.x_m = bb.x_m;
                    merged.y_m = bb.y_m;
                    merged.width_m = bb.width_m;
                    merged.height_m = bb.height_m;
                  }
                }
                history.applyTransient((l) => ({
                  ...l,
                  rooms: (l.rooms || []).map((r) =>
                    r.id === roomId ? { ...r, ...merged } : r
                  ),
                }));
              }}
              onRoomDragEnd={() => history.endTransient()}
            />
          </div>
        )}
        {section === "room" && (
        <div
          style={{
            display: "flex",
            width: "100%",
            gap: 12,
            minWidth: 0,
            // Fill the content cell's height (overrides canvasWrap's center)
            // so the canvas sizes to the available space instead of a magic
            // viewport-minus-N px, which under/overshoots and overflows.
            alignSelf: "stretch",
            minHeight: 0,
            alignItems: "stretch",
          }}
        >
          <div style={{ flex: 1, minWidth: 0, position: "relative", display: "flex", flexDirection: "column", minHeight: 0 }}>
          {/* Canvas-top action bar - close to where the operator works.
              Replaces the section-3-only tool buttons that used to live in
              the global header. UWB + WiFi are the primary actions (current
              testbed focus); 5G + GNSS are demoted visually because they
              are not the priority right now. Walls sit on the right after
              a separator. */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 10px",
              marginBottom: 8,
              borderRadius: 8,
              background: "rgba(15,22,40,0.65)",
              border: "1px solid rgba(58,130,255,0.18)",
            }}
          >
            <button
              type="button"
              onClick={() => setTool("select")}
              title="Select (V)"
              style={toolBtnStyle({
                accent: tool === "select" ? "#cce0ff" : "#7a8aab",
                active: tool === "select",
                secondary: true,
              })}
            >
              ▸ select
            </button>
            <span style={{ width: 1, height: 18, background: "rgba(255,255,255,0.08)", margin: "0 4px" }} />
            {/* Primary techs - UWB (the registry key is "wittra") and WiFi
                take visible weight. Other technologies (5G / GNSS) hide
                under a "+ more ▾" menu so the bar stays calm. */}
            {["wittra", "wifi"].map((t) => {
              const m = techMeta(t);
              const active = tool === `anchor:${t}`;
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTool(`anchor:${t}`)}
                  title={`+ ${m.label} anchor (${m.hotkey.toUpperCase()})`}
                  style={toolBtnStyle({ accent: m.color, active })}
                >
                  + {m.label}
                </button>
              );
            })}
            {/* Secondary-tech dropdown - 5G / GNSS not priority right now.
                Open on click, close on outside-click / Esc. */}
            <div data-more-tech style={{ position: "relative" }}>
              <button
                type="button"
                onClick={() => setMoreTechOpen((o) => !o)}
                title="Other technologies"
                style={toolBtnStyle({
                  accent: "#9aa9c4",
                  active: moreTechOpen,
                  secondary: true,
                })}
              >
                + more ▾
              </button>
              {moreTechOpen && (
                <div
                  style={{
                    position: "absolute",
                    top: "calc(100% + 4px)",
                    left: 0,
                    minWidth: 140,
                    padding: 4,
                    background: "rgba(11,17,32,0.98)",
                    border: "1px solid rgba(255,255,255,0.12)",
                    borderRadius: 6,
                    boxShadow: "0 6px 20px rgba(0,0,0,0.5)",
                    zIndex: 4,
                  }}
                >
                  {["fiveg", "gnss"].map((t) => {
                    const m = techMeta(t);
                    return (
                      <button
                        key={t}
                        type="button"
                        onClick={() => {
                          setTool(`anchor:${t}`);
                          setMoreTechOpen(false);
                        }}
                        style={{
                          display: "block",
                          width: "100%",
                          textAlign: "left",
                          padding: "6px 10px",
                          fontSize: 11,
                          letterSpacing: "0.06em",
                          textTransform: "uppercase",
                          fontFamily: "ui-monospace, monospace",
                          background: "transparent",
                          color: m.color,
                          border: "none",
                          cursor: "pointer",
                          borderRadius: 4,
                        }}
                        onMouseEnter={(e) =>
                          (e.currentTarget.style.background = "rgba(255,255,255,0.05)")
                        }
                        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                      >
                        + {m.label}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
            <span style={{ width: 1, height: 18, background: "rgba(255,255,255,0.08)", margin: "0 4px" }} />
            <button
              type="button"
              onClick={() => setTool("wall")}
              title="+ Wall (W). Hold Shift while drawing to snap angle to 15°."
              style={toolBtnStyle({ accent: "#9ec3ff", active: tool === "wall" })}
            >
              + Wall
            </button>
            <button
              type="button"
              onClick={() => setTool("boxroom")}
              title="+ Box Room. Drag a rectangle to drop four walls forming a sub-room (office, server closet, lab annex). Single undo step."
              style={toolBtnStyle({ accent: "#9ec3ff", active: tool === "boxroom" })}
            >
              + Box Room
            </button>
            <span style={{ width: 1, height: 18, background: "rgba(255,255,255,0.08)", margin: "0 4px" }} />
            {/* Capability-driven: shown only when a live adapter advertises
                `calibration`. No hardcoded wifi assumption. */}
            {calibrationCap && (
              <button
                type="button"
                disabled={calibrationCap.state && calibrationCap.state !== "live"}
                onClick={() => setTool(tool === "calibrate" ? "select" : "calibrate")}
                title={
                  calibrationCap.state && calibrationCap.state !== "live"
                    ? `${calibrationCap.name} adapter is ${calibrationCap.state}; calibration unavailable.`
                    : "Calibrate WiFi path-loss per AP. Click on the canvas where you are standing; the adapter records 10 raw scans and stores a sample. Repeat at 8 to 12 points covering each AP from at least 3 distances."
                }
                style={toolBtnStyle({ accent: "#5dffb0", active: tool === "calibrate" })}
              >
                ↹ calibrate
              </button>
            )}
            {/* One SYNC per adapter advertising `discover`, labelled by source.
                Add a vendor with discover:true and its button appears here,
                no frontend change. */}
            {discoverCaps.map((cap) => {
              const src = cap.capabilities?.source || cap.name;
              const offline = cap.state && cap.state !== "live";
              return (
                <button
                  key={cap.name}
                  type="button"
                  disabled={offline}
                  onClick={() => setTool(tool === "vendorsync" ? "select" : "vendorsync")}
                  title={
                    offline
                      ? `${src} adapter is ${cap.state}; sync unavailable.`
                      : `Sync ${src} anchors from the cloud. The placement editor calls the adapter's discover endpoint and offers to drop each cloud device at its reported position.`
                  }
                  style={toolBtnStyle({ accent: "#c084fc", active: tool === "vendorsync" })}
                >
                  ↻ sync {src}
                </button>
              );
            })}

            {/* Floor-plan image background toggle + opacity. Only shown when
                the active floor plan actually has an image attached - no
                point exposing the control otherwise. */}
            {currentFp?.image?.data_url && (
              <>
                <span style={{ width: 1, height: 18, background: "rgba(255,255,255,0.08)", margin: "0 4px" }} />
                <button
                  type="button"
                  onClick={() => setBgImageEnabled((v) => !v)}
                  title="Show the section 2 floor-plan image under the grid (cropped to this room)"
                  style={toolBtnStyle({
                    accent: bgImageEnabled ? "#5dffb0" : "#9aa9c4",
                    active: bgImageEnabled,
                    secondary: true,
                  })}
                >
                  {bgImageEnabled ? "✓ floor img" : "+ floor img"}
                </button>
                {bgImageEnabled && (
                  <input
                    type="range"
                    min="0.05"
                    max="1"
                    step="0.05"
                    value={bgImageOpacity}
                    onChange={(e) => setBgImageOpacity(Number(e.target.value))}
                    title={`Floor-plan image opacity · ${Math.round(bgImageOpacity * 100)}%`}
                    style={{ width: 100, accentColor: "#5dffb0" }}
                  />
                )}
              </>
            )}

            <div style={{ marginLeft: "auto", fontSize: 10, color: "#7a8aab", fontFamily: "ui-monospace, monospace" }}>
              {tool === "select"
                ? "Click to select · click selected to drag · empty space deselects"
                : tool === "wall"
                ? "Click + drag to draw a wall · Shift = 15° angle snap"
                : tool === "boxroom"
                ? "Drag a rectangle to drop 4 walls forming a sub-room"
                : tool === "calibrate"
                ? "Click where you are standing · the adapter records 10 raw scans"
                : isAnchorTool(tool)
                ? `Click in the canvas to place a ${techMeta(toolTech(tool)).label} anchor`
                : ""}
            </div>
          </div>
        <svg
          ref={svgRef}
          viewBox={vb}
          preserveAspectRatio="xMidYMid meet"
          width="100%"
          style={{
            // Fill the remaining column height below the action bar (the
            // wrapper is a flex column sized to the content cell), so the
            // canvas never over/undershoots a magic viewport offset.
            flex: 1,
            minHeight: 0,
            background: "#070b18",
            borderRadius: 10,
            border: "1px solid rgba(58,130,255,0.2)",
            touchAction: "none",
            cursor:
              tool === "wall" || tool === "boxroom" || tool === "calibrate" || isAnchorTool(tool) ? "crosshair" : "default",
            display: "block",
            userSelect: "none",
            WebkitUserSelect: "none",
            WebkitUserDrag: "none",
          }}
          onDragStart={(e) => e.preventDefault()}
          onPointerDown={onCanvasPointerDown}
          onPointerMove={onCanvasPointerMove}
          onPointerUp={onCanvasPointerUp}
          onPointerLeave={onCanvasPointerUp}
        >
          <defs>
            <pattern id="grid" width="0.5" height="0.5" patternUnits="userSpaceOnUse">
              <path d="M 0.5 0 L 0 0 0 0.5" fill="none" stroke="#152549" strokeWidth="0.02" />
            </pattern>
            <pattern id="gridMajor" width="1" height="1" patternUnits="userSpaceOnUse">
              <path d="M 1 0 L 0 0 0 1" fill="none" stroke="#1d3160" strokeWidth="0.03" />
            </pattern>
            <pattern id="gridSection" width="5" height="5" patternUnits="userSpaceOnUse">
              <path d="M 5 0 L 0 0 0 5" fill="none" stroke="#3a82ff" strokeWidth="0.06" />
            </pattern>
            {/* Room-shape clip - keeps the floor-plan background image from
                bleeding outside the room footprint. Polygon when shape is
                defined, rectangle otherwise. */}
            <clipPath id="roomClip" clipPathUnits="userSpaceOnUse">
              {Array.isArray(currentRoom?.shape) && currentRoom.shape.length >= 3 ? (
                <polygon
                  points={currentRoom.shape
                    .map((p) => `${p[0] - Number(currentRoom.x_m)},${p[1] - Number(currentRoom.y_m)}`)
                    .join(" ")}
                />
              ) : (
                <rect x="0" y="0" width={w} height={h} />
              )}
            </clipPath>
          </defs>

          {/* Floor-plan image background. Two layers:
              1. Peripheral context - full image, unclipped, dimmed to ~25%
                 of the user-chosen opacity so the room sits inside a
                 visible-but-faded surround. Helps orient where the room
                 lives on the plan without competing with the working area.
              2. Room-clipped image at full opacity, drawn on top.
              The image lives in floor-plan-local metres at
              (0,0)→(fp.width_m, fp.height_m); we translate by
              (-room.x_m, -room.y_m) into the room-local frame. Room
              rotation is intentionally ignored here - section 3 always
              renders the room axis-aligned. */}
          {bgImageEnabled &&
            currentFp?.image?.data_url &&
            currentRoom &&
            Number(currentFp.georef?.width_m) > 0 &&
            Number(currentFp.georef?.height_m) > 0 && (
              <g style={{ pointerEvents: "none" }}>
                <image
                  href={currentFp.image.data_url}
                  x={-Number(currentRoom.x_m)}
                  y={-Number(currentRoom.y_m)}
                  width={Number(currentFp.georef.width_m)}
                  height={Number(currentFp.georef.height_m)}
                  preserveAspectRatio="none"
                  opacity={bgImageOpacity * 0.25}
                />
                <g clipPath="url(#roomClip)">
                  <image
                    href={currentFp.image.data_url}
                    x={-Number(currentRoom.x_m)}
                    y={-Number(currentRoom.y_m)}
                    width={Number(currentFp.georef.width_m)}
                    height={Number(currentFp.georef.height_m)}
                    preserveAspectRatio="none"
                    opacity={bgImageOpacity}
                  />
                </g>
              </g>
            )}
          {/* Background grid + room outline. pointer-events:none on all of
              them so clicks pass through to the <svg> root - that's where
              onCanvasPointerDown deselects (in select mode) or starts a wall
              draw (in wall mode). Without this, any background click hits
              the grid rect first and the canvas-level handler short-circuits. */}
          <rect
            x={-MARGIN_M}
            y={-MARGIN_M}
            width={w + 2 * MARGIN_M}
            height={h + 2 * MARGIN_M}
            fill="url(#grid)"
            style={{ pointerEvents: "none" }}
          />
          <rect
            x={-MARGIN_M}
            y={-MARGIN_M}
            width={w + 2 * MARGIN_M}
            height={h + 2 * MARGIN_M}
            fill="url(#gridMajor)"
            style={{ pointerEvents: "none" }}
          />
          <rect
            x={-MARGIN_M}
            y={-MARGIN_M}
            width={w + 2 * MARGIN_M}
            height={h + 2 * MARGIN_M}
            fill="url(#gridSection)"
            style={{ pointerEvents: "none" }}
          />

          {/* room outline + perimeter openings. The fill stays solid so
              the room area reads as one surface; the stroke is split into
              4 sides which we cut around any perimeter_openings entries.
              Each opening is also marked with two small perpendicular
              ticks so it reads as a door / corridor gap on the canvas. */}
          <rect
            x="0"
            y="0"
            width={w}
            height={h}
            fill="rgba(58,130,255,0.05)"
            stroke="none"
            style={{ pointerEvents: "none" }}
          />
          {(() => {
            const stroke = "#7fb3ff";
            const sw = 0.08;
            const perim = currentRoom?.perimeter_openings || [];
            const edges = perimeterEdges(currentRoom);
            const segments = [];
            const tickMarks = [];
            for (let idx = 0; idx < edges.length; idx++) {
              const edge = edges[idx];
              const { length: len, start: p0, dir } = edge;
              // Outward normal: 90° CW rotation of the edge direction.
              // Holds for both rectangle (where the explicit normals used
              // to be) and polygon edges so long as the polygon is wound
              // CW around its area. For CCW polygons the ticks render on
              // the inside - visual only, no correctness impact.
              const normal = [dir[1], -dir[0]];
              const opens = perim
                .filter((o) => Number(o.edge_index) === idx)
                .map((o) => {
                  const a = Math.max(0, Math.min(len, Number(o.start_m) || 0));
                  const b = Math.max(0, Math.min(len, Number(o.end_m) || 0));
                  return { ...o, start_m: Math.min(a, b), end_m: Math.max(a, b) };
                })
                .filter((o) => o.end_m - o.start_m > 0.02)
                .sort((a, b) => a.start_m - b.start_m);
              const merged = [];
              for (const o of opens) {
                const last = merged[merged.length - 1];
                if (last && o.start_m <= last.end_m) {
                  last.end_m = Math.max(last.end_m, o.end_m);
                } else {
                  merged.push({ ...o });
                }
              }
              let cursor = 0;
              const lerp = (m) => [p0[0] + dir[0] * m, p0[1] + dir[1] * m];
              for (const o of merged) {
                if (o.start_m > cursor + 0.01) {
                  const [sx, sy] = lerp(cursor);
                  const [ex, ey] = lerp(o.start_m);
                  segments.push([sx, sy, ex, ey]);
                }
                const [ax, ay] = lerp(o.start_m);
                const [bx, by] = lerp(o.end_m);
                const tlen = 0.35;
                tickMarks.push([
                  ax - normal[0] * tlen,
                  ay - normal[1] * tlen,
                  ax + normal[0] * tlen,
                  ay + normal[1] * tlen,
                ]);
                tickMarks.push([
                  bx - normal[0] * tlen,
                  by - normal[1] * tlen,
                  bx + normal[0] * tlen,
                  by + normal[1] * tlen,
                ]);
                cursor = Math.max(cursor, o.end_m);
              }
              if (cursor < len - 0.01) {
                const [sx, sy] = lerp(cursor);
                const [ex, ey] = lerp(len);
                segments.push([sx, sy, ex, ey]);
              }
            }
            return (
              <g style={{ pointerEvents: "none" }}>
                {segments.map(([x1, y1, x2, y2], i) => (
                  <line
                    key={`ps${i}`}
                    x1={x1}
                    y1={y1}
                    x2={x2}
                    y2={y2}
                    stroke={stroke}
                    strokeWidth={sw}
                    strokeLinecap="butt"
                  />
                ))}
                {tickMarks.map(([x1, y1, x2, y2], i) => (
                  <line
                    key={`pt${i}`}
                    x1={x1}
                    y1={y1}
                    x2={x2}
                    y2={y2}
                    stroke={stroke}
                    strokeWidth={sw * 0.7}
                    strokeLinecap="round"
                    opacity={0.85}
                  />
                ))}
              </g>
            );
          })()}

          {/* tick labels on x axis */}
          {Array.from({ length: Math.floor(w / 5) + 1 }).map((_, i) => {
            const x = i * 5;
            return (
              <text
                key={`xt-${i}`}
                x={x}
                y={-0.5}
                fontSize="0.55"
                fill="#7a8aab"
                textAnchor="middle"
                fontFamily="ui-monospace, monospace"
                style={{ pointerEvents: "none" }}
              >
                {x}
              </text>
            );
          })}
          {/* tick labels on y axis */}
          {Array.from({ length: Math.floor(h / 5) + 1 }).map((_, i) => {
            const y = i * 5;
            return (
              <text
                key={`yt-${i}`}
                x={-0.6}
                y={y + 0.2}
                fontSize="0.55"
                fill="#7a8aab"
                textAnchor="end"
                fontFamily="ui-monospace, monospace"
                style={{ pointerEvents: "none" }}
              >
                {y}
              </text>
            );
          })}

          {/* origin marker */}
          <circle cx="0" cy="0" r="0.2" fill="#e8eef7" />

          {/* Walls */}
          {walls.map((wall) => {
            const sel = wall.id === selectedWallId;
            const invalid = errorByField.has(`wall:${wall.id}`);
            const thick = Number(wall.thickness) || DEFAULT_WALL_THICKNESS_M;
            const wallStroke = invalid
              ? "#ff6b78"
              : sel
              ? editUnlocked
                ? "#ffb347"
                : "#fff3e0"
              : "#9ec3ff";
            const wallOpacity = invalid ? 0.9 : sel ? 0.95 : 0.75;
            const wallDash = sel && !editUnlocked ? "0.4 0.25" : undefined;
            // Compute solid / opening segments along the wall. Openings are
            // 1-D ranges in metres from (x1, y1); we lerp them back into
            // world coords so the SVG draws solid wall + thin door markers
            // wherever an opening sits. Bad ranges (out of bounds, inverted,
            // overlapping) are clamped + sorted defensively so a half-broken
            // schema still renders.
            const wlen = wallLength(wall);
            const wx = wall.x2 - wall.x1;
            const wy = wall.y2 - wall.y1;
            const lerp = (m) => {
              const t = wlen > 0 ? m / wlen : 0;
              return [wall.x1 + wx * t, wall.y1 + wy * t];
            };
            const rawOpenings = wall.openings || [];
            const cleanOpenings = rawOpenings
              .map((o) => {
                const a = Math.max(0, Math.min(wlen, Number(o.start_m) || 0));
                const b = Math.max(0, Math.min(wlen, Number(o.end_m) || 0));
                return { ...o, start_m: Math.min(a, b), end_m: Math.max(a, b) };
              })
              .filter((o) => o.end_m - o.start_m > 0.02)
              .sort((a, b) => a.start_m - b.start_m);
            // Merge overlapping ranges so the solid-segment list stays
            // monotonic.
            const merged = [];
            for (const o of cleanOpenings) {
              const last = merged[merged.length - 1];
              if (last && o.start_m <= last.end_m) {
                last.end_m = Math.max(last.end_m, o.end_m);
              } else {
                merged.push({ ...o });
              }
            }
            const solidSegments = [];
            let cursor = 0;
            for (const o of merged) {
              if (o.start_m > cursor + 0.01) {
                solidSegments.push([cursor, o.start_m]);
              }
              cursor = Math.max(cursor, o.end_m);
            }
            if (cursor < wlen - 0.01) solidSegments.push([cursor, wlen]);
            return (
              <g
                key={wall.id}
                onPointerDown={(e) => onWallBodyPointerDown(e, wall)}
                style={{
                  cursor:
                    tool === "select"
                      ? sel
                        ? editUnlocked
                          ? "grab"
                          : "pointer"
                        : "pointer"
                      : tool === "wall"
                      ? "crosshair"
                      : "default",
                }}
              >
                {/* Transparent full-length hit line so click anywhere on
                    the wall - including over an opening - selects it. */}
                <line
                  x1={wall.x1}
                  y1={wall.y1}
                  x2={wall.x2}
                  y2={wall.y2}
                  stroke="transparent"
                  strokeWidth={Math.max(0.4, thick)}
                  strokeLinecap="round"
                />
                {/* Solid wall segments - one per gap between openings. */}
                {solidSegments.map(([a, b], i) => {
                  const [sx, sy] = lerp(a);
                  const [ex, ey] = lerp(b);
                  return (
                    <line
                      key={`s${i}`}
                      x1={sx}
                      y1={sy}
                      x2={ex}
                      y2={ey}
                      stroke={wallStroke}
                      strokeWidth={thick}
                      strokeLinecap="round"
                      strokeDasharray={wallDash}
                      opacity={wallOpacity}
                    />
                  );
                })}
                {/* Opening markers - thin perpendicular ticks at each end
                    of the opening, plus a faint connector along the wall
                    so it reads as a gap and not as a missing segment. */}
                {merged.map((o, i) => {
                  const [ax, ay] = lerp(o.start_m);
                  const [bx, by] = lerp(o.end_m);
                  const nx = wlen > 0 ? -wy / wlen : 0;
                  const ny = wlen > 0 ? wx / wlen : 0;
                  const tickLen = thick * 1.6;
                  return (
                    <g key={`o${i}`} style={{ pointerEvents: "none" }}>
                      <line
                        x1={ax}
                        y1={ay}
                        x2={bx}
                        y2={by}
                        stroke={wallStroke}
                        strokeWidth={thick * 0.25}
                        opacity={wallOpacity * 0.4}
                        strokeDasharray="0.15 0.15"
                      />
                      <line
                        x1={ax + nx * tickLen}
                        y1={ay + ny * tickLen}
                        x2={ax - nx * tickLen}
                        y2={ay - ny * tickLen}
                        stroke={wallStroke}
                        strokeWidth={thick * 0.5}
                        strokeLinecap="round"
                        opacity={wallOpacity}
                      />
                      <line
                        x1={bx + nx * tickLen}
                        y1={by + ny * tickLen}
                        x2={bx - nx * tickLen}
                        y2={by - ny * tickLen}
                        stroke={wallStroke}
                        strokeWidth={thick * 0.5}
                        strokeLinecap="round"
                        opacity={wallOpacity}
                      />
                    </g>
                  );
                })}
                {sel && tool === "select" && editUnlocked && (
                  <>
                    <circle
                      cx={wall.x1}
                      cy={wall.y1}
                      r="0.25"
                      fill="#fff3e0"
                      stroke="#3a82ff"
                      strokeWidth="0.05"
                      style={{ cursor: "grab" }}
                      onPointerDown={(e) => onWallEndpointPointerDown(e, wall, "start")}
                    />
                    <circle
                      cx={wall.x2}
                      cy={wall.y2}
                      r="0.25"
                      fill="#fff3e0"
                      stroke="#3a82ff"
                      strokeWidth="0.05"
                      style={{ cursor: "grab" }}
                      onPointerDown={(e) => onWallEndpointPointerDown(e, wall, "end")}
                    />
                    <text
                      x={(wall.x1 + wall.x2) / 2}
                      y={(wall.y1 + wall.y2) / 2 - 0.4}
                      fontSize="0.5"
                      fill="#7a8aab"
                      textAnchor="middle"
                      fontFamily="ui-monospace, monospace"
                      style={{ pointerEvents: "none" }}
                    >
                      {wallLength(wall).toFixed(2)} m
                    </text>
                  </>
                )}
              </g>
            );
          })}

          {/* drawing preview */}
          {drawingPreview && drawingPreview.kind === "wall" && (
            <line
              x1={drawingPreview.x1}
              y1={drawingPreview.y1}
              x2={drawingPreview.x2}
              y2={drawingPreview.y2}
              stroke="#ffb347"
              strokeWidth={DEFAULT_WALL_THICKNESS_M}
              strokeLinecap="round"
              opacity="0.6"
              strokeDasharray="0.3 0.2"
            />
          )}
          {drawingPreview && drawingPreview.kind === "boxroom" && (
            <rect
              x={Math.min(drawingPreview.x1, drawingPreview.x2)}
              y={Math.min(drawingPreview.y1, drawingPreview.y2)}
              width={Math.abs(drawingPreview.x2 - drawingPreview.x1)}
              height={Math.abs(drawingPreview.y2 - drawingPreview.y1)}
              fill="rgba(158,195,255,0.08)"
              stroke="#ffb347"
              strokeWidth={DEFAULT_WALL_THICKNESS_M}
              strokeDasharray="0.3 0.2"
              opacity="0.7"
            />
          )}
          {/* Vendor sync ghost markers (only while the vendorsync tool is
              active). Purple, dashed ring; show the cloud position so the
              operator sees the proposed placement before pressing import. */}
          {tool === "vendorsync" &&
            vendorSyncPreview.map(
              (s) =>
                s.local && (
                  <g key={`cloud-${s.vendor_device_id}`} style={{ pointerEvents: "none" }}>
                    <circle
                      cx={s.local.x}
                      cy={s.local.y}
                      r="0.5"
                      fill="none"
                      stroke="#c084fc"
                      strokeWidth="0.08"
                      strokeDasharray="0.2 0.15"
                      opacity="0.85"
                    />
                    <text
                      x={s.local.x}
                      y={s.local.y - 0.7}
                      fontSize="0.45"
                      fill="#dbc1ff"
                      textAnchor="middle"
                      fontFamily="ui-monospace, monospace"
                    >
                      {s.label || s.vendor_device_id}
                    </text>
                  </g>
                )
            )}

          {/* WiFi calibration sample markers (only while the calibrate
              tool is active, so they do not pollute the regular view). */}
          {tool === "calibrate" &&
            calibrationSamples.map((s) => (
              <g key={s.id} style={{ pointerEvents: "none" }}>
                <circle
                  cx={s.x_m}
                  cy={s.y_m}
                  r="0.25"
                  fill="#5dffb0"
                  stroke="#aaffd6"
                  strokeWidth="0.06"
                  opacity="0.85"
                />
                <text
                  x={s.x_m}
                  y={s.y_m - 0.45}
                  fontSize="0.4"
                  fill="#aaffd6"
                  textAnchor="middle"
                  fontFamily="ui-monospace, monospace"
                >
                  {Object.keys(s.rssi_by_anchor || {}).length}
                </text>
              </g>
            ))}
          {/* Anchors (per-technology colour) */}
          {aps.map((ap) => {
            const sel = ap.id === selectedApId;
            const invalid = apIdInvalid(ap);
            const fill = invalid ? "#ff6b78" : techColor(ap);
            const textFill = techText(ap);
            // Tech-group collapse in the sidebar also ghosts the anchors of
            // that tech on the canvas. The operator can still see their
            // positions for context, but they fade into the background so
            // they don't compete for attention with the active tech.
            const ghosted = !!collapsedTech[techOf(ap)] && !sel;
            return (
              <g
                key={ap.id}
                onPointerDown={(e) => onApPointerDown(e, ap)}
                style={{
                  cursor: sel
                    ? editUnlocked
                      ? "grab"
                      : "pointer"
                    : ghosted
                    ? "default"
                    : "pointer",
                  opacity: ghosted ? 0.18 : 1,
                  pointerEvents: ghosted ? "none" : "auto",
                  transition: "opacity 0.12s",
                }}
              >
                {/* Coverage circle removed - a nominal radius without walls
                    or multipath is a misleading visualisation. The schema
                    still keeps coverage_m per anchor with a per-tech default
                    so the runtime engine + downstream simulator have a
                    starting value, but the editor does not surface it. */}
                <circle
                  cx={ap.x}
                  cy={ap.y}
                  r="0.6"
                  fill={fill}
                  stroke={sel ? (editUnlocked ? "#ffb347" : "#fff3e0") : "transparent"}
                  strokeWidth={sel && editUnlocked ? "0.2" : "0.14"}
                  strokeDasharray={sel && !editUnlocked ? "0.15 0.15" : undefined}
                />
                <text
                  x={ap.x}
                  y={ap.y - 0.9}
                  fontSize="0.65"
                  fill={textFill}
                  textAnchor="middle"
                  fontFamily="ui-monospace, monospace"
                  style={{ pointerEvents: "none" }}
                >
                  {ap.id}
                </text>
                {sel && (
                  <text
                    x={ap.x}
                    y={ap.y + 1.3}
                    fontSize="0.5"
                    fill="#7a8aab"
                    textAnchor="middle"
                    fontFamily="ui-monospace, monospace"
                    style={{ pointerEvents: "none" }}
                  >
                    {ap.x.toFixed(2)}, {ap.y.toFixed(2)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>

          </div>
        {/* Right-rail selection panel always reserved as a flex sibling
            so selecting / deselecting does NOT reflow the canvas. The rail
            is empty (with a faint hint) when nothing is selected, and
            populated when an anchor or wall is. The canvas keeps a fixed
            width through any selection change, which is what the operator
            expects from a precision tool.
            While `tool === "calibrate"`, the rail is taken over by the
            CalibrationPanel instead, because the calibration workflow is
            self-contained (no anchor / wall selection while calibrating). */}
          {tool === "calibrate" ? (
            <div style={{ width: 320, flexShrink: 0 }}>
              <CalibrationPanel
                active
                pendingClick={pendingCalibrationClick}
                onPendingHandled={() => setPendingCalibrationClick(null)}
                anchors={aps}
                onSamplesChanged={setCalibrationSamples}
                onClose={() => setTool("select")}
              />
            </div>
          ) : tool === "vendorsync" ? (
            <div style={{ width: 320, flexShrink: 0 }}>
              <VendorSyncPanel
                active
                room={currentRoom}
                floorPlan={currentFp}
                anchors={aps}
                onPreview={setVendorSyncPreview}
                onClose={() => {
                  setTool("select");
                  setVendorSyncPreview([]);
                }}
                onImport={(spec) => {
                  // Upsert anchor with technology="wittra" (or any UWB
                  // vendor) joined by vendor_device_id. Existing anchors
                  // with the same vendor id are moved to the new cloud
                  // position; new ones get a fresh editor id (UWB01...).
                  mutateRoom((r) => {
                    const anchors = r.anchors || [];
                    const idx = anchors.findIndex(
                      (a) => a.vendor_device_id === spec.vendor_device_id
                    );
                    if (idx >= 0) {
                      const updated = [...anchors];
                      updated[idx] = {
                        ...updated[idx],
                        x: spec.x,
                        y: spec.y,
                        height_m: spec.height_m,
                        label: spec.label || updated[idx].label,
                      };
                      return { ...r, anchors: updated };
                    }
                    const newId = nextApId(anchors.filter(
                      (a) => (a.technology || "wifi") === "wittra"
                    ).map((a) => ({ id: a.id }))) || nextApId(anchors);
                    return {
                      ...r,
                      anchors: [
                        ...anchors,
                        {
                          id: newId,
                          technology: "wittra",
                          x: spec.x,
                          y: spec.y,
                          height_m: spec.height_m,
                          label: spec.label,
                          vendor_device_id: spec.vendor_device_id,
                          vendor: "Wittra",
                          model: "Positioning Beacon",
                        },
                      ],
                    };
                  });
                }}
              />
            </div>
          ) : (
          <aside
            style={{
              width: 300,
              flexShrink: 0,
              maxHeight: "calc(100vh - 156px)",
              overflowY: "auto",
              padding: "10px 12px",
              borderRadius: 8,
              background: "rgba(11,17,32,0.96)",
              border: `1px solid ${
                selectedAp || selectedWall
                  ? "rgba(58,130,255,0.35)"
                  : "rgba(255,255,255,0.04)"
              }`,
              boxShadow: (selectedAp || selectedWall)
                ? "0 6px 24px rgba(0,0,0,0.45)"
                : "none",
              fontSize: 11,
            }}
          >
            {!selectedAp && !selectedWall && (
              <div
                style={{
                  color: "#5a6987",
                  fontSize: 11,
                  textAlign: "center",
                  padding: "40px 16px",
                  lineHeight: 1.6,
                  fontFamily: "ui-monospace, monospace",
                }}
              >
                click an anchor or wall on the canvas to inspect
              </div>
            )}
            {selectedAp && (() => {
              const apTechMeta = techMeta(techOf(selectedAp));
              const subHeader = {
                fontSize: 9,
                color: "#7a8aab",
                letterSpacing: "0.10em",
                textTransform: "uppercase",
                margin: "10px 0 4px",
              };
              return (
                <>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 8,
                      paddingBottom: 8,
                      marginBottom: 4,
                      borderBottom: `1px solid ${apTechMeta.color}33`,
                    }}
                  >
                    <strong
                      style={{
                        color: apTechMeta.color,
                        letterSpacing: "0.06em",
                        fontSize: 12,
                        fontFamily: "ui-monospace, monospace",
                      }}
                    >
                      ● {selectedAp.id}
                    </strong>
                    <button
                      type="button"
                      onClick={() => setSelection(null)}
                      title="Close (Esc)"
                      style={{
                        padding: "2px 6px",
                        background: "transparent",
                        color: "#7a8aab",
                        border: "1px solid rgba(255,255,255,0.1)",
                        borderRadius: 3,
                        fontSize: 10,
                        cursor: "pointer",
                      }}
                    >
                      ✕
                    </button>
                  </div>

                  <EditLockToggle
                    unlocked={editUnlocked}
                    onToggle={() => setEditUnlocked((v) => !v)}
                    accent={apTechMeta.color}
                  />

                  <div style={subHeader}>· identity</div>
                  <div style={field}>
                    <span style={label}>id</span>
                    <TextInput
                      value={selectedAp.id}
                      invalid={apIdInvalid(selectedAp)}
                      onCommit={(v) => v && v !== selectedAp.id && renameAp(selectedAp.id, v)}
                    />
                  </div>
                  <div style={field}>
                    <span style={label}>tech</span>
                    <select
                      style={inputStyle(false)}
                      value={techOf(selectedAp)}
                      onChange={(e) => updateAp(selectedAp.id, { technology: e.target.value })}
                    >
                      {TECH_KEYS.map((t) => (
                        <option key={t} value={t}>{techMeta(t).label}</option>
                      ))}
                    </select>
                  </div>

                  <div style={subHeader}>· position (m, from room ⌐)</div>
                  <div style={field}>
                    <span style={label}>x</span>
                    <NumberInput
                      value={selectedAp.x}
                      step="0.1"
                      onCommit={(v) => updateAp(selectedAp.id, { x: v })}
                    />
                  </div>
                  <div style={field}>
                    <span style={label}>y</span>
                    <NumberInput
                      value={selectedAp.y}
                      step="0.1"
                      onCommit={(v) => updateAp(selectedAp.id, { y: v })}
                    />
                  </div>

                  <div style={subHeader}>· height (m)</div>
                  <div style={field}>
                    <span style={label}>height</span>
                    <NumberInput
                      value={selectedAp.height_m ?? apTechMeta.default_height_m}
                      step="0.1"
                      onCommit={(v) => updateAp(selectedAp.id, { height_m: v })}
                    />
                  </div>

                  <div style={subHeader}>· device</div>
                  <div style={field}>
                    <span style={label}>vendor</span>
                    <TextInput
                      value={selectedAp.vendor}
                      onCommit={(v) => updateAp(selectedAp.id, { vendor: v })}
                    />
                  </div>
                  <div style={field}>
                    <span style={label}>model</span>
                    <TextInput
                      value={selectedAp.model}
                      onCommit={(v) => updateAp(selectedAp.id, { model: v })}
                    />
                  </div>

                  {techOf(selectedAp) === "wifi" && (
                    <>
                      <div style={subHeader}>· radio</div>
                      <div style={field}>
                        <span style={label}>band</span>
                        <TextInput
                          value={selectedAp.band}
                          onCommit={(v) => updateAp(selectedAp.id, { band: v })}
                        />
                      </div>
                      <div style={field}>
                        <span style={label}>channel</span>
                        <NumberInput
                          value={selectedAp.channel ?? 0}
                          step="1"
                          onCommit={(v) => updateAp(selectedAp.id, { channel: v })}
                        />
                      </div>
                      <div style={field}>
                        <span style={label}>tx dBm</span>
                        <NumberInput
                          value={selectedAp.tx_power_dbm ?? 0}
                          step="1"
                          onCommit={(v) => updateAp(selectedAp.id, { tx_power_dbm: v })}
                        />
                      </div>
                    </>
                  )}

                  {currentRoom && currentFp?.georef?.latitude != null &&
                    currentFp?.georef?.longitude != null &&
                    Number(currentFp.georef.width_m) > 0 &&
                    Number(currentFp.georef.height_m) > 0 && (() => {
                      const rot = (Number(currentRoom.rotation_deg) || 0) * Math.PI / 180;
                      const cx = Number(currentRoom.x_m) + Number(currentRoom.width_m) / 2;
                      const cy = Number(currentRoom.y_m) + Number(currentRoom.height_m) / 2;
                      const dx = Number(currentRoom.x_m) + Number(selectedAp.x) - cx;
                      const dy = Number(currentRoom.y_m) + Number(selectedAp.y) - cy;
                      const fpx = cx + dx * Math.cos(rot) - dy * Math.sin(rot);
                      const fpy = cy + dx * Math.sin(rot) + dy * Math.cos(rot);
                      const wp = localToGps(fpx, fpy, {
                        latitude: Number(currentFp.georef.latitude),
                        longitude: Number(currentFp.georef.longitude),
                        azimuth_deg: Number(currentFp.georef.azimuth_deg) || 0,
                      });
                      return (
                        <>
                          <div style={subHeader}>· world position</div>
                          <div
                            style={{
                              fontFamily: "ui-monospace, monospace",
                              fontSize: 11,
                              color: "#9ec3ff",
                              lineHeight: 1.5,
                            }}
                          >
                            lat {wp.lat.toFixed(6)}
                            <br />
                            lon {wp.lng.toFixed(6)}
                          </div>
                        </>
                      );
                    })()}

                  <ConfirmDelete
                    armed={confirmDelete === `ap:${selectedAp.id}`}
                    label="delete anchor"
                    onArm={() => setConfirmDelete(`ap:${selectedAp.id}`)}
                    onConfirm={() => {
                      removeAp(selectedAp.id);
                      setConfirmDelete(null);
                    }}
                    onCancel={() => setConfirmDelete(null)}
                  />
                </>
              );
            })()}

            {selectedWall && !selectedAp && (
              <>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                    paddingBottom: 8,
                    marginBottom: 4,
                    borderBottom: "1px solid rgba(158,195,255,0.25)",
                  }}
                >
                  <strong
                    style={{
                      color: "#9ec3ff",
                      letterSpacing: "0.06em",
                      fontSize: 12,
                      fontFamily: "ui-monospace, monospace",
                    }}
                  >
                    ▬ {selectedWall.id}
                  </strong>
                  <button
                    type="button"
                    onClick={() => setSelection(null)}
                    title="Close (Esc)"
                    style={{
                      padding: "2px 6px",
                      background: "transparent",
                      color: "#7a8aab",
                      border: "1px solid rgba(255,255,255,0.1)",
                      borderRadius: 3,
                      fontSize: 10,
                      cursor: "pointer",
                    }}
                  >
                    ✕
                  </button>
                </div>
                <EditLockToggle
                  unlocked={editUnlocked}
                  onToggle={() => setEditUnlocked((v) => !v)}
                  accent="#9ec3ff"
                />
                <div style={field}>
                  <span style={label}>id</span>
                  <TextInput
                    value={selectedWall.id}
                    invalid={errorByField.has(`wall:${selectedWall.id}`)}
                    onCommit={(v) => v && v !== selectedWall.id && renameWall(selectedWall.id, v)}
                  />
                </div>
                <div style={field}>
                  <span style={label}>x1</span>
                  <NumberInput value={selectedWall.x1} step="0.1" onCommit={(v) => updateWall(selectedWall.id, { x1: v })} />
                </div>
                <div style={field}>
                  <span style={label}>y1</span>
                  <NumberInput value={selectedWall.y1} step="0.1" onCommit={(v) => updateWall(selectedWall.id, { y1: v })} />
                </div>
                <div style={field}>
                  <span style={label}>x2</span>
                  <NumberInput value={selectedWall.x2} step="0.1" onCommit={(v) => updateWall(selectedWall.id, { x2: v })} />
                </div>
                <div style={field}>
                  <span style={label}>y2</span>
                  <NumberInput value={selectedWall.y2} step="0.1" onCommit={(v) => updateWall(selectedWall.id, { y2: v })} />
                </div>
                <div style={field}>
                  <span style={label}>thick</span>
                  <NumberInput
                    value={selectedWall.thickness ?? DEFAULT_WALL_THICKNESS_M}
                    step="0.05"
                    min={0.05}
                    onCommit={(v) => updateWall(selectedWall.id, { thickness: v })}
                  />
                </div>
                <div style={field}>
                  <span style={label}>height</span>
                  <NumberInput
                    value={
                      selectedWall.height_m ??
                      currentRoom?.wall_height_m ??
                      DEFAULT_WALL_HEIGHT_M
                    }
                    step="0.1"
                    min={0.1}
                    onCommit={(v) => updateWall(selectedWall.id, { height_m: v })}
                  />
                </div>

                {/* Openings on this wall - doors / windows / pass-throughs.
                    Stored as 1-D ranges along the wall (start_m, end_m) plus
                    vertical extent (sill_m, height_m). Operators add openings
                    by clicking the wall and pressing "+ opening" - initial
                    range is the middle 1 m of the wall, then refined here or
                    by dragging the endpoints on the canvas. */}
                {(() => {
                  const wallLenM = wallLength(selectedWall);
                  const openings = selectedWall.openings || [];
                  const subHeader = {
                    fontSize: 9,
                    color: "#7a8aab",
                    letterSpacing: "0.10em",
                    textTransform: "uppercase",
                    margin: "10px 0 4px",
                  };
                  return (
                    <>
                      <div
                        style={{
                          ...subHeader,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                        }}
                      >
                        <span>· openings ({openings.length})</span>
                        <button
                          type="button"
                          disabled={!editUnlocked || wallLenM < 0.4}
                          onClick={() => {
                            const center = wallLenM / 2;
                            const span = Math.min(1.0, Math.max(0.3, wallLenM * 0.3));
                            const start = +(center - span / 2).toFixed(2);
                            const end = +(center + span / 2).toFixed(2);
                            addOpening(selectedWall.id, {
                              id: nextOpeningId(openings),
                              start_m: start,
                              end_m: end,
                              height_m: DEFAULT_OPENING_HEIGHT_M,
                              sill_m: 0,
                            });
                          }}
                          title={
                            editUnlocked
                              ? "Add a door / window on this wall"
                              : "Unlock the wall to edit openings"
                          }
                          style={{
                            padding: "2px 8px",
                            background: "transparent",
                            color: editUnlocked ? "#9ec3ff" : "#5a6987",
                            border: `1px solid ${
                              editUnlocked ? "#9ec3ff55" : "rgba(255,255,255,0.1)"
                            }`,
                            borderRadius: 3,
                            fontSize: 10,
                            fontFamily: "ui-monospace, monospace",
                            letterSpacing: "0.06em",
                            cursor: editUnlocked && wallLenM >= 0.4 ? "pointer" : "not-allowed",
                            opacity: wallLenM < 0.4 ? 0.5 : 1,
                          }}
                        >
                          + opening
                        </button>
                      </div>
                      {openings.length === 0 && (
                        <div style={{ color: "#5a6987", fontSize: 10, padding: "4px 0" }}>
                          no openings - solid wall
                        </div>
                      )}
                      {openings.map((o) => (
                        <div
                          key={o.id}
                          style={{
                            marginBottom: 6,
                            padding: "6px 8px",
                            borderRadius: 4,
                            background: "rgba(158,195,255,0.05)",
                            border: "1px solid rgba(158,195,255,0.15)",
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "space-between",
                              gap: 6,
                              marginBottom: 4,
                            }}
                          >
                            <strong
                              style={{
                                color: "#9ec3ff",
                                fontSize: 10,
                                fontFamily: "ui-monospace, monospace",
                                letterSpacing: "0.04em",
                              }}
                            >
                              {o.id}
                            </strong>
                            <button
                              type="button"
                              onClick={() => removeOpening(selectedWall.id, o.id)}
                              title="Delete opening"
                              style={{
                                padding: "1px 5px",
                                background: "transparent",
                                color: "#ff6b78",
                                border: "1px solid rgba(255,107,120,0.4)",
                                borderRadius: 3,
                                fontSize: 10,
                                fontFamily: "ui-monospace, monospace",
                                cursor: "pointer",
                              }}
                            >
                              ✕
                            </button>
                          </div>
                          <div style={field}>
                            <span style={label}>start m</span>
                            <NumberInput
                              value={o.start_m}
                              step="0.1"
                              min={0}
                              max={wallLenM}
                              onCommit={(v) =>
                                updateOpening(selectedWall.id, o.id, { start_m: v })
                              }
                            />
                          </div>
                          <div style={field}>
                            <span style={label}>end m</span>
                            <NumberInput
                              value={o.end_m}
                              step="0.1"
                              min={0}
                              max={wallLenM}
                              onCommit={(v) =>
                                updateOpening(selectedWall.id, o.id, { end_m: v })
                              }
                            />
                          </div>
                          <div style={field}>
                            <span style={label}>height</span>
                            <NumberInput
                              value={o.height_m ?? DEFAULT_OPENING_HEIGHT_M}
                              step="0.1"
                              min={0.1}
                              onCommit={(v) =>
                                updateOpening(selectedWall.id, o.id, { height_m: v })
                              }
                            />
                          </div>
                          <div style={field}>
                            <span style={label}>sill</span>
                            <NumberInput
                              value={o.sill_m ?? 0}
                              step="0.1"
                              min={0}
                              onCommit={(v) =>
                                updateOpening(selectedWall.id, o.id, { sill_m: v })
                              }
                            />
                          </div>
                        </div>
                      ))}
                    </>
                  );
                })()}

                <ConfirmDelete
                  armed={confirmDelete === `wall:${selectedWall.id}`}
                  label="delete wall"
                  onArm={() => setConfirmDelete(`wall:${selectedWall.id}`)}
                  onConfirm={() => {
                    removeWall(selectedWall.id);
                    setConfirmDelete(null);
                  }}
                  onCancel={() => setConfirmDelete(null)}
                />
              </>
            )}
          </aside>
          )}
        </div>
        )}
      </div>
      <ToastHost />
    </div>
  );
}
