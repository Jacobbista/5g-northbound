import { useDeviceDetails } from "../hooks/useDeviceDetails";
import { useAnchorCalibration } from "../hooks/useAnchorCalibration";
import { useDeviceDiagnostics } from "../hooks/useDeviceDiagnostics";

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

// Forward transform: room-local canvas-y (x right, y down) -> lat/lon, the exact
// inverse of gpsToRoomLocal. Anchors are stored in the room frame with no native
// lat/lon; georef them so the panel can show both. (x, y) here is (ap.x, ap.y).
function roomLocalToGps(x, y, frame) {
  if (!frame?.georef) return null;
  const { lat0, lon0, az, roomX, roomY, fpH } = frame;
  const xFp = x + roomX;
  const yFp = fpH - (y + roomY);
  const east = xFp * Math.cos(az) + yFp * Math.sin(az);
  const north = -xFp * Math.sin(az) + yFp * Math.cos(az);
  return {
    lat: lat0 + north / M_PER_DEG,
    lon: lon0 + east / (M_PER_DEG * Math.cos((lat0 * Math.PI) / 180)),
  };
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
  // Near-opaque solid ground (not a see-through frosted panel) so the content
  // reads cleanly and never looks offset behind the blur.
  background: "rgba(9,15,30,0.97)",
  border: "1px solid rgba(58,130,255,0.28)",
  boxShadow: "0 8px 32px rgba(0,0,0,0.5), 0 0 0 1px rgba(58,130,255,0.08) inset",
  color: "#e6edf7",
  fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif",
  fontSize: 12,
  backdropFilter: "blur(10px)",
  // Scroll lives on the panel itself (not the crossfade wrapper). No reserved
  // gutter: it left a constant empty strip on the right that looked misaligned;
  // a short panel now uses the full width.
  overflowX: "hidden",
  overflowY: "auto",
  maxHeight: "calc(100vh - 150px)",
  paddingBottom: 8,
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

// A reported fix older than this is stale: the device is still live (an adapter
// reports it) but its position is not current. Keep the two facts distinct.
const STALE_FIX_SECS = 120;

function fixAgeSecs(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d)) return null;
  return Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
}

// Relative age with day granularity, falling back to an absolute date+time once
// the fix is over a week old, so a stale fix never reads as the current time.
function fmtTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const secs = fixAgeSecs(iso);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  if (secs < 7 * 86400) return `${Math.round(secs / 86400)}d ago`;
  return d.toLocaleString();
}

function DevicePanel({ token, device, onClose, frame, lastFix }) {
  const { details, error, loading } = useDeviceDetails(token, device.assetId);
  // Diagnostics come from a per-device vendor GET, independent of a current
  // position fix: an offline asset still reports battery / last_seen. Fetch
  // regardless of liveness.
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
        </div>
      </div>

      {/* Identity as aligned label:value rows, the same grid as position/fusion,
          so class (what it is), source (who locates it) and tenant (who owns it)
          read as distinct facts. Shown whether or not there is a current fix. */}
      <div style={sectionTitle}>identity</div>
      {kind && (
        <div style={statRow}><span style={sLabel}>class</span><span style={sVal}>{kind}</span></div>
      )}
      {source && (
        <div style={statRow}>
          <span style={sLabel}>source</span>
          <span><span style={chip(TECH_COLOR[source] || INK.secondary)}>{source}</span></span>
        </div>
      )}
      {org && (
        <div style={statRow}><span style={sLabel}>tenant</span><span style={sVal}>{org}</span></div>
      )}

      {loading && <div style={{ color: INK.muted, padding: "16px" }}>loading…</div>}
      {error && <div style={{ color: STATUS.error, padding: "16px" }}>error: {error}</div>}
      {!loading && !t && !error && (
        <>
          <div style={{ color: INK.muted, padding: "20px 16px 8px", fontSize: 11 }}>
            No current fix. The asset is registered but no positioning source is reporting it.
          </div>
          {lastFix?.area?.center && (
            <>
              <div style={sectionTitle}>last known fix</div>
              <div style={statRow}>
                <span style={sLabel}>seen</span>
                <span style={sVal} title={lastFix.observedAt || lastFix.lastLocationTime || ""}>
                  {fmtTime(lastFix.observedAt || lastFix.lastLocationTime)}
                </span>
              </div>
              <div style={statRow}>
                <span style={sLabel}>lat / lon</span>
                <span style={sVal}>
                  {lastFix.area.center.latitude.toFixed(6)}, {lastFix.area.center.longitude.toFixed(6)}
                </span>
              </div>
              {(() => {
                const c = lastFix.area.center;
                const p = gpsToRoomLocal(c.latitude, c.longitude, frame);
                return p ? (
                  <div style={statRow}>
                    <span style={sLabel}>room x / z</span>
                    <span style={sVal}>{p.x.toFixed(1)}, {p.z.toFixed(1)} m</span>
                  </div>
                ) : null;
              })()}
            </>
          )}
        </>
      )}

      {t && (
        <>
          <div style={sectionTitle}>position</div>
          <div style={statRow}>
            <span style={sLabel}>lat / lon</span>
            <span style={sVal}>{t.latitude.toFixed(6)}, {t.longitude.toFixed(6)}</span>
          </div>
          {(() => {
            const p = gpsToRoomLocal(t.latitude, t.longitude, frame);
            return p ? (
              <div style={statRow}>
                <span style={sLabel}>room x / z</span>
                <span style={sVal}>{p.x.toFixed(1)}, {p.z.toFixed(1)} m</span>
              </div>
            ) : null;
          })()}
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
              <div style={sectionTitle}>diagnostics</div>
              {/* Core vocabulary: standard names, same for every vendor. */}
              {diag.battery != null && (
                <div style={statRow}><span style={sLabel}>battery</span><span style={sVal}>{Math.round(diag.battery)}%</span></div>
              )}
              {diag.moving != null && (
                <div style={statRow}><span style={sLabel}>motion</span><span style={sVal}>{diag.moving ? "moving" : "stationary"}</span></div>
              )}
              {diag.last_seen != null && (
                <div style={statRow}><span style={sLabel}>last seen</span><span style={sVal}>{new Date(diag.last_seen * 1000).toLocaleTimeString()}</span></div>
              )}
              {diag.accuracy != null && (
                <div style={statRow}><span style={sLabel}>accuracy</span><span style={sVal}>±{Number(diag.accuracy).toFixed(2)} m</span></div>
              )}
              {/* Legacy flat fields, in case a source has not migrated yet. */}
              {diag.motion != null && (
                <div style={statRow}><span style={sLabel}>motion</span><span style={sVal}>{diag.motion}</span></div>
              )}
              {diag.accuracy_value != null && (
                <div style={statRow}>
                  <span style={sLabel}>accuracy</span>
                  <span style={sVal}>±{Number(diag.accuracy_value).toFixed(2)} m{diag.accuracy_kind ? ` · ${diag.accuracy_kind}` : ""}</span>
                </div>
              )}
              {/* Everything the profile does not standardize: raw, collapsed. */}
              {diag.x_vendor && Object.keys(diag.x_vendor).length > 0 && (
                <details style={{ marginTop: 4 }}>
                  <summary style={{ ...sLabel, cursor: "pointer" }}>vendor-specific</summary>
                  {Object.entries(diag.x_vendor).map(([k, v]) => (
                    <div key={k} style={statRow}>
                      <span style={sLabel}>{k}</span>
                      <span style={sVal}>{Array.isArray(v) ? v.join(", ") : String(v)}</span>
                    </div>
                  ))}
                </details>
              )}
            </>
          )}

          {(() => {
            // The device is live (telemetry present) but its fix may be old.
            // Surface the fix age separately, amber past the stale threshold,
            // so a stale position is not mistaken for the current one.
            const secs = fixAgeSecs(t.lastLocationTime);
            const stale = secs != null && secs > STALE_FIX_SECS;
            return (
              <div style={{ ...statRow, paddingBottom: 14, paddingTop: 10, borderTop: "1px solid rgba(255,255,255,0.05)", marginTop: 6 }}>
                <span style={sLabel}>last fix</span>
                <span style={{ ...sVal, color: stale ? STATUS.warn : INK.secondary }} title={t.lastLocationTime || ""}>
                  {fmtTime(t.lastLocationTime)}{stale ? " · stale" : ""}
                </span>
              </div>
            );
          })()}
        </>
      )}
    </aside>
  );
}

function ApPanel({ ap, onClose, token, frame }) {
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
      </div>

      {/* Identity as aligned rows, matching the asset panel. An anchor is venue
          infrastructure, not a tenant asset, so role is fixed. Hardware id and
          model appear when the anchor was synced from the vendor cloud. */}
      <div style={sectionTitle}>identity</div>
      <div style={statRow}>
        <span style={sLabel}>tech</span>
        <span><span style={chip(accent)}>{tech}</span></span>
      </div>
      <div style={statRow}><span style={sLabel}>role</span><span style={sVal}>infrastructure</span></div>
      {rf && (
        <div style={statRow}>
          <span style={sLabel}>rf</span>
          <span><span style={chip(rf.calibrated ? STATUS.ok : INK.muted)}>{rf.calibrated ? "calibrated" : "default"}</span></span>
        </div>
      )}
      {ap.vendor_device_id && (
        <div style={statRow}><span style={sLabel}>hardware id</span><span style={sVal}>{ap.vendor_device_id}</span></div>
      )}
      {ap.model && (
        <div style={statRow}><span style={sLabel}>class</span><span style={sVal}>{ap.model}</span></div>
      )}

      <div style={sectionTitle}>anchor</div>
      <div style={statRow}>
        <span style={sLabel}>room x / y</span>
        <span style={sVal}>{ap.x.toFixed(1)}, {ap.y.toFixed(1)} m</span>
      </div>
      {(() => {
        const g = roomLocalToGps(ap.x, ap.y, frame);
        return g ? (
          <div style={statRow}>
            <span style={sLabel}>lat / lon</span>
            <span style={sVal}>{g.lat.toFixed(6)}, {g.lon.toFixed(6)}</span>
          </div>
        ) : null;
      })()}
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

export function DetailPanel({ selection, token, onClose, frame, lastFix }) {
  if (!selection) return null;
  if (selection.kind === "device")
    return <DevicePanel token={token} device={selection.device} onClose={onClose} frame={frame} lastFix={lastFix} />;
  if (selection.kind === "ap") return <ApPanel ap={selection.ap} onClose={onClose} token={token} frame={frame} />;
  return null;
}
