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

// Convert a (lat, lng) coming back from the gateway into floor-local (x, z)
// metres relative to the GPS origin. Sidebar uses this so the lat/lon ↔ x/z
// toggle in the header actually changes what's shown next to each device.
function gpsToLocal(lat, lon) {
  const x = (lon - GPS_ORIGIN_LON) * M_PER_DEG * Math.cos((GPS_ORIGIN_LAT * Math.PI) / 180);
  const z = (lat - GPS_ORIGIN_LAT) * M_PER_DEG;
  return { x, z };
}

const TECH_LABEL = { wifi: "WiFi", wittra: "UWB", fiveg: "5G", gnss: "GNSS" };
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
  gap: 12,
  padding: "14px 20px",
  borderBottom: "1px solid rgba(255,255,255,0.06)",
  background: "rgba(10,18,40,0.6)",
  backdropFilter: "blur(8px)",
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
    offline: { bg: "rgba(122,138,171,0.12)", fg: "#7a8aab", border: "#7a8aab" },
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

function AdapterHealthBadge({ adapters }) {
  if (!adapters || adapters.length === 0) {
    return <span style={adapterBadge("unknown")} title="adapter health unknown">adapters n/a</span>;
  }
  const degraded = adapters.filter((a) => a.in_cooldown);
  if (degraded.length === 0) {
    return (
      <span
        style={adapterBadge("ok")}
        title={adapters.map((a) => a.name).join(", ")}
      >
        {adapters.length} adapter{adapters.length === 1 ? "" : "s"} ok
      </span>
    );
  }
  const detail = degraded
    .map((a) => `${a.name} (${a.fail_count} fail, ${a.cooldown_seconds_remaining.toFixed(0)}s)`)
    .join("\n");
  return (
    <span style={adapterBadge("degraded")} title={detail}>
      {degraded.length}/{adapters.length} degraded
    </span>
  );
}

const sceneWrap = {
  padding: "16px 20px 20px",
  position: "relative",
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

function deviceState({ position, connected }) {
  if (!position?.lastLocationTime) return connected ? "offline" : "offline";
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

function DeviceItem({ device, state, position, selected, coordMode, onToggle }) {
  const center = position?.area?.center;
  const coordStr = center
    ? coordMode === "relative"
      ? (() => {
          const p = gpsToLocal(center.latitude, center.longitude);
          return `x=${p.x.toFixed(2)}  z=${p.z.toFixed(2)}`;
        })()
      : `${center.latitude.toFixed(5)}, ${center.longitude.toFixed(5)}`
    : null;
  return (
    <div
      style={deviceRow(selected, device.color)}
      onClick={() => onToggle(device.phoneNumber)}
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
        {selected && coordStr && (
          <span style={{ fontSize: 10, color: "#7a8aab", fontFamily: "ui-monospace, monospace" }}>
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
  const allPhones = devices.map((d) => d.phoneNumber);
  const { isSelected, toggle } = useSelection(allPhones);
  const adapters = useAdapterHealth(token, { paused });
  const { byDeviceId, connected } = usePositionsStream(token, { paused });

  // Index every registered device against the live stream by its internal
  // deviceId (the WS payload key). Devices without a stream entry get
  // null position which the rest of the UI renders as "offline".
  const byPhone = useMemo(() => {
    const out = {};
    for (const d of devices) {
      const streamItem = byDeviceId[d.deviceId];
      out[d.phoneNumber] = {
        device: d,
        position: adaptStreamItem(streamItem),
      };
    }
    return out;
  }, [devices, byDeviceId]);

  if (authError)
    return <div style={{ ...shell, padding: 24, color: "#ff6b78" }}>{authError}</div>;
  if (!token)
    return <div style={{ ...shell, padding: 24, color: "#7a8aab" }}>Authenticating…</div>;

  const scenePositions = devices
    .filter((d) => isSelected(d.phoneNumber))
    .map((d) => ({
      device: d,
      position: byPhone[d.phoneNumber]?.position,
    }));
  const anyMock = devices.some((d) => d.simulated);

  return (
    <div style={shell}>
      <header style={header}>
        <div style={dot("#3a82ff", true)} />
        <h2 style={title}>5G Positioning</h2>
        <span style={subtitle}>· CAMARA · live</span>
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
        <div style={coordToggle}>
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
          const selected = isSelected(d.phoneNumber);
          const entry = byPhone[d.phoneNumber];
          return (
            <div key={d.phoneNumber}>
              <DeviceItem
                device={d}
                state={selected ? deviceState({ position: entry?.position, connected }) : "offline"}
                position={entry?.position}
                selected={selected}
                coordMode={coordMode}
                onToggle={toggle}
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
          onSelectDevice={(d) => setSelection({ kind: "device", device: d })}
          onSelectAp={(ap) => setSelection({ kind: "ap", ap })}
          onLayoutLoaded={setLayout}
        />
      </div>
      <aside style={{ padding: "16px 20px 20px 0" }}>
        <DetailPanel
          selection={selection}
          token={token}
          coordMode={coordMode}
          onClose={() => setSelection(null)}
        />
      </aside>
      {idleState === "prompting" && (
        <IdlePromptModal remainingMs={promptRemainingMs} onAcknowledge={acknowledge} />
      )}
      {idleState === "standby" && <StandbyOverlay />}
    </div>
  );
}
