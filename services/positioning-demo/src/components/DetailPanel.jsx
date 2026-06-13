import { useDeviceDetails } from "../hooks/useDeviceDetails";
import { GPS_ORIGIN_LAT, GPS_ORIGIN_LON } from "../config";

const M_PER_DEG = 111320;

const panel = {
  width: "100%",
  padding: 16,
  borderRadius: 10,
  background: "rgba(8,14,32,0.92)",
  border: "1px solid rgba(58,130,255,0.3)",
  boxShadow: "0 8px 32px rgba(0,0,0,0.5), 0 0 0 1px rgba(58,130,255,0.1) inset",
  color: "#e6edf7",
  fontFamily: "ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif",
  fontSize: 12,
  backdropFilter: "blur(10px)",
};

const titleRow = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  marginBottom: 12,
};

const title = {
  margin: 0,
  fontSize: 13,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  fontWeight: 600,
};

const closeBtn = {
  background: "transparent",
  border: "1px solid rgba(255,255,255,0.2)",
  color: "#e6edf7",
  borderRadius: 4,
  padding: "2px 8px",
  cursor: "pointer",
  fontSize: 11,
};

const tag = (color) => ({
  display: "inline-block",
  padding: "1px 6px",
  borderRadius: 3,
  background: `${color}20`,
  border: `1px solid ${color}80`,
  color,
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  fontFamily: "ui-monospace, monospace",
  marginRight: 4,
});

const row = {
  display: "grid",
  gridTemplateColumns: "100px 1fr",
  gap: 8,
  padding: "5px 0",
  borderBottom: "1px solid rgba(255,255,255,0.04)",
};

const label = { color: "#7a8aab", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em" };
const val = { fontFamily: "ui-monospace, monospace", fontSize: 11, color: "#e6edf7", wordBreak: "break-word" };

function gpsToLocal(lat, lon) {
  const x = (lon - GPS_ORIGIN_LON) * M_PER_DEG * Math.cos((GPS_ORIGIN_LAT * Math.PI) / 180);
  const z = (lat - GPS_ORIGIN_LAT) * M_PER_DEG;
  return { x, z };
}

function DevicePanel({ token, device, onClose, coordMode }) {
  const { details, error, loading } = useDeviceDetails(token, device.phoneNumber);
  const t = details?.telemetry;

  return (
    <aside style={panel}>
      <div style={titleRow}>
        <div>
          <h3 style={{ ...title, color: device.color }}>{device.label}</h3>
          <span style={{ fontSize: 10, color: "#7a8aab" }}>{device.deviceId}</span>
        </div>
        <button style={closeBtn} onClick={onClose} aria-label="close">
          ✕
        </button>
      </div>

      {loading && <div style={{ color: "#7a8aab" }}>loading…</div>}
      {error && <div style={{ color: "#ff6b78" }}>error: {error}</div>}
      {!loading && !t && !error && <div style={{ color: "#7a8aab" }}>no fix yet</div>}

      {t && (
        <>
          <div style={row}>
            <span style={label}>strategy</span>
            <span style={val}>{t.strategy}</span>
          </div>
          <div style={row}>
            <span style={label}>sources</span>
            <span style={val}>
              {t.sources.length === 0 ? (
                <span style={{ color: "#7a8aab" }}>-</span>
              ) : (
                t.sources.map((s) => (
                  <span key={s} style={tag("#3a82ff")}>
                    {s}
                  </span>
                ))
              )}
            </span>
          </div>
          <div style={row}>
            <span style={label}>accuracy</span>
            <span style={val}>±{t.accuracy_m.toFixed(2)} m</span>
          </div>
          <div style={row}>
            <span style={label}>
              {coordMode === "relative" ? "rel (m)" : "lat / lon"}
            </span>
            <span style={val}>
              {coordMode === "relative"
                ? (() => {
                    const p = gpsToLocal(t.latitude, t.longitude);
                    return `x=${p.x.toFixed(2)}  z=${p.z.toFixed(2)}`;
                  })()
                : `${t.latitude.toFixed(6)}, ${t.longitude.toFixed(6)}`}
            </span>
          </div>
          <div style={row}>
            <span style={label}>last fix</span>
            <span style={val}>{t.lastLocationTime}</span>
          </div>
        </>
      )}
    </aside>
  );
}

function ApPanel({ ap, onClose, coordMode }) {
  return (
    <aside style={panel}>
      <div style={titleRow}>
        <div>
          <h3 style={{ ...title, color: "#ffb347" }}>{ap.id}</h3>
          <span style={{ fontSize: 10, color: "#7a8aab" }}>
            {ap.vendor || "Access Point"}
            {ap.model ? ` · ${ap.model}` : ""}
          </span>
        </div>
        <button style={closeBtn} onClick={onClose} aria-label="close">
          ✕
        </button>
      </div>

      <div style={row}>
        <span style={label}>position</span>
        <span style={val}>
          {coordMode === "relative"
            ? `x=${ap.x.toFixed(2)}  z=${ap.y.toFixed(2)}`
            : "(local frame)"}
        </span>
      </div>
      {ap.band && (
        <div style={row}>
          <span style={label}>band</span>
          <span style={val}>{ap.band}</span>
        </div>
      )}
      {ap.channel != null && (
        <div style={row}>
          <span style={label}>channel</span>
          <span style={val}>{ap.channel}</span>
        </div>
      )}
      {ap.tx_power_dbm != null && (
        <div style={row}>
          <span style={label}>tx power</span>
          <span style={val}>{ap.tx_power_dbm} dBm</span>
        </div>
      )}
    </aside>
  );
}

const emptyRail = {
  width: "100%",
  padding: 16,
  borderRadius: 10,
  background: "rgba(8,14,32,0.55)",
  border: "1px solid rgba(255,255,255,0.04)",
  color: "#5a6987",
  fontFamily: "ui-monospace, monospace",
  fontSize: 11,
  textAlign: "center",
  padding: "40px 16px",
  lineHeight: 1.6,
};

export function DetailPanel({ selection, token, onClose, coordMode }) {
  if (!selection)
    return <div style={emptyRail}>click a device or anchor to inspect</div>;
  if (selection.kind === "device")
    return <DevicePanel token={token} device={selection.device} onClose={onClose} coordMode={coordMode} />;
  if (selection.kind === "ap") return <ApPanel ap={selection.ap} onClose={onClose} coordMode={coordMode} />;
  return null;
}
