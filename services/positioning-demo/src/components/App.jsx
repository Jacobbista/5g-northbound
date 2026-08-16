import { useEffect, useMemo, useState } from "react";
import keycloak, { initOptions } from "../keycloak";
import { GPS_ORIGIN_LAT, GPS_ORIGIN_LON } from "../config";
import { useAdapterHealth } from "../hooks/useAdapterHealth";
import { useDevices } from "../hooks/useDevices";
import { useIdlePrompt } from "../hooks/useIdlePrompt";
import { usePositionsStream } from "../hooks/usePositionsStream";
import { useSelection } from "../hooks/useSelection";
import { FloorPlanScene, TECH_KEYS } from "./FloorPlanScene";
import { DetailPanel } from "./DetailPanel";

const M_PER_DEG = 111320;

// Convert a (lat, lng) from the gateway into room-local (x, y) metres for the
// sidebar's lat/lon <-> x/z toggle. Uses the blueprint's floor-plan georef
// (passed as `frame`) so it matches the 3D scene and the engine; falls back to
// the legacy env GPS_ORIGIN only when no blueprint is loaded.
function gpsToLocal(lat, lon, frame) {
  if (frame?.georef) {
    const { lat0, lon0, az, roomX, roomY, fpH } = frame;
    const east = (lon - lon0) * M_PER_DEG * Math.cos((lat0 * Math.PI) / 180);
    const north = (lat - lat0) * M_PER_DEG;
    const xFp = east * Math.cos(az) - north * Math.sin(az);
    const yFp = east * Math.sin(az) + north * Math.cos(az);
    // Match the editor / stored anchors (canvas-y, top-left origin): mirror the
    // georef-frame y about the floor-plan height, then subtract the room base.
    const x = xFp - roomX;
    const z = (fpH - yFp) - roomY;
    return { x, z };
  }
  const x = (lon - GPS_ORIGIN_LON) * M_PER_DEG * Math.cos((GPS_ORIGIN_LAT * Math.PI) / 180);
  const z = (lat - GPS_ORIGIN_LAT) * M_PER_DEG;
  return { x, z };
}

// Build the projection frame from the loaded blueprint, or null.
function frameFromLayout(layout) {
  const g = layout?.floor_plans?.[0]?.georef;
  if (!g || g.latitude == null || g.longitude == null) return null;
  return {
    georef: true,
    lat0: Number(g.latitude),
    lon0: Number(g.longitude),
    az: ((Number(g.azimuth_deg) || 0) * Math.PI) / 180,
    roomX: Number(layout?.rooms?.[0]?.x_m) || 0,
    roomY: Number(layout?.rooms?.[0]?.y_m) || 0,
    fpH: Number(g.height_m) || 0,
  };
}

const TECH_LABEL = { wifi: "WiFi", wittra: "UWB", fiveg: "5G", gnss: "GNSS" };
// Human-readable names for the engine fusion strategies (see
// docs/fusion-strategies.md). Falls back to the raw id for anything unmapped.
const STRATEGY_LABEL = {
  weighted_avg: "Weighted average",
  nearest: "Nearest anchor",
  kalman: "Kalman",
};
const TECH_COLOR = { wifi: "#ffb347", wittra: "#5dffb0", fiveg: "#c084fc", gnss: "#fbbf24" };
const TECH_VIS_KEY = "5g-positioning-demo.visible-techs.v1";

const COORD_KEY = "5g-positioning-demo.coord-mode.v1";

// Adapter: WS payload from the engine broadcast -> the CAMARA-Location-ish
// shape the 3D scene and the sidebar status chips already consume.
function adaptStreamItem(item) {
  if (!item || item.latitude == null || item.longitude == null) return null;
  return {
    lastLocationTime: item.timestamp,
    area: {
      areaType: "CIRCLE",
      center: { latitude: item.latitude, longitude: item.longitude },
      radius: item.accuracy_m,
    },
    sources: item.sources || [],
    strategy: item.strategy,
  };
}

const STALE_MS = 30000;
// Above this reported accuracy the fix is treated as unusable for display
// purposes: a WiFi device far outside the calibrated room still produces a
// "fresh" fix (the trilateration collapses toward the room centre with a
// huge radius), and painting that as a confident live dot misleads the
// viewer. Configurable per deployment via runtime env.
const ACCURACY_MAX_M = Number(
  (typeof window !== "undefined" && window.__ENV__?.VITE_ACCURACY_MAX_M) || 15
);

const shell = {
  height: "100vh",
  overflow: "hidden",
  background: "linear-gradient(180deg, #050816 0%, #0a1228 100%)",
  color: "#e6edf7",
  fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
  display: "grid",
  // Always reserve the right rail (300 px) for the selection panel -
  // selecting / deselecting a device or anchor must not reflow the canvas.
  // Pattern mirrors the placement-editor's room view right rail.
  gridTemplateColumns: "260px minmax(0, 1fr) 320px",
  gridTemplateRows: "auto 1fr",
};

const header = {
  gridColumn: "1 / -1",
  display: "flex",
  alignItems: "center",
  gap: 10,
  // Single row that never wraps into extra height. No overflow:hidden here -
  // it would clip the adapter-health dropdown that opens below the header.
  flexWrap: "nowrap",
  padding: "12px 18px",
  borderBottom: "1px solid rgba(255,255,255,0.06)",
  background: "rgba(10,18,40,0.6)",
  backdropFilter: "blur(8px)",
  // The header is a grid sibling of the 3D scene (and the fixed z40/z50
  // panels). Without a z-index the later-painted scene covers the lower rows
  // of the adapter dropdown that hangs below the header. Lift the whole header
  // stacking context above scene + panels so the dropdown always renders on top.
  position: "relative",
  zIndex: 60,
};

const title = {
  margin: 0,
  fontSize: 16,
  fontWeight: 600,
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  color: "#e6edf7",
};

const subtitle = {
  fontSize: 11,
  color: "#7a8aab",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

const sidebar = {
  padding: "16px 14px",
  borderRight: "1px solid rgba(255,255,255,0.06)",
  background: "rgba(8,14,32,0.5)",
  overflowY: "auto",
};

const sidebarTitle = {
  fontSize: 10,
  color: "#7a8aab",
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  margin: "0 0 10px 4px",
};

const deviceRow = (selected, color) => ({
  display: "grid",
  gridTemplateColumns: "auto 10px 1fr",
  alignItems: "center",
  gap: 10,
  padding: "8px 10px",
  marginBottom: 6,
  borderRadius: 8,
  background: selected ? "rgba(58,130,255,0.06)" : "transparent",
  border: `1px solid ${selected ? `${color}40` : "rgba(255,255,255,0.04)"}`,
  cursor: "pointer",
  fontSize: 12,
});

const dot = (color, glow) => ({
  width: 10,
  height: 10,
  borderRadius: 5,
  background: color,
  boxShadow: glow ? `0 0 8px ${color}` : "none",
});

const statusPill = (state) => {
  const colors = {
    live: { bg: "rgba(93,255,176,0.12)", fg: "#5dffb0", border: "#5dffb0" },
    stale: { bg: "rgba(255,179,71,0.12)", fg: "#ffb347", border: "#ffb347" },
    imprecise: { bg: "rgba(122,138,171,0.14)", fg: "#9aa9c4", border: "#9aa9c4" },
    // No fix arriving for a device the user IS tracking (source silent / stream
    // down). Distinct from `hidden`, which is a deliberate deselect.
    offline: { bg: "rgba(255,107,120,0.10)", fg: "#c98a92", border: "#c98a92" },
    // The user unchecked the device: not shown in the scene, not a data problem.
    hidden: { bg: "transparent", fg: "#5a6987", border: "rgba(122,138,171,0.35)" },
    err: { bg: "rgba(255,107,120,0.12)", fg: "#ff6b78", border: "#ff6b78" },
  };
  const c = colors[state] || colors.offline;
  return {
    fontSize: 9,
    padding: "2px 6px",
    borderRadius: 4,
    background: c.bg,
    color: c.fg,
    border: `1px solid ${c.border}`,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    fontFamily: "ui-monospace, monospace",
  };
};

const adapterBadge = (state) => {
  const colors = {
    ok:       { bg: "rgba(93,255,176,0.10)", fg: "#5dffb0", border: "#5dffb0" },
    degraded: { bg: "rgba(255,107,120,0.12)", fg: "#ff6b78", border: "#ff6b78" },
    unknown:  { bg: "rgba(122,138,171,0.10)", fg: "#7a8aab", border: "#7a8aab" },
  };
  const c = colors[state] || colors.unknown;
  return {
    fontSize: 10,
    padding: "3px 8px",
    borderRadius: 4,
    background: c.bg,
    color: c.fg,
    border: `1px solid ${c.border}`,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    fontFamily: "ui-monospace, monospace",
    marginLeft: 8,
  };
};

const adapterDropdown = {
  position: "absolute",
  top: "calc(100% + 6px)",
  left: 0,
  minWidth: 180,
  padding: 6,
  borderRadius: 8,
  background: "rgba(10,18,40,0.97)",
  border: "1px solid rgba(58,130,255,0.3)",
  boxShadow: "0 8px 28px rgba(0,0,0,0.5)",
  zIndex: 20,
  backdropFilter: "blur(8px)",
};
const adapterRow = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "5px 8px",
  fontSize: 11,
  fontFamily: "ui-monospace, monospace",
};

// Engine registry per-adapter `state`: live / unreachable (polls failing) /
// stale (stopped heartbeating). The badge summarises; clicking opens a panel
// naming each adapter + its state, so "1/3 degraded" says which and why.
function AdapterHealthBadge({ adapters }) {
  const [open, setOpen] = useState(false);
  if (!adapters || adapters.length === 0) {
    return <span style={adapterBadge("unknown")}>adapters n/a</span>;
  }
  const notLive = adapters.filter((a) => (a.state ? a.state !== "live" : a.in_cooldown));
  const ok = notLive.length === 0;
  return (
    // zIndex when open lifts the badge's whole subtree above the z40/z50
    // panels; otherwise the absolutely-positioned dropdown renders behind them.
    <span style={{ position: "relative", display: "inline-flex", zIndex: open ? 80 : undefined }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{ ...adapterBadge(ok ? "ok" : "degraded"), cursor: "pointer" }}
        title="Per-adapter detail"
      >
        {ok
          ? `${adapters.length} adapter${adapters.length === 1 ? "" : "s"} ok`
          : `${notLive.length}/${adapters.length} degraded`}
        <span style={{ marginLeft: 5, opacity: 0.65 }}>{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div style={adapterDropdown}>
          {adapters.map((a) => {
            const live = a.state ? a.state === "live" : !a.in_cooldown;
            const state = a.state || (a.in_cooldown ? "unreachable" : "live");
            const c = live ? "#5dffb0" : "#ff6b78";
            return (
              <div key={a.name} style={adapterRow}>
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: c, flexShrink: 0 }} />
                <span style={{ color: "#e6edf7", fontWeight: 600 }}>{a.name}</span>
                <span style={{ marginLeft: "auto", color: c, textTransform: "uppercase", fontSize: 9, letterSpacing: "0.06em" }}>
                  {state}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </span>
  );
}

const sceneWrap = {
  padding: "16px 20px 20px",
  position: "relative",
  // Fill the grid cell exactly (the row is 1fr); minHeight:0 lets it shrink
  // instead of overflowing the page when the header height varies.
  height: "100%",
  minHeight: 0,
  boxSizing: "border-box",
  userSelect: "none",
  WebkitUserSelect: "none",
};

const coordToggle = {
  display: "inline-flex",
  borderRadius: 6,
  border: "1px solid rgba(255,255,255,0.1)",
  overflow: "hidden",
  marginLeft: "auto",
};

const coordBtn = (active) => ({
  padding: "4px 10px",
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  fontFamily: "ui-monospace, monospace",
  background: active ? "rgba(58,130,255,0.2)" : "transparent",
  color: active ? "#9ec3ff" : "#7a8aab",
  border: "none",
  cursor: "pointer",
});

function deviceState({ position }) {
  // Called only for a SELECTED device; deselected rows show "hidden" upstream.
  if (!position?.lastLocationTime) return "offline";
  const ageMs = Date.now() - new Date(position.lastLocationTime).getTime();
  if (ageMs > STALE_MS) return "stale";
  const radius = position?.area?.radius;
  if (radius != null && radius > ACCURACY_MAX_M) return "imprecise";
  return "live";
}

const standbyPill = {
  fontSize: 9,
  padding: "2px 6px",
  borderRadius: 4,
  background: "rgba(122,138,171,0.12)",
  color: "#7a8aab",
  border: "1px solid #7a8aab",
  letterSpacing: "0.10em",
  textTransform: "uppercase",
  fontFamily: "ui-monospace, monospace",
};

const idleOverlay = {
  position: "fixed",
  inset: 0,
  background: "rgba(5,8,22,0.78)",
  backdropFilter: "blur(4px)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 50,
};

const idleCard = {
  background: "rgba(20,28,52,0.96)",
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: 12,
  padding: "24px 28px",
  maxWidth: 360,
  textAlign: "center",
  color: "#e6edf7",
  fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
};

const idleButton = {
  marginTop: 16,
  padding: "10px 22px",
  background: "rgba(58,130,255,0.2)",
  border: "1px solid #3a82ff",
  color: "#9ec3ff",
  borderRadius: 6,
  fontSize: 13,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  cursor: "pointer",
  fontFamily: "ui-monospace, monospace",
};

function IdlePromptModal({ remainingMs, onAcknowledge }) {
  const secs = Math.ceil(remainingMs / 1000);
  return (
    <div style={idleOverlay} role="alertdialog" aria-modal="true">
      <div style={idleCard}>
        <div style={{ fontSize: 14, letterSpacing: "0.08em", textTransform: "uppercase", color: "#7a8aab" }}>
          inactivity
        </div>
        <div style={{ fontSize: 18, fontWeight: 600, marginTop: 8 }}>Still watching?</div>
        <div style={{ fontSize: 12, color: "#7a8aab", marginTop: 8 }}>
          The position feed will pause in <strong style={{ color: "#ffb347" }}>{secs}s</strong> to save resources.
        </div>
        <button style={idleButton} onClick={onAcknowledge} autoFocus>
          Yes, keep going
        </button>
      </div>
    </div>
  );
}

const standbyOverlay = {
  position: "fixed",
  inset: 0,
  background: "rgba(5,8,22,0.72)",
  backdropFilter: "blur(3px)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 40,
  pointerEvents: "none",
};

function StandbyOverlay() {
  return (
    <div style={standbyOverlay}>
      <div style={{ ...idleCard, pointerEvents: "auto" }}>
        <div style={{ fontSize: 12, letterSpacing: "0.10em", textTransform: "uppercase", color: "#7a8aab" }}>
          standby
        </div>
        <div style={{ fontSize: 16, fontWeight: 600, marginTop: 8 }}>Feed paused</div>
        <div style={{ fontSize: 12, color: "#7a8aab", marginTop: 8 }}>
          Move the mouse or press any key to resume.
        </div>
      </div>
    </div>
  );
}

const mockPill = {
  fontSize: 9,
  padding: "2px 6px",
  borderRadius: 4,
  background: "rgba(255,179,71,0.10)",
  color: "#ffb347",
  border: "1px dashed #ffb347",
  letterSpacing: "0.10em",
  textTransform: "uppercase",
  fontFamily: "ui-monospace, monospace",
};

function DeviceItem({ device, state, position, selected, coordMode, onToggle, frame }) {
  const center = position?.area?.center;
  const coordStr = center
    ? coordMode === "relative"
      ? (() => {
          const p = gpsToLocal(center.latitude, center.longitude, frame);
          return `x=${p.x.toFixed(2)}  z=${p.z.toFixed(2)}`;
        })()
      : `${center.latitude.toFixed(5)}, ${center.longitude.toFixed(5)}`
    : null;
  return (
    <div
      style={deviceRow(selected, device.color)}
      onClick={() => onToggle(device.assetId)}
      role="checkbox"
      aria-checked={selected}
      tabIndex={0}
    >
      <input
        type="checkbox"
        checked={selected}
        readOnly
        style={{ accentColor: device.color, cursor: "pointer" }}
      />
      <span style={dot(device.color, selected)} />
      <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <strong style={{ color: device.color, letterSpacing: "0.04em" }}>{device.label}</strong>
          <span style={statusPill(state)}>{state}</span>
          {device.simulated && (
            <span style={mockPill} title="Synthetic source - demo only">
              mock
            </span>
          )}
        </div>
        <span
          style={{ fontSize: 9, color: "#5a6987", fontFamily: "ui-monospace, monospace", letterSpacing: "0.04em" }}
          title="Asset identity (private-asset profile): assetId · kind · source. No MSISDN/subscriber."
        >
          {device.assetId} · {device.kind} · {device.source}
        </span>
        {selected && coordStr && (
          <span
            style={{
              fontSize: 10,
              color: "#7a8aab",
              fontFamily: "ui-monospace, monospace",
              // Never let an out-of-frame fix (very large x/z) push the row wider
              // than the sidebar; wrap instead of overflowing horizontally.
              overflowWrap: "anywhere",
            }}
          >
            {coordStr}
            {" ±"}
            {position.area.radius?.toFixed(1)}m
          </span>
        )}
      </div>
    </div>
  );
}

export function App() {
  const [token, setToken] = useState(null);
  const [authError, setAuthError] = useState(null);
  const [selection, setSelection] = useState(null);
  const [layout, setLayout] = useState(null);
  // Which technologies actually have at least one anchor in the loaded
  // layout. The header tech toggles only render for these - no point
  // exposing a 5G toggle when there are zero 5G anchors to show / hide.
  const techsWithAnchors = (() => {
    const room = layout?.rooms?.[0];
    const anchors = (room?.anchors ?? layout?.aps) ?? [];
    const present = new Set();
    for (const a of anchors) present.add(a?.technology || "wifi");
    return present;
  })();
  const [coordMode, setCoordMode] = useState(
    () => localStorage.getItem(COORD_KEY) || "absolute"
  );
  const [visibleTechs, setVisibleTechs] = useState(() => {
    try {
      const raw = localStorage.getItem(TECH_VIS_KEY);
      if (raw) return new Set(JSON.parse(raw));
    } catch {
      // fall through to default
    }
    return new Set(TECH_KEYS);
  });

  useEffect(() => {
    localStorage.setItem(TECH_VIS_KEY, JSON.stringify([...visibleTechs]));
  }, [visibleTechs]);

  const toggleTech = (tech) => {
    setVisibleTechs((prev) => {
      const next = new Set(prev);
      if (next.has(tech)) next.delete(tech);
      else next.add(tech);
      return next;
    });
  };

  useEffect(() => {
    localStorage.setItem(COORD_KEY, coordMode);
  }, [coordMode]);

  useEffect(() => {
    keycloak
      .init(initOptions)
      .then((authenticated) => {
        if (authenticated) setToken(keycloak.token);
        else setAuthError("Authentication failed");
      })
      .catch(() => setAuthError("Keycloak init failed"));
  }, []);

  const { state: idleState, promptRemainingMs, acknowledge } = useIdlePrompt();
  const paused = idleState === "standby";

  const { devices, error: devicesError, loading: devicesLoading } = useDevices(token);
  const allAssetIds = devices.map((d) => d.assetId);
  const { isSelected, toggle } = useSelection(allAssetIds);
  const adapters = useAdapterHealth(token, { paused });
  const { byDeviceId, connected } = usePositionsStream(token, { paused });

  // Index every registered asset against the live stream by its internal
  // positioningId (the WS payload key). Assets without a stream entry get
  // null position which the rest of the UI renders as "offline".
  const byAsset = useMemo(() => {
    const out = {};
    for (const d of devices) {
      const streamItem = byDeviceId[d.positioningId];
      out[d.assetId] = {
        device: d,
        position: adaptStreamItem(streamItem),
      };
    }
    return out;
  }, [devices, byDeviceId]);

  // The engine's active fusion strategy, surfaced from the live feed itself
  // (every fix carries it as a private-profile vendor extension). Read from the
  // stream the demo already consumes via the gateway - never a direct engine
  // call (this is a MEC app: gateway only). All fixes share the primary, so any
  // one is representative.
  const activeStrategy = useMemo(() => {
    for (const it of Object.values(byDeviceId)) {
      if (it?.strategy) return it.strategy;
    }
    return null;
  }, [byDeviceId]);

  // Keep the panel content mounted through the close transition so the rail
  // can slide/fade out instead of vanishing. Cleared after the animation.
  const [renderedSelection, setRenderedSelection] = useState(null);
  useEffect(() => {
    if (selection) {
      setRenderedSelection(selection);
      return;
    }
    const id = setTimeout(() => setRenderedSelection(null), 260);
    return () => clearTimeout(id);
  }, [selection]);

  if (authError)
    return <div style={{ ...shell, padding: 24, color: "#ff6b78" }}>{authError}</div>;
  if (!token)
    return <div style={{ ...shell, padding: 24, color: "#7a8aab" }}>Authenticating…</div>;

  const scenePositions = devices
    .filter((d) => isSelected(d.assetId))
    .map((d) => ({
      device: d,
      position: byAsset[d.assetId]?.position,
    }));
  const anyMock = devices.some((d) => d.simulated);

  // Venue metadata, taken from the blueprint (never hardcoded): floor-plan
  // label = the place, room label + extent, georef lat/lon = the location.
  const fp0 = layout?.floor_plans?.[0];
  const room0 = layout?.rooms?.[0];
  const g0 = fp0?.georef;
  const venueName = fp0?.label || null;
  const roomLabel = room0?.label || null;
  const roomDims = room0?.width_m
    ? `${Number(room0.width_m).toFixed(1)}×${Number(room0.height_m).toFixed(1)} m`
    : null;
  const geoStr =
    g0?.latitude != null ? `${Number(g0.latitude).toFixed(5)}, ${Number(g0.longitude).toFixed(5)}` : null;

  return (
    <div
      style={{
        ...shell,
        // Two columns only: sidebar + full-width scene. The detail panel is a
        // floating overlay on the scene (see below), so selecting never resizes
        // the canvas - no demand-mode resize jank, scene always uses full width.
        gridTemplateColumns: "260px minmax(0, 1fr)",
      }}
    >
      <header style={header}>
        <div
          style={dot(connected ? "#5dffb0" : "#7a8aab", connected)}
          title={connected ? "Live position feed connected" : "Position feed disconnected - reconnecting"}
        />
        <h2 style={title}>Asset Location</h2>
        <span style={subtitle}>· CAMARA Device Location · {connected ? "live" : "offline"}</span>
        {activeStrategy && (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: 10,
              color: "#9ec3ff",
              fontFamily: "ui-monospace, monospace",
              padding: "2px 8px",
              borderRadius: 6,
              border: "1px solid rgba(58,130,255,0.3)",
              background: "rgba(58,130,255,0.08)",
              letterSpacing: "0.06em",
              textTransform: "uppercase",
            }}
            title={`Engine fusion strategy in effect (private-profile vendor extension, id: ${activeStrategy}). Every fix in the feed is produced by this strategy.`}
          >
            <span style={{ opacity: 0.6 }}>fusion</span>
            {STRATEGY_LABEL[activeStrategy] || activeStrategy}
          </span>
        )}
        {venueName && (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: 11,
              color: "#9aa9c4",
              fontFamily: "ui-monospace, monospace",
              padding: "2px 8px",
              borderRadius: 6,
              border: "1px solid rgba(255,255,255,0.08)",
              background: "rgba(255,255,255,0.03)",
            }}
            title={geoStr ? `Location: ${geoStr}` : undefined}
          >
            <span style={{ opacity: 0.7 }}>📍</span>
            <span style={{ color: "#cdd7ea" }}>{venueName}</span>
            {roomLabel && <span style={{ opacity: 0.6 }}>· {roomLabel}</span>}
            {roomDims && <span style={{ opacity: 0.5 }}>· {roomDims}</span>}
          </span>
        )}
        {anyMock && (
          <span
            style={mockPill}
            title="At least one registered device is wired to a synthetic data source (mock-positioning / mock-wittra). Real deployments do not ship with these."
          >
            demo build
          </span>
        )}
        {idleState === "standby" && (
          <span style={standbyPill} title="Polling paused while idle. Any input resumes the feed.">
            standby
          </span>
        )}
        <AdapterHealthBadge adapters={adapters} />
        <div style={{ display: "inline-flex", gap: 4, marginLeft: 8 }}>
          {TECH_KEYS.filter((t) => techsWithAnchors.has(t)).map((tech) => {
            const active = visibleTechs.has(tech);
            const c = TECH_COLOR[tech];
            return (
              <button
                key={tech}
                onClick={() => toggleTech(tech)}
                title={`${active ? "Hide" : "Show"} ${TECH_LABEL[tech]} anchors in the scene`}
                style={{
                  padding: "3px 8px",
                  borderRadius: 4,
                  border: `1px solid ${active ? c : "#7a8aab44"}`,
                  background: active ? `${c}1a` : "transparent",
                  color: active ? c : "#7a8aab",
                  fontSize: 10,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  fontFamily: "ui-monospace, monospace",
                  cursor: "pointer",
                  opacity: active ? 1 : 0.55,
                }}
              >
                {TECH_LABEL[tech]}
              </button>
            );
          })}
        </div>
        <div style={{ ...coordToggle, marginLeft: "auto" }}>
          <button
            style={coordBtn(coordMode === "absolute")}
            onClick={() => setCoordMode("absolute")}
          >
            lat/lon
          </button>
          <button
            style={coordBtn(coordMode === "relative")}
            onClick={() => setCoordMode("relative")}
          >
            x/z (m)
          </button>
        </div>
      </header>

      <aside style={sidebar}>
        <h3 style={sidebarTitle}>Devices</h3>
        {devicesLoading && <div style={{ color: "#7a8aab", fontSize: 12, padding: 10 }}>loading…</div>}
        {devicesError && (
          <div style={{ color: "#ff6b78", fontSize: 12, padding: 10 }}>
            discovery failed: {devicesError}
          </div>
        )}
        {!devicesLoading && devices.length === 0 && !devicesError && (
          <div style={{ color: "#7a8aab", fontSize: 12, padding: 10 }}>no devices registered</div>
        )}
        {devices.map((d) => {
          const selected = isSelected(d.assetId);
          const entry = byAsset[d.assetId];
          return (
            <div key={d.assetId}>
              <DeviceItem
                device={d}
                state={selected ? deviceState({ position: entry?.position }) : "hidden"}
                position={entry?.position}
                selected={selected}
                coordMode={coordMode}
                onToggle={toggle}
                frame={frameFromLayout(layout)}
              />
            </div>
          );
        })}
      </aside>

      <div style={sceneWrap}>
        <FloorPlanScene
          token={token}
          positions={scenePositions}
          visibleTechs={visibleTechs}
          onSelectDevice={(d) => setSelection(d ? { kind: "device", device: d } : null)}
          onSelectAp={(ap) => setSelection({ kind: "ap", ap })}
          onLayoutLoaded={setLayout}
        />
        {/* Floating overlay on the scene - never resizes the canvas. */}
        <div
          style={{
            position: "absolute",
            top: 28,
            right: 32,
            width: 340,
            maxHeight: "calc(100vh - 200px)",
            overflowY: "auto",
            overflowX: "hidden",
            boxSizing: "border-box",
            zIndex: 5,
            opacity: selection ? 1 : 0,
            transform: selection ? "translateX(0)" : "translateX(20px)",
            transition: "transform 240ms cubic-bezier(0.22, 1, 0.36, 1), opacity 200ms ease",
            pointerEvents: selection ? "auto" : "none",
          }}
        >
          {renderedSelection && (
            <DetailPanel
              selection={renderedSelection}
              token={token}
              coordMode={coordMode}
              frame={frameFromLayout(layout)}
              onClose={() => setSelection(null)}
            />
          )}
        </div>
      </div>
      {idleState === "prompting" && (
        <IdlePromptModal remainingMs={promptRemainingMs} onAcknowledge={acknowledge} />
      )}
      {idleState === "standby" && <StandbyOverlay />}
    </div>
  );
}
