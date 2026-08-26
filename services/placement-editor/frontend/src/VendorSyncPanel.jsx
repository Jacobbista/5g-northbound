import { useCallback, useEffect, useMemo, useState } from "react";
import { discoverDevices, fetchVendorSchema } from "./api/vendorSync.js";
import { localToGps } from "./GeorefMap.jsx";

const panel = {
  width: "100%",
  padding: "10px 12px",
  borderRadius: 8,
  background: "rgba(11,17,32,0.96)",
  border: "1px solid rgba(192,132,252,0.35)",
  boxShadow: "0 6px 24px rgba(0,0,0,0.45)",
  fontSize: 11,
  color: "#e6edf7",
  fontFamily: "ui-monospace, monospace",
};

const sectionTitle = {
  fontSize: 9,
  color: "#7a8aab",
  letterSpacing: "0.10em",
  textTransform: "uppercase",
  margin: "10px 0 4px",
};

const btn = (active = false, danger = false) => ({
  padding: "5px 10px",
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  fontWeight: 600,
  background: danger
    ? "rgba(255,107,120,0.10)"
    : active
    ? "rgba(192,132,252,0.20)"
    : "transparent",
  color: danger ? "#ff6b78" : active ? "#dbc1ff" : "#9aa9c4",
  border: `1px solid ${danger ? "#ff6b7855" : active ? "#c084fcaa" : "#9aa9c455"}`,
  borderRadius: 4,
  fontFamily: "ui-monospace, monospace",
  cursor: "pointer",
});

// Best-effort inverse of GerorefMap.localToGps: take a cloud (lat, lon) +
// the floor plan's georef and return room-local metres. The editor places
// devices using this projection when the operator presses Import.
function gpsToFloorPlanLocal(lat, lon, fp) {
  const georef = fp?.georef;
  if (!georef || georef.latitude == null || georef.longitude == null) return null;
  const lat0 = Number(georef.latitude);
  const lon0 = Number(georef.longitude);
  const az = ((Number(georef.azimuth_deg) || 0) * Math.PI) / 180;
  const mPerDegLat = 111320;
  const mPerDegLon = 111320 * Math.cos((lat0 * Math.PI) / 180);
  const east = (lon - lon0) * mPerDegLon;
  const north = (lat - lat0) * mPerDegLat;
  // Inverse of: east = x*cos(az) + y*sin(az), north = -x*sin(az) + y*cos(az)
  const x = east * Math.cos(az) - north * Math.sin(az);
  const y = east * Math.sin(az) + north * Math.cos(az);
  return { x, y };
}

// Compute the delta in metres between two (x, y) anchor positions in the
// room frame. Returns null when either point is missing.
function distanceM(a, b) {
  if (!a || !b) return null;
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.hypot(dx, dy);
}

export function VendorSyncPanel({
  active,
  room,           // current room object (provides x_m, y_m, width_m, height_m)
  floorPlan,      // current floor plan (georef)
  anchors,        // current room.anchors (operator can compare to cloud)
  onClose,
  onImport,       // (anchorSpec) => void  - caller adds / updates anchor
  onPreview,      // (samples[{vendor_device_id, x_local, y_local}]) => void
}) {
  const [vendor, setVendor] = useState(null);
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const schema = await fetchVendorSchema().catch(() => null);
      setVendor(schema?.vendor || null);
      const out = await discoverDevices();
      // Anchors only here: the discover list now carries mobile tags too
      // (fixed=false), but those are onboarded as assets by the KELT
      // dashboard, not placed as anchors. Keep fixed anchors for the editor.
      setDevices((out?.devices || []).filter((d) => d.fixed !== false));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (active) refresh();
  }, [active, refresh]);

  // Convert each cloud device's (lat, lon) into the room frame so the
  // canvas can render a ghost marker. Devices with no cloud coords get
  // a null local position; the operator then must place them manually.
  const cloudSamples = useMemo(() => {
    if (!floorPlan || !room) return [];
    const baseX = Number(room.x_m) || 0;
    const baseY = Number(room.y_m) || 0;
    // Floor-plan extent height, used to mirror the y axis (see below).
    const fpH = Number(floorPlan?.georef?.height_m) || 0;
    return devices.map((d) => {
      let local = null;
      if (d.latitude != null && d.longitude != null) {
        const fp = gpsToFloorPlanLocal(d.latitude, d.longitude, floorPlan);
        if (fp != null) {
          // gpsToFloorPlanLocal returns floor-plan-local coords in the georef
          // frame: origin at the lower-left, y growing NORTH (up). The plan /
          // room canvas and the hand-placed anchors use the image/SVG frame:
          // origin top-left, y growing DOWN. Convert by mirroring y about the
          // floor-plan height (fpH - fp.y), THEN subtract the room's top-left
          // origin. x shares the same direction in both frames, so it only
          // needs the room-base offset.
          local = { x: fp.x - baseX, y: (fpH - fp.y) - baseY };
        }
      }
      return { ...d, local };
    });
  }, [devices, floorPlan, room]);

  // Bubble the ghost positions up to the parent so the canvas can render
  // markers without each child reimplementing the projection.
  useEffect(() => {
    onPreview?.(cloudSamples);
    return () => onPreview?.([]);
  }, [cloudSamples, onPreview]);

  const handleImport = useCallback(
    (sample) => {
      if (!sample.local) {
        setError(`${sample.vendor_device_id} has no cloud position; place it manually`);
        return;
      }
      onImport?.({
        vendor_device_id: sample.vendor_device_id,
        label: sample.label,
        x: +sample.local.x.toFixed(2),
        y: +sample.local.y.toFixed(2),
        height_m: sample.height_m ?? 0,
        // Device class and vendor name from the active schema.
        device_type: sample.device_type,
        vendor,
      });
    },
    [onImport, vendor]
  );

  const handleImportAll = useCallback(() => {
    const ready = cloudSamples.filter((s) => s.local);
    if (ready.length === 0) {
      setError("no cloud devices have positions to import");
      return;
    }
    if (!confirm(`Import ${ready.length} device(s) from cloud? Existing IDs will be updated.`)) return;
    for (const sample of ready) {
      onImport?.({
        vendor_device_id: sample.vendor_device_id,
        label: sample.label,
        x: +sample.local.x.toFixed(2),
        y: +sample.local.y.toFixed(2),
        height_m: sample.height_m ?? 0,
        device_type: sample.device_type,
        vendor,
      });
    }
  }, [cloudSamples, onImport, vendor]);

  if (!active) return null;

  const driftHint = (sample) => {
    if (!sample.local) return null;
    const existing = anchors?.find(
      (a) => a.vendor_device_id && a.vendor_device_id === sample.vendor_device_id
    );
    if (!existing) return null;
    const d = distanceM({ x: existing.x, y: existing.y }, sample.local);
    if (d == null) return null;
    if (d < 0.1) return { color: "#5dffb0", label: "in sync" };
    if (d < 1.0) return { color: "#ffb347", label: `drift ${d.toFixed(2)}m` };
    return { color: "#ff6b78", label: `drift ${d.toFixed(2)}m` };
  };

  return (
    <aside style={panel}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          paddingBottom: 8,
          marginBottom: 4,
          borderBottom: "1px solid rgba(192,132,252,0.25)",
        }}
      >
        <strong
          style={{
            color: "#dbc1ff",
            letterSpacing: "0.06em",
            fontSize: 12,
          }}
        >
          ↻ sync {vendor || "vendor"}
        </strong>
        <button type="button" onClick={onClose} style={btn(false)}>
          ✕ close
        </button>
      </div>

      <div style={{ fontSize: 11, color: "#9aa9c4", lineHeight: 1.5, marginBottom: 8 }}>
        Pull the current device list from the vendor cloud and place anchors
        at their reported positions. Devices without cloud coordinates appear
        with a warning so you can position them manually.
      </div>

      <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        <button type="button" onClick={refresh} disabled={loading} style={btn(true)}>
          {loading ? "⟳ loading…" : "⟳ refresh"}
        </button>
        <button type="button" onClick={handleImportAll} disabled={loading || cloudSamples.length === 0} style={btn(true)}>
          ↓ import all
        </button>
      </div>

      {error && (
        <div
          style={{
            background: "rgba(255,107,120,0.10)",
            border: "1px solid #ff6b7855",
            color: "#ff6b78",
            padding: "6px 8px",
            borderRadius: 4,
            marginBottom: 8,
            wordBreak: "break-word",
          }}
        >
          {error}
        </div>
      )}

      <div style={sectionTitle}>· cloud devices ({cloudSamples.length})</div>
      {cloudSamples.length === 0 && !loading && (
        <div style={{ color: "#5a6987", fontSize: 10, padding: "4px 0" }}>
          none. check the vendor-adapter schema and credentials.
        </div>
      )}
      <div style={{ maxHeight: 360, overflowY: "auto" }}>
        {cloudSamples.map((s) => {
          const drift = driftHint(s);
          return (
            <div
              key={s.vendor_device_id}
              style={{
                padding: "6px 8px",
                borderRadius: 3,
                marginBottom: 4,
                background: "rgba(192,132,252,0.06)",
                border: "1px solid rgba(192,132,252,0.18)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 6,
                }}
              >
                <span style={{ color: "#dbc1ff", fontWeight: 600 }}>
                  {s.label || s.vendor_device_id}
                </span>
                {drift && (
                  <span
                    style={{
                      fontSize: 9,
                      color: drift.color,
                      border: `1px solid ${drift.color}`,
                      padding: "1px 5px",
                      borderRadius: 3,
                      letterSpacing: "0.06em",
                      textTransform: "uppercase",
                    }}
                  >
                    {drift.label}
                  </span>
                )}
              </div>
              <div style={{ color: "#7a8aab", fontSize: 10, marginTop: 2 }}>
                id <span style={{ color: "#aaffd6" }}>{s.vendor_device_id}</span>
              </div>
              {s.local ? (
                <div style={{ color: "#7a8aab", fontSize: 10, marginTop: 2 }}>
                  cloud xy: ({s.local.x.toFixed(2)}, {s.local.y.toFixed(2)})
                  {s.height_m != null && (
                    <span style={{ marginLeft: 6 }}>h={Number(s.height_m).toFixed(2)}</span>
                  )}
                </div>
              ) : (
                <div style={{ color: "#ffb347", fontSize: 10, marginTop: 2 }}>
                  no cloud position. place manually after import.
                </div>
              )}
              <div style={{ marginTop: 4 }}>
                <button
                  type="button"
                  onClick={() => handleImport(s)}
                  disabled={!s.local}
                  style={btn(true)}
                >
                  ↓ import
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
