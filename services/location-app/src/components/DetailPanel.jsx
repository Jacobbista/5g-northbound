import { useDeviceDetails } from "../hooks/useDeviceDetails";
import { useAnchorCalibration } from "../hooks/useAnchorCalibration";
import { useDeviceDiagnostics } from "../hooks/useDeviceDiagnostics";
import { shortLabel } from "../lib/label";

const M_PER_DEG = 111320;

// Invert the blueprint's floor-plan georef to room-local metres (canvas-y),
// the SAME frame the scene + sidebar use. NOT the legacy env GPS_ORIGIN, which
// produced the million-metre x/z the panel used to show. `frame` is null until
// the blueprint loads; callers fall back to lat/lon.
function gpsToRoomLocal(lat, lon, frame) {
  if (!frame?.georef) return null;
  const { lat0, lon0, az, roomX, roomY, fpH } = frame;
  const east = (lon - lon0) * M_PER_DEG * Math.cos((lat0 * Math.PI) / 180);
  const north = (lat - lat0) * M_PER_DEG;
  const xFp = east * Math.cos(az) - north * Math.sin(az);
  const yFp = east * Math.sin(az) + north * Math.cos(az);
  return { x: xFp - roomX, z: (fpH - yFp) - roomY };
}

const KIND_ICON = {
  forklift: "🚜",
  pallet: "📦",
  tool: "🔧",
  "uwb-tag": "🏷️",
  asset: "📍",
  ue: "📱",
};

// Palette tokens:
//   INK    - text scale (emphasis by lightness)
//   STATUS - state: ok / attention / failure
//   TECH   - positioning technology identity; one hue per technology, shared by
//            source chips, anchor accents and scene markers.
const INK = { primary: "#e6edf7", secondary: "#9aa9c4", muted: "#7a8aab", faint: "#5a6987" };
const STATUS = { ok: "#5dffb0", warn: "#ffb347", error: "#ff6b78" };
const TECH_COLOR = {
  wifi: "#ffb347",
  wittra: "#5dffb0",
  fiveg: "#c084fc",
  gnss: "#fbbf24",
  synthetic: "#7a8aab",
};

const panel = {
  width: "100%",
  boxSizing: "border-box",
  maxWidth: "100%",
  borderRadius: 12,
  background: "rgba(8,14,32,0.92)",
  border: "1px solid rgba(58,130,255,0.28)",
  boxShadow: "0 8px 32px rgba(0,0,0,0.5), 0 0 0 1px rgba(58,130,255,0.08) inset",
  color: "#e6edf7",
  fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif",
  fontSize: 12,
  backdropFilter: "blur(10px)",
  overflow: "hidden",
};

const head = (accent) => ({
  padding: "14px 16px",
  borderBottom: "1px solid rgba(255,255,255,0.06)",
  background: `linear-gradient(180deg, ${accent}14, transparent)`,
});

const closeBtn = {
  background: "transparent",
  border: "1px solid rgba(255,255,255,0.18)",
  color: "#9aa9c4",
  borderRadius: 6,
  width: 24,
  height: 24,
  cursor: "pointer",
  fontSize: 12,
  lineHeight: 1,
  flexShrink: 0,
};

const chip = (color) => ({
  display: "inline-flex",
  alignItems: "center",
  padding: "2px 7px",
  borderRadius: 999,
  background: `${color}1f`,
  border: `1px solid ${color}66`,
  color,
  fontSize: 9.5,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  fontFamily: "ui-monospace, monospace",
});

const sectionTitle = {
  fontSize: 9,
  color: "#5a6987",
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  padding: "12px 16px 4px",
};

const statRow = {
  display: "grid",
  gridTemplateColumns: "84px 1fr",
  gap: 10,
  alignItems: "baseline",
  padding: "5px 16px",
};
const sLabel = { color: INK.muted, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em" };
const sVal = { fontFamily: "ui-monospace, monospace", fontSize: 12, color: INK.primary, wordBreak: "break-word" };

function StatusPill({ live }) {
  const c = live ? STATUS.ok : INK.muted;
  return (
    <span style={{ ...chip(c), gap: 5 }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: c, boxShadow: live ? `0 0 6px ${c}` : "none" }} />
      {live ? "live" : "offline"}
    </span>
  );
}

function fmtTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const secs = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  return d.toLocaleTimeString();
}

function DevicePanel({ token, device, onClose, coordMode, frame }) {
  const { details, error, loading } = useDeviceDetails(token, device.assetId);
  const { diagnostics: diag } = useDeviceDiagnostics(token, device.assetId);
  const t = details?.telemetry;
  const accent = device.color;
  const kind = details?.kind || device.kind;
  const source = details?.source || device.source;
  const org = details?.org;

  return (
    <aside style={panel}>
      <div style={head(accent)}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 18 }}>{KIND_ICON[kind] || "📍"}</span>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: accent, letterSpacing: "0.02em" }}>
                {device.label}
              </h3>
            </div>
            <div style={{ fontSize: 11, color: "#7a8aab", fontFamily: "ui-monospace, monospace", marginTop: 3 }}>
              {device.assetId}
            </div>
          </div>
          <button style={closeBtn} onClick={onClose} aria-label="close">✕</button>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 10 }}>
          <StatusPill live={Boolean(t)} />
          {kind && <span style={chip(INK.secondary)}>{kind}</span>}
          {source && <span style={chip(TECH_COLOR[source] || INK.secondary)}>{source}</span>}
          {org && <span style={chip(INK.muted)}>{org}</span>}
        </div>
      </div>

      {loading && <div style={{ color: INK.muted, padding: "16px" }}>loading…</div>}
      {error && <div style={{ color: STATUS.error, padding: "16px" }}>error: {error}</div>}
      {!loading && !t && !error && (
        <div style={{ color: INK.muted, padding: "20px 16px", fontSize: 11 }}>
          No current fix. The asset is registered but no positioning source is reporting it.
        </div>
      )}

      {t && (
        <>
          <div style={sectionTitle}>position</div>
          <div style={statRow}>
            <span style={sLabel}>{coordMode === "relative" ? "room x/z" : "lat / lon"}</span>
            <span style={sVal}>
              {coordMode === "relative"
                ? (() => {
                    const p = gpsToRoomLocal(t.latitude, t.longitude, frame);
                    return p ? `${p.x.toFixed(1)}, ${p.z.toFixed(1)} m` : "—";
                  })()
                : `${t.latitude.toFixed(6)}, ${t.longitude.toFixed(6)}`}
            </span>
          </div>
          {t.altitude != null && (
            <div style={statRow}>
              <span style={sLabel}>altitude</span>
              <span style={sVal}>{t.altitude.toFixed(2)} m</span>
            </div>
          )}
          <div style={statRow}>
            <span style={sLabel}>accuracy</span>
            <span style={sVal}>±{t.accuracy_m.toFixed(2)} m</span>
          </div>

          <div style={sectionTitle}>fusion</div>
          <div style={statRow}>
            <span style={sLabel}>strategy</span>
            <span style={sVal}>{t.strategy}</span>
          </div>
          <div style={statRow}>
            <span style={sLabel}>sources</span>
            <span style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {t.sources.length === 0
                ? <span style={{ color: INK.muted }}>—</span>
                : t.sources.map((s) => (
                    <span key={s} style={chip(TECH_COLOR[s] || INK.secondary)}>{s}</span>
                  ))}
            </span>
          </div>

          {diag && Object.keys(diag).length > 0 && (
            <>
              <div style={sectionTitle}>signal quality</div>
              {diag.motion != null && (
                <div style={statRow}><span style={sLabel}>motion</span><span style={sVal}>{diag.motion}</span></div>
              )}
              {diag.accuracy_value != null && (
                <div style={statRow}>
                  <span style={sLabel}>accuracy</span>
                  <span style={sVal}>±{Number(diag.accuracy_value).toFixed(2)} m{diag.accuracy_kind ? ` · ${diag.accuracy_kind}` : ""}</span>
                </div>
              )}
              {Array.isArray(diag.rssi) && diag.rssi.length > 0 && (
                <div style={statRow}><span style={sLabel}>rssi</span><span style={sVal}>{diag.rssi.join(", ")} dBm</span></div>
              )}
              {Array.isArray(diag.ping_pongs) && diag.ping_pongs.length > 0 && (
                <div style={statRow}><span style={sLabel}>ping-pongs</span><span style={sVal}>{diag.ping_pongs.join(", ")}</span></div>
              )}
              {Array.isArray(diag.neighbors) && diag.neighbors.length > 0 && (
                <div style={statRow}><span style={sLabel}>neighbors</span><span style={sVal}>{diag.neighbors.map((n) => shortLabel(n)).join(", ")}</span></div>
              )}
            </>
          )}

          <div style={{ ...statRow, paddingBottom: 14, paddingTop: 10, borderTop: "1px solid rgba(255,255,255,0.05)", marginTop: 6 }}>
            <span style={sLabel}>last fix</span>
            <span style={{ ...sVal, color: INK.secondary }}>{fmtTime(t.lastLocationTime)}</span>
          </div>
        </>
      )}
    </aside>
  );
}

function ApPanel({ ap, onClose, coordMode, token }) {
  const calib = useAnchorCalibration(token);
  const rf = calib[ap.id];
  const tech = ap.technology || "anchor";
  // Accent follows the anchor's technology.
  const accent = TECH_COLOR[ap.technology] || INK.secondary;
  // Vendor identity when present.
  const subtitle = ap.vendor
    ? `${ap.vendor}${ap.model ? ` · ${ap.model}` : ""}`
    : `Anchor · ${tech}`;
  return (
    <aside style={panel}>
      <div style={head(accent)}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
          <div style={{ minWidth: 0 }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: accent }}>{ap.id}</h3>
            <div style={{ fontSize: 11, color: INK.muted, marginTop: 3 }}>{subtitle}</div>
          </div>
          <button style={closeBtn} onClick={onClose} aria-label="close">✕</button>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 10 }}>
          <span style={chip(accent)}>{tech}</span>
          {rf && <span style={chip(rf.calibrated ? STATUS.ok : INK.muted)}>{rf.calibrated ? "calibrated" : "default rf"}</span>}
        </div>
      </div>

      {/* Cloud identity, present when the anchor was synced from the vendor. */}
      {(ap.vendor_device_id || ap.model) && (
        <>
          <div style={sectionTitle}>identity</div>
          {ap.vendor_device_id && (
            <div style={statRow}><span style={sLabel}>hardware id</span><span style={sVal}>{ap.vendor_device_id}</span></div>
          )}
          {ap.model && (
            <div style={statRow}><span style={sLabel}>class</span><span style={sVal}>{ap.model}</span></div>
          )}
        </>
      )}

      <div style={sectionTitle}>anchor</div>
      <div style={statRow}>
        <span style={sLabel}>position</span>
        <span style={sVal}>
          {coordMode === "relative" ? `${ap.x.toFixed(1)}, ${ap.y.toFixed(1)} m` : "(local frame)"}
        </span>
      </div>
      {ap.height_m != null && (
        <div style={statRow}><span style={sLabel}>height</span><span style={sVal}>{Number(ap.height_m).toFixed(2)} m</span></div>
      )}

      {/* Real RF model from the wifi calibration (DERIVE), not the blueprint's
          nominal placeholders. Absent for non-wifi or un-calibrated anchors. */}
      {rf ? (
        <>
          <div style={sectionTitle}>rf model {rf.calibrated ? "· calibrated" : "· default"}</div>
          <div style={statRow}>
            <span style={sLabel}>tx@ref</span>
            <span style={sVal}>{Number(rf.tx_power_ref_dbm).toFixed(1)} dBm</span>
          </div>
          <div style={{ ...statRow, paddingBottom: 14 }}>
            <span style={sLabel}>path-loss n</span>
            <span style={sVal}>{Number(rf.path_loss_n).toFixed(2)}</span>
          </div>
        </>
      ) : (
        ap.technology === "wifi" && (
          <div style={{ color: INK.muted, padding: "10px 16px 14px", fontSize: 11 }}>
            No calibration yet - run the WiFi calibration to fit this anchor's RF model.
          </div>
        )
      )}
    </aside>
  );
}

export function DetailPanel({ selection, token, onClose, coordMode, frame }) {
  if (!selection) return null;
  if (selection.kind === "device")
    return <DevicePanel token={token} device={selection.device} onClose={onClose} coordMode={coordMode} frame={frame} />;
  if (selection.kind === "ap") return <ApPanel ap={selection.ap} onClose={onClose} coordMode={coordMode} token={token} />;
  return null;
}
