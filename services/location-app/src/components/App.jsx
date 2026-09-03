import { useEffect, useMemo, useRef, useState } from "react";
import keycloak, { initOptions } from "../keycloak";
import { GPS_ORIGIN_LAT, GPS_ORIGIN_LON } from "../config";
import { useAdapterHealth } from "../hooks/useAdapterHealth";
import { useDevices } from "../hooks/useDevices";
import { useIdlePrompt } from "../hooks/useIdlePrompt";
import { usePositionsStream } from "../hooks/usePositionsStream";
import { useSelection } from "../hooks/useSelection";
import { useDeviceDiagnostics } from "../hooks/useDeviceDiagnostics";
import { relevantAnchorIds as computeRelevant } from "../lib/relevance";
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
const TECH_VIS_KEY = "5g-location-app.visible-techs.v1";

// Scene controls live in the header (top bar), not floating over the world:
// the recenter button and the per-technology layer toggles / colour legend.
const headerBtn = {
  padding: "5px 11px",
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  fontFamily: "ui-monospace, monospace",
  color: "#9ec3ff",
  background: "rgba(58,130,255,0.10)",
  border: "1px solid rgba(58,130,255,0.35)",
  borderRadius: 6,
  cursor: "pointer",
};
const headerLayers = {
  display: "flex",
  alignItems: "center",
  gap: 4,
  padding: "3px 4px",
  borderRadius: 6,
  border: "1px solid rgba(255,255,255,0.08)",
};
const headerTech = (active, c) => ({
  display: "flex",
  alignItems: "center",
  gap: 6,
  padding: "3px 8px",
  borderRadius: 5,
  background: active ? `${c}1a` : "transparent",
  border: "none",
  cursor: "pointer",
  color: active ? c : "#5a6987",
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  fontFamily: "ui-monospace, monospace",
  opacity: active ? 1 : 0.55,
  transition: "background 140ms ease, opacity 140ms ease, color 140ms ease",
});

// Adapter: WS payload from the engine broadcast -> the CAMARA-Location-ish
// shape the 3D scene and the sidebar status chips already consume.
function adaptStreamItem(item) {
  if (!item || item.latitude == null || item.longitude == null) return null;
  return {
    // Fix time (CAMARA lastLocationTime): freezes while a stationary asset
    // reports the same fix - drives position-age display, NOT liveness.
    lastLocationTime: item.timestamp,
    // When the source last answered (this broadcast tick). Drives liveness, so
    // a still-but-reachable asset stays live. Falls back to the fix time for an
    // older engine that does not emit observed_at.
    observedAt: item.observed_at || item.timestamp,
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
  // The header is a grid sibling of the 3D scene and the detail-panel overlay.
  // Its stacking context must sit above that overlay (z70) so the adapter-health
  // dropdown, which hangs down into the same top-right region, renders over the
  // panel instead of behind it.
  position: "relative",
  zIndex: 80,
};

const railToggle = {
  width: 28,
  height: 28,
  flexShrink: 0,
  display: "grid",
  placeItems: "center",
  borderRadius: 7,
  border: "1px solid rgba(255,255,255,0.12)",
  background: "rgba(255,255,255,0.03)",
  color: "#9aa9c4",
  cursor: "pointer",
  fontSize: 12,
  fontFamily: "ui-monospace, monospace",
  lineHeight: 1,
};

const title = {
  margin: 0,
  fontSize: 16,
  fontWeight: 600,
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  color: "#e6edf7",
};

// Vertical divider that separates the header's three zones (brand · context ·
// controls) so it reads as grouped, not one flat row of chips.
const hDivider = {
  width: 1,
  alignSelf: "stretch",
  margin: "6px 4px",
  background: "rgba(255,255,255,0.09)",
};
// One unified style for the secondary context chips (fusion, venue).
const metaChip = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  fontSize: 10.5,
  color: "#9aa9c4",
  fontFamily: "ui-monospace, monospace",
  padding: "3px 9px",
  borderRadius: 6,
  border: "1px solid rgba(255,255,255,0.08)",
  background: "rgba(255,255,255,0.03)",
  whiteSpace: "nowrap",
};

const subtitle = {
  fontSize: 11,
  color: "#7a8aab",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

// Device rail as a floating overlay on the scene: slides off to the left when
// collapsed, never touching the canvas size (no reflow / recenter).
const sidebarPanel = (open) => ({
  position: "absolute",
  top: 12,
  left: 12,
  width: 236,
  maxHeight: "calc(100% - 24px)",
  overflowY: "auto",
  overflowX: "hidden",
  padding: "12px 12px 14px",
  borderRadius: 12,
  background: "linear-gradient(180deg, rgba(12,20,44,0.92), rgba(8,14,32,0.9))",
  border: "1px solid rgba(58,130,255,0.22)",
  boxShadow: "0 8px 32px rgba(0,0,0,0.45)",
  backdropFilter: "blur(10px)",
  zIndex: 40,
  transform: open ? "translateX(0)" : "translateX(-118%)",
  opacity: open ? 1 : 0,
  pointerEvents: open ? "auto" : "none",
  transition: "transform 260ms cubic-bezier(0.22,1,0.36,1), opacity 200ms ease",
});
const sidebarHead = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  marginBottom: 10,
};
// Reopen tab, shown only when the rail is collapsed.
const railReopen = (open) => ({
  position: "absolute",
  top: 16,
  left: 12,
  zIndex: 39,
  padding: "7px 12px",
  fontSize: 11,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  fontFamily: "ui-monospace, monospace",
  color: "#9ec3ff",
  background: "rgba(10,18,40,0.7)",
  border: "1px solid rgba(58,130,255,0.35)",
  borderRadius: 8,
  cursor: "pointer",
  backdropFilter: "blur(6px)",
  opacity: open ? 0 : 1,
  transform: open ? "translateX(-8px)" : "translateX(0)",
  pointerEvents: open ? "none" : "auto",
  transition: "opacity 180ms ease, transform 180ms ease",
});

const sidebarTitle = {
  fontSize: 10,
  color: "#7a8aab",
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  margin: "0 0 10px 4px",
};

// Device card: a fixed-padding card with a left accent stripe in the device's
// colour and, when shown, the same top-down colour wash the detail panel uses.
// Consistent geometry - only colours change with state, never the box size.
const deviceRow = (selected, color) => ({
  position: "relative",
  display: "flex",
  flexDirection: "column",
  gap: 6,
  padding: "10px 12px",
  marginBottom: 8,
  borderRadius: 10,
  background: selected
    ? `linear-gradient(180deg, ${color}22, rgba(8,14,32,0.55))`
    : "rgba(8,14,32,0.4)",
  border: `1px solid ${selected ? `${color}55` : "rgba(255,255,255,0.06)"}`,
  borderLeft: `3px solid ${selected ? color : "rgba(255,255,255,0.12)"}`,
  cursor: "pointer",
  fontSize: 12,
  transition: "background 160ms ease, border-color 160ms ease",
});

// Show/hide affordance: an eye toggle that reflects and flips scene visibility,
// replacing the checkbox. Filled + coloured when shown, outlined when hidden.
const eyeBtn = (selected, color) => ({
  flexShrink: 0,
  width: 26,
  height: 26,
  display: "grid",
  placeItems: "center",
  borderRadius: 7,
  border: `1px solid ${selected ? `${color}66` : "rgba(255,255,255,0.12)"}`,
  background: selected ? `${color}22` : "transparent",
  color: selected ? color : "#7a8aab",
  cursor: "pointer",
  padding: 0,
  transition: "background 180ms ease, border-color 180ms ease, color 180ms ease",
});

function EyeIcon({ shown }) {
  return shown ? (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  ) : (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  );
}

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
    warn:     { bg: "rgba(255,179,71,0.12)", fg: "#ffb347", border: "#ffb347" },
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
  // The badge sits at the far right of the header - open the panel leftward so
  // it never spills off the right edge of the screen.
  right: 0,
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
  const wrapRef = useRef(null);
  // A glance-and-dismiss popover: an outside click or Escape closes it, not only
  // a second click of the badge.
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  if (!adapters || adapters.length === 0) {
    return <span style={adapterBadge("unknown")}>adapters n/a</span>;
  }
  // Worst severity drives the badge: any sustained outage is red, a fresh miss
  // is amber, otherwise green. Amber keeps a transient blip from looking grave.
  const errors = adapters.filter((a) => a.severity === "error");
  const warns = adapters.filter((a) => a.severity === "warn");
  const notLive = errors.length + warns.length;
  const variant = errors.length ? "degraded" : warns.length ? "warn" : "ok";
  const ok = notLive === 0;
  return (
    // zIndex when open lifts the badge's whole subtree above the z40/z50
    // panels; otherwise the absolutely-positioned dropdown renders behind them.
    <span ref={wrapRef} style={{ position: "relative", display: "inline-flex", zIndex: open ? 80 : undefined }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{ ...adapterBadge(variant), cursor: "pointer" }}
        title="Per-adapter detail"
      >
        {ok
          ? `${adapters.length} adapter${adapters.length === 1 ? "" : "s"} ok`
          : `${notLive}/${adapters.length} degraded`}
        <span style={{ marginLeft: 5, opacity: 0.65 }}>{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div style={adapterDropdown}>
          {adapters.map((a) => {
            const live = a.state ? a.state === "live" : !a.in_cooldown;
            const state = a.state || (a.in_cooldown ? "unreachable" : "live");
            const sev = a.severity || (live ? "ok" : "error");
            const c = sev === "ok" ? "#5dffb0" : sev === "warn" ? "#ffb347" : "#ff6b78";
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

// Faint controls legend, bottom-right of the scene.
const navHint = {
  position: "absolute",
  right: 14,
  bottom: 12,
  zIndex: 25,
  display: "flex",
  gap: 14,
  padding: "6px 12px",
  borderRadius: 8,
  background: "rgba(8,14,32,0.62)",
  border: "1px solid rgba(255,255,255,0.07)",
  backdropFilter: "blur(6px)",
  fontSize: 10,
  color: "#8595b3",
  fontFamily: "ui-monospace, monospace",
  letterSpacing: "0.04em",
  pointerEvents: "none",
};

const sceneWrap = {
  // Full-bleed: the canvas fills the cell edge-to-edge (no framed inset), and
  // the grid fades to the horizon so the world reads as open, not boxed.
  padding: 0,
  position: "relative",
  // Fill the grid cell exactly (the row is 1fr); minHeight:0 lets it shrink
  // instead of overflowing the page when the header height varies.
  height: "100%",
  minHeight: 0,
  boxSizing: "border-box",
  userSelect: "none",
  WebkitUserSelect: "none",
};

function deviceState({ position }) {
  // Called only for a SELECTED device; deselected rows show "hidden" upstream.
  // Liveness is measured from observedAt (when the source last answered), NOT
  // from lastLocationTime (the fix time, which freezes for a stationary asset).
  // A still but reachable asset is live, not stale.
  const liveAt = position?.observedAt || position?.lastLocationTime;
  if (!liveAt) return "offline";
  const ageMs = Date.now() - new Date(liveAt).getTime();
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

function DeviceItem({ device, position, shown, detailOpen, onOpenDetail, onToggleShown, frame }) {
  const center = position?.area?.center;
  // Liveness is intrinsic to the asset, not to whether it is shown: the pill
  // reads live/offline from the stream regardless of the eye toggle.
  const canShow = Boolean(position);
  const state = deviceState({ position });
  const coordStr = (() => {
    if (!center) return null;
    const ll = `${center.latitude.toFixed(5)}, ${center.longitude.toFixed(5)}`;
    const p = gpsToLocal(center.latitude, center.longitude, frame);
    return p ? `${ll} · x=${p.x.toFixed(1)} z=${p.z.toFixed(1)}` : ll;
  })();
  return (
    <div
      // The card opens the detail; the eye toggles scene visibility. A live
      // asset the user has hidden dims; an offline asset stays full (its eye is
      // the disabled part, since there is no marker to show).
      style={{ ...deviceRow(detailOpen, device.color), opacity: canShow && !shown ? 0.55 : 1 }}
      onClick={() => onOpenDetail(device)}
      role="button"
      aria-pressed={detailOpen}
      tabIndex={0}
      title="Open details"
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={dot(device.color, shown && canShow)} />
        <strong
          style={{
            color: device.color,
            letterSpacing: "0.04em",
            flex: 1,
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {device.label}
        </strong>
        <span style={statusPill(state)}>{state}</span>
        <button
          type="button"
          style={{
            ...eyeBtn(shown && canShow, device.color),
            opacity: canShow ? 1 : 0.3,
            cursor: canShow ? "pointer" : "not-allowed",
          }}
          title={!canShow ? "No live fix to show" : shown ? "Hide in the scene" : "Show in the scene"}
          aria-label={shown ? "Hide" : "Show"}
          disabled={!canShow}
          onClick={(e) => {
            e.stopPropagation();
            if (canShow) onToggleShown(device.assetId);
          }}
        >
          <EyeIcon shown={shown && canShow} />
        </button>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span
          style={{ fontSize: 9, color: "#5a6987", fontFamily: "ui-monospace, monospace", letterSpacing: "0.04em" }}
          title="Asset identity (private-asset profile): assetId · kind · source. No MSISDN/subscriber."
        >
          {device.assetId} · {device.kind} · {device.source}
        </span>
        {device.source === "synthetic" && (
          <span style={mockPill} title="Synthetic source - waypoint walker, not real hardware">
            synthetic
          </span>
        )}
      </div>

      {coordStr && (
        <div
          style={{
            marginTop: 4,
            paddingTop: 8,
            borderTop: "1px solid rgba(255,255,255,0.07)",
            display: "flex",
            flexDirection: "column",
            gap: 3,
            fontSize: 10,
            fontFamily: "ui-monospace, monospace",
            overflowWrap: "anywhere",
          }}
        >
          <span style={{ color: "#9aa9c4" }}>{coordStr}</span>
          <span style={{ color: "#6b7a97" }}>±{position.area.radius?.toFixed(1)} m accuracy</span>
        </div>
      )}
    </div>
  );
}

// Crossfade the detail panel on selection change: hold the old content, fade it
// out, swap, fade the new one in - so switching between two anchors of the same
// kind is clearly animated, not an instant text swap. Same selection just
// refreshes content (live telemetry) without replaying the animation.
function PanelSwap({ swapKey, children }) {
  const [shown, setShown] = useState(true);
  const [shownChildren, setShownChildren] = useState(children);
  const keyRef = useRef(swapKey);
  const childrenRef = useRef(children);
  childrenRef.current = children;

  // Keep the visible content fresh for the CURRENT selection (live telemetry)
  // without animating. Declared first so it never runs after the key flips.
  useEffect(() => {
    if (swapKey === keyRef.current) setShownChildren(children);
  }, [children, swapKey]);

  // Animate ONLY on a real selection change. Deps are [swapKey] only, so an
  // unrelated re-render (a stream tick during the fade) can no longer cancel the
  // timeout that flips the panel back to visible - the bug that left the asset
  // detail stuck invisible when switching from an anchor detail.
  useEffect(() => {
    if (swapKey === keyRef.current) return;
    keyRef.current = swapKey;
    setShown(false); // fade the old content out
    const t = setTimeout(() => {
      setShownChildren(childrenRef.current); // swap while invisible
      setShown(true); // fade the new content in
    }, 170);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [swapKey]);
  return (
    <div
      style={{
        opacity: shown ? 1 : 0,
        transition: "opacity 170ms ease",
      }}
    >
      {shownChildren}
    </div>
  );
}

// Centered splash for the auth handshake (and auth errors), instead of a bare
// line of text in the corner.
function Splash({ error }) {
  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "linear-gradient(180deg, #050816 0%, #0a1228 100%)",
        color: "#e6edf7",
        fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
      }}
    >
      <style>{`@keyframes spl-spin{to{transform:rotate(360deg)}}@keyframes spl-pulse{0%,100%{opacity:.45}50%{opacity:1}}`}</style>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 18 }}>
        {!error && (
          <div
            style={{
              width: 42,
              height: 42,
              borderRadius: "50%",
              border: "3px solid rgba(58,130,255,0.18)",
              borderTopColor: "#3a82ff",
              animation: "spl-spin 0.9s linear infinite",
            }}
          />
        )}
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 13, letterSpacing: "0.18em", textTransform: "uppercase", fontWeight: 600 }}>
            Asset Location
          </div>
          <div
            style={{
              marginTop: 8,
              fontSize: 12,
              color: error ? "#ff6b78" : "#7a8aab",
              animation: error ? "none" : "spl-pulse 1.6s ease infinite",
            }}
          >
            {error || "Authenticating…"}
          </div>
        </div>
      </div>
    </div>
  );
}

export function App() {
  const [token, setToken] = useState(null);
  const [authError, setAuthError] = useState(null);
  const [selection, setSelection] = useState(null);
  const [layout, setLayout] = useState(null);
  const [recenterSignal, setRecenterSignal] = useState(0);
  // Collapse the device rail to give the 3D world the full width. Starts closed
  // on a narrow viewport so the scene is usable on small screens.
  const [railOpen, setRailOpen] = useState(
    () => typeof window === "undefined" || window.innerWidth >= 900
  );
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
    let interval;
    // Renew the access token before it expires. The token captured at init goes
    // stale after its lifetime (~5 min), which 401s every API call and the WS
    // stream. updateToken refreshes only when near expiry. setToken re-runs the
    // token-dependent fetches and reconnects the stream with the fresh token.
    const renew = () =>
      keycloak
        .updateToken(60)
        .then((refreshed) => {
          if (refreshed) setToken(keycloak.token);
        })
        .catch(() => keycloak.login());
    keycloak
      .init(initOptions)
      .then((authenticated) => {
        // check-sso: authenticated silently if a session exists, otherwise send
        // the user to the login page (only here, not on every refresh).
        if (authenticated) {
          setToken(keycloak.token);
          keycloak.onTokenExpired = renew;
          interval = setInterval(renew, 30000);
        } else keycloak.login();
      })
      .catch(() => setAuthError("Keycloak init failed"));
    return () => clearInterval(interval);
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

  // Remember the last position each asset reported, so an asset that goes
  // offline can still show its last known fix in the detail panel (the stream
  // stops carrying it, but a client-side memory does not). Keeps the most
  // recent non-null position per asset for the session.
  const lastFixRef = useRef({});
  useEffect(() => {
    for (const [assetId, entry] of Object.entries(byAsset)) {
      if (entry.position) lastFixRef.current[assetId] = entry.position;
    }
  }, [byAsset]);

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

  // Asset-driven anchor relevance: the focused device's diagnostics (UWB
  // neighbours) or its technology decide which anchors stay bright; the rest
  // recede. Null when nothing is focused (neutral overview).
  const focusedDevice = selection?.kind === "device" ? selection.device : null;
  const { diagnostics: focusDiag } = useDeviceDiagnostics(token, focusedDevice?.assetId || null);
  const relevance = useMemo(() => {
    if (!focusedDevice) return null;
    const anchors = (layout?.rooms?.[0]?.anchors ?? layout?.aps) ?? [];
    return computeRelevant(
      { technology: focusedDevice.source, neighbors: focusDiag?.neighbors },
      anchors
    );
  }, [focusedDevice, focusDiag, layout]);

  if (authError) return <Splash error={authError} />;
  if (!token) return <Splash />;

  // Every device that has a live position renders a marker; `selected` drives
  // its scale so hiding / showing an asset animates out / in (a deselected but
  // still-live device stays mounted at scale 0, ready to ease back).
  const scenePositions = devices
    .map((d) => ({
      device: d,
      position: byAsset[d.assetId]?.position,
      selected: isSelected(d.assetId),
    }))
    .filter((e) => e.position);
  const anyMock = devices.some((d) => d.source === "synthetic");

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
        // One column: the scene owns the full width and never resizes. Both the
        // device rail (left) and the detail panel (right) are floating overlays
        // on the scene, so collapsing the rail never reflows the canvas.
        gridTemplateColumns: "minmax(0, 1fr)",
      }}
    >
      <header style={header}>
        {/* Zone 1 - brand: the app identity, given primacy (title over a muted
            subtitle), with the live-feed dot. */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={dot(connected ? "#5dffb0" : "#7a8aab", connected)}
            title={connected ? "Live position feed connected" : "Position feed disconnected - reconnecting"}
          />
          <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.15 }}>
            <h2 style={title}>Asset Location</h2>
            <span style={{ fontSize: 9, letterSpacing: "0.14em", textTransform: "uppercase", color: "#65748f" }}>
              CAMARA Device Location · {connected ? "live" : "offline"}
            </span>
          </div>
        </div>

        {/* Zone 2 - context: what the feed is doing right now, as secondary chips. */}
        <div style={hDivider} />
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          {activeStrategy && (
            <span
              style={{ ...metaChip, color: "#9ec3ff", border: "1px solid rgba(58,130,255,0.3)", background: "rgba(58,130,255,0.08)" }}
              title={`Engine fusion strategy in effect (private-profile vendor extension, id: ${activeStrategy}). Every fix in the feed is produced by this strategy.`}
            >
              <span style={{ opacity: 0.55, textTransform: "uppercase", letterSpacing: "0.06em" }}>fusion</span>
              {STRATEGY_LABEL[activeStrategy] || activeStrategy}
            </span>
          )}
          {venueName && (
            <span style={metaChip} title={geoStr ? `Location: ${geoStr}` : undefined}>
              <span style={{ opacity: 0.7 }}>📍</span>
              <span style={{ color: "#cdd7ea" }}>{venueName}</span>
              {roomLabel && <span style={{ opacity: 0.6 }}>· {roomLabel}</span>}
              {roomDims && <span style={{ opacity: 0.5 }}>· {roomDims}</span>}
            </span>
          )}
          {anyMock && (
            <span
              style={mockPill}
              title="At least one registered asset is positioned by the synthetic-adapter (waypoint walker). Real deployments do not ship with it."
            >
              demo build
            </span>
          )}
          {idleState === "standby" && (
            <span style={standbyPill} title="Polling paused while idle. Any input resumes the feed.">
              standby
            </span>
          )}
        </div>

        {/* Zone 3 - controls: scene view controls + adapter health, right-aligned. */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          <div style={hDivider} />
          {techsWithAnchors.size > 0 && (
            <div style={headerLayers}>
              {TECH_KEYS.filter((t) => techsWithAnchors.has(t)).map((tech) => {
                const active = visibleTechs.has(tech);
                const c = TECH_COLOR[tech];
                return (
                  <button
                    key={tech}
                    onClick={() => toggleTech(tech)}
                    title={`${active ? "Hide" : "Show"} ${TECH_LABEL[tech]} anchors`}
                    style={headerTech(active, c)}
                  >
                    <span style={{ width: 8, height: 8, borderRadius: "50%", background: active ? c : "transparent", border: `1px solid ${c}`, flexShrink: 0 }} />
                    {TECH_LABEL[tech]}
                  </button>
                );
              })}
            </div>
          )}
          <button
            type="button"
            style={headerBtn}
            onClick={() => setRecenterSignal((n) => n + 1)}
            title="Recenter the view"
          >
            ⌖ recenter
          </button>
          <AdapterHealthBadge adapters={adapters} />
        </div>
      </header>

      <div style={sceneWrap}>
        {/* Device rail: a floating overlay, slides in/out WITHOUT resizing the
            canvas (so toggling never reflows / recenters the world). Collapse
            control sits at its own top-right; a reopen tab shows when hidden. */}
        <aside style={sidebarPanel(railOpen)}>
          <div style={sidebarHead}>
            <h3 style={{ ...sidebarTitle, margin: 0 }}>Devices</h3>
            <button
              type="button"
              style={railToggle}
              onClick={() => setRailOpen(false)}
              title="Collapse the device rail"
              aria-label="Collapse device rail"
            >
              ‹‹
            </button>
          </div>
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
            const entry = byAsset[d.assetId];
            const detailOpen =
              selection?.kind === "device" && selection.device?.assetId === d.assetId;
            return (
              <div key={d.assetId}>
                <DeviceItem
                  device={d}
                  position={entry?.position}
                  shown={isSelected(d.assetId)}
                  detailOpen={detailOpen}
                  onOpenDetail={(dev) => setSelection({ kind: "device", device: dev })}
                  onToggleShown={toggle}
                  frame={frameFromLayout(layout)}
                />
              </div>
            );
          })}
        </aside>
        <button
          type="button"
          style={railReopen(railOpen)}
          onClick={() => setRailOpen(true)}
          title="Show the device rail"
          aria-label="Show device rail"
        >
          ›› devices
        </button>

        <FloorPlanScene
          token={token}
          positions={scenePositions}
          visibleTechs={visibleTechs}
          relevantAnchorIds={relevance}
          recenterSignal={recenterSignal}
          onSelectDevice={(d) => setSelection(d ? { kind: "device", device: d } : null)}
          onSelectAp={(ap) => setSelection({ kind: "ap", ap })}
          onLayoutLoaded={setLayout}
        />
        {/* Floating overlay on the scene - never resizes the canvas. */}
        <div
          style={{
            position: "absolute",
            top: 28,
            right: "clamp(12px, 2vw, 32px)",
            width: "min(340px, calc(100vw - 48px))",
            // The panel itself scrolls (see DetailPanel `panel`); the overlay
            // just positions + fades it, so the crossfade never touches scroll.
            overflow: "visible",
            overflowX: "hidden",
            boxSizing: "border-box",
            zIndex: 70,
            opacity: selection ? 1 : 0,
            transform: selection ? "translateX(0)" : "translateX(20px)",
            transition: "transform 240ms cubic-bezier(0.22, 1, 0.36, 1), opacity 200ms ease",
            pointerEvents: selection ? "auto" : "none",
          }}
        >
          {renderedSelection && (
            <PanelSwap
              swapKey={
                renderedSelection.kind === "ap"
                  ? `ap:${renderedSelection.ap?.id}`
                  : `device:${renderedSelection.device?.assetId}`
              }
            >
              <DetailPanel
                selection={renderedSelection}
                token={token}
                frame={frameFromLayout(layout)}
                lastFix={
                  renderedSelection.kind === "device"
                    ? lastFixRef.current[renderedSelection.device?.assetId]
                    : null
                }
                onClose={() => setSelection(null)}
              />
            </PanelSwap>
          )}
        </div>
        <div style={navHint}>
          <span>⟳ drag&nbsp;rotate</span>
          <span>⇅ scroll&nbsp;zoom</span>
          <span>✥ right-drag&nbsp;/&nbsp;ctrl&nbsp;pan</span>
          <span>⇧ shift&nbsp;up/down</span>
        </div>
      </div>
      {idleState === "prompting" && (
        <IdlePromptModal remainingMs={promptRemainingMs} onAcknowledge={acknowledge} />
      )}
      {idleState === "standby" && <StandbyOverlay />}
    </div>
  );
}
