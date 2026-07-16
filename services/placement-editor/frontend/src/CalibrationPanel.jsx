import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "./toast.js";
import {
  apply as apiApply,
  cancelCapture,
  clearSamples,
  derive as apiDerive,
  deleteSample,
  getBindings,
  getState,
  pollCapture,
  putBindings,
  startCapture,
} from "./api/calibration.js";

const POLL_MS = 500;

const panel = {
  width: "100%",
  padding: "10px 12px",
  borderRadius: 8,
  background: "rgba(11,17,32,0.96)",
  border: "1px solid rgba(93,255,176,0.35)",
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
    ? "rgba(93,255,176,0.20)"
    : "transparent",
  color: danger ? "#ff6b78" : active ? "#5dffb0" : "#9aa9c4",
  border: `1px solid ${danger ? "#ff6b7855" : active ? "#5dffb0aa" : "#9aa9c455"}`,
  borderRadius: 4,
  fontFamily: "ui-monospace, monospace",
  cursor: "pointer",
});

const pill = (color) => ({
  display: "inline-block",
  padding: "1px 6px",
  borderRadius: 3,
  fontSize: 9,
  color,
  border: `1px solid ${color}`,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
});

// `CalibrationPanel` lives in the right rail when the operator activates
// the calibrate tool in section 3 of the placement editor.
//
// Props:
//   active                 boolean
//   pendingClick           { x_m, y_m } | null     where the operator just clicked
//   onPendingHandled       () => void              clear pendingClick after start
//   roomBounds             { w, h }                used to mark recommended spots
//   anchors                [{ id, x, y, technology }]
//   onSamplesChanged       (samples) => void       lets the canvas redraw markers
//   onClose                () => void
export function CalibrationPanel({
  active,
  pendingClick,
  onPendingHandled,
  anchors,
  onSamplesChanged,
  onClose,
}) {
  const [samples, setSamples] = useState([]);
  const [session, setSession] = useState(null);
  const [derived, setDerived] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const pollTimerRef = useRef(null);
  const fileRef = useRef(null);

  const wifiAnchors = (anchors || []).filter(
    (a) => (a.technology || "wifi") === "wifi"
  );

  const reloadState = useCallback(async () => {
    try {
      const s = await getState();
      setSamples(s.samples || []);
      onSamplesChanged?.(s.samples || []);
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, [onSamplesChanged]);

  const handleExport = useCallback(async () => {
    try {
      const doc = await getBindings();
      const blob = new Blob([JSON.stringify(doc, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "wifi-config.json";
      a.click();
      URL.revokeObjectURL(url);
      setError(null);
    } catch (err) {
      setError(`export failed: ${err.message}`);
    }
  }, []);

  const handleImportBindings = useCallback(
    async (e) => {
      const file = e.target.files?.[0];
      e.target.value = ""; // allow re-importing the same file
      if (!file) return;
      let doc;
      try {
        doc = JSON.parse(await file.text());
      } catch (err) {
        setError(`import failed: not valid JSON (${err.message})`);
        return;
      }
      const n = Array.isArray(doc?.bindings)
        ? doc.bindings.length
        : Array.isArray(doc?.routers)
        ? doc.routers.length
        : 0;
      if (
        !confirm(
          `Replace the live wifi bindings with this file (${n} anchors)? This overwrites the current per-venue config (BSSIDs + RF + samples).`
        )
      )
        return;
      try {
        setBusy(true);
        const out = await putBindings(doc);
        setDerived(null);
        setError(null);
        await reloadState();
        toast(
          out.reloaded === false
            ? `Imported ${out.bindings} bindings. wifi-positioning is still loading the blueprint; they apply once it is ready.`
            : `Imported ${out.bindings} bindings, ${out.samples} samples. Live config reloaded.`,
          out.reloaded === false ? "warn" : "info"
        );
      } catch (err) {
        setError(`import failed: ${err.message}`);
      } finally {
        setBusy(false);
      }
    },
    [reloadState]
  );

  useEffect(() => {
    if (!active) return;
    reloadState();
  }, [active, reloadState]);

  // Drive a capture started by a canvas click in the parent. We keep
  // the session locally, polling progress until it completes, then
  // refresh the sample list.
  useEffect(() => {
    if (!pendingClick || !active) return;
    let cancelled = false;
    (async () => {
      try {
        setBusy(true);
        setError(null);
        const created = await startCapture({
          x_m: pendingClick.x_m,
          y_m: pendingClick.y_m,
          target_scans: 10,
        });
        if (cancelled) return;
        setSession(created);
        onPendingHandled?.();
      } catch (e) {
        setError(e.message);
        setBusy(false);
        onPendingHandled?.();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pendingClick, active, onPendingHandled]);

  useEffect(() => {
    if (!session || session.done) return;
    const tick = async () => {
      try {
        const s = await pollCapture(session.id);
        setSession(s);
        if (s.done) {
          setBusy(false);
          await reloadState();
        }
      } catch (e) {
        setError(e.message);
        setBusy(false);
      }
    };
    pollTimerRef.current = setInterval(tick, POLL_MS);
    return () => clearInterval(pollTimerRef.current);
  }, [session, reloadState]);

  const handleCancel = useCallback(async () => {
    if (!session) return;
    try {
      await cancelCapture(session.id);
    } catch {
      // ignore; user probably cancelled an already-finished session
    }
    setSession(null);
    setBusy(false);
  }, [session]);

  const handleDelete = useCallback(
    async (id) => {
      try {
        await deleteSample(id);
        await reloadState();
      } catch (e) {
        setError(e.message);
      }
    },
    [reloadState]
  );

  const handleClear = useCallback(async () => {
    if (!confirm("Delete every calibration sample? This cannot be undone.")) return;
    try {
      await clearSamples();
      setDerived(null);
      await reloadState();
    } catch (e) {
      setError(e.message);
    }
  }, [reloadState]);

  const handleDerive = useCallback(async () => {
    try {
      setBusy(true);
      const out = await apiDerive();
      setDerived(out.per_anchor || {});
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, []);

  const handleApply = useCallback(async () => {
    if (!derived) return;
    try {
      setBusy(true);
      const out = await apiApply(derived);
      setError(null);
      const n = Object.keys(out.applied || {}).length;
      toast(
        out.reloaded === false
          ? `Saved params for ${n} anchors. wifi-positioning is still loading the blueprint; they apply once it is ready.`
          : `Applied to ${n} anchors.`,
        out.reloaded === false ? "warn" : "info"
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [derived]);

  if (!active) return null;

  // Coverage per anchor: how many samples include each one.
  const coverage = {};
  for (const a of wifiAnchors) coverage[a.id] = 0;
  // BSSID -> anchor lookup; we don't actually know the bindings here,
  // so coverage is counted via the rssi_by_anchor keys (which are
  // BSSIDs). The wifi-positioning service maps BSSIDs to anchors at
  // derive time. For the UI we just count samples per anchor by
  // distance: a sample is "covered" by anchor A if at least one BSSID
  // exists in it that matches A. We can't do that without the binding
  // map, so we just show total sample count here.
  const total = samples.length;

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
          borderBottom: "1px solid rgba(93,255,176,0.25)",
        }}
      >
        <strong
          style={{
            color: "#5dffb0",
            letterSpacing: "0.06em",
            fontSize: 12,
          }}
        >
          ↹ wifi calibration
        </strong>
        <button type="button" onClick={onClose} style={btn(false)}>
          ✕ close
        </button>
      </div>

      <div style={{ fontSize: 11, color: "#9aa9c4", lineHeight: 1.5, marginBottom: 8 }}>
        Walk the room. Click on the canvas where you are standing, hold still while
        the device collects 10 scans. Repeat at 8 to 12 points to cover each AP from
        at least 3 distances. Aim for 1 m, 5 m, and 8 m from each AP.
      </div>

      <div style={sectionTitle}>· transfer</div>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <button
          type="button"
          onClick={handleExport}
          disabled={busy}
          style={btn(false)}
          title="Download the live per-venue bindings (BSSIDs + RF params + samples) as wifi-config.json. Carry it to another cluster and import there."
        >
          ⇩ export bindings
        </button>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          style={btn(false)}
          title="Upload a wifi-config.json / bindings file to REPLACE the live per-venue config (BSSIDs + RF + samples) and hot-reload. Use to seed a fresh cluster from one calibrated on the demo."
        >
          ⇪ import bindings
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="application/json,.json"
          onChange={handleImportBindings}
          style={{ display: "none" }}
        />
      </div>
      <div style={{ fontSize: 10, color: "#7a8aab", margin: "4px 0 2px" }}>
        Calibrate on the demo, export, import here: the full config (BSSIDs + RF +
        samples) travels as one file. Import replaces the live bindings and
        hot-reloads.
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

      {session && !session.done && (
        <div
          style={{
            background: "rgba(255,179,71,0.10)",
            border: "1px solid #ffb34755",
            padding: "8px",
            borderRadius: 4,
            marginBottom: 8,
          }}
        >
          <div style={{ color: "#ffb347", fontWeight: 600, marginBottom: 4 }}>
            recording at ({session.x_m.toFixed(2)}, {session.y_m.toFixed(2)})
          </div>
          <div
            style={{
              height: 6,
              background: "rgba(255,255,255,0.06)",
              borderRadius: 3,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${(session.collected / session.target_scans) * 100}%`,
                background: "#ffb347",
                transition: "width 0.2s",
              }}
            />
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginTop: 6,
              fontSize: 10,
              color: "#9aa9c4",
            }}
          >
            <span>
              {session.collected} / {session.target_scans} scans
            </span>
            <button type="button" onClick={handleCancel} style={btn(false, true)}>
              ✕ cancel
            </button>
          </div>
        </div>
      )}

      <div style={sectionTitle}>· samples ({total})</div>
      {samples.length === 0 && (
        <div style={{ color: "#5a6987", fontSize: 10, padding: "4px 0" }}>
          none yet. click on the canvas to record one.
        </div>
      )}
      <div style={{ maxHeight: 180, overflowY: "auto" }}>
        {samples.map((s) => (
          <div
            key={s.id}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "4px 6px",
              borderRadius: 3,
              marginBottom: 3,
              background: "rgba(93,255,176,0.05)",
              border: "1px solid rgba(93,255,176,0.15)",
            }}
          >
            <span style={{ color: "#aaffd6" }}>
              ({s.x_m.toFixed(1)}, {s.y_m.toFixed(1)}){" "}
              <span style={{ color: "#7a8aab" }}>
                {Object.keys(s.rssi_by_anchor || {}).length} BSSID, {s.n_scans} scans
              </span>
            </span>
            <button
              type="button"
              onClick={() => handleDelete(s.id)}
              style={{
                background: "transparent",
                border: "none",
                color: "#ff6b78",
                cursor: "pointer",
                fontSize: 10,
              }}
              title="remove this sample"
            >
              ✕
            </button>
          </div>
        ))}
      </div>

      {samples.length > 0 && (
        <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
          <button
            type="button"
            onClick={handleDerive}
            disabled={busy || samples.length < 3}
            style={btn(true)}
            title="run a log-distance fit per AP using the current samples"
          >
            ⚙ derive
          </button>
          <button
            type="button"
            onClick={handleClear}
            disabled={busy}
            style={btn(false, true)}
          >
            ✕ clear all
          </button>
        </div>
      )}

      {derived && (
        <>
          <div style={sectionTitle}>· derived params</div>
          <div
            style={{
              border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 4,
              overflow: "hidden",
            }}
          >
            <table style={{ width: "100%", fontSize: 10, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: "rgba(255,255,255,0.04)", color: "#7a8aab" }}>
                  <th style={{ padding: "4px 6px", textAlign: "left" }}>id</th>
                  <th style={{ padding: "4px 6px" }}>tx_power</th>
                  <th style={{ padding: "4px 6px" }}>n</th>
                  <th style={{ padding: "4px 6px" }}>R²</th>
                  <th style={{ padding: "4px 6px" }}>pts</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(derived).map(([anchorId, params]) => {
                  const ok = params.tx_power != null;
                  return (
                    <tr
                      key={anchorId}
                      style={{
                        borderTop: "1px solid rgba(255,255,255,0.04)",
                        color: ok ? "#e6edf7" : "#5a6987",
                      }}
                    >
                      <td style={{ padding: "4px 6px", color: "#aaffd6" }}>
                        {anchorId}
                      </td>
                      <td style={{ padding: "4px 6px", textAlign: "center" }}>
                        {params.tx_power ?? "-"}
                      </td>
                      <td style={{ padding: "4px 6px", textAlign: "center" }}>
                        {params.path_loss_n ?? "-"}
                      </td>
                      <td style={{ padding: "4px 6px", textAlign: "center" }}>
                        {params.r2 ?? "-"}
                      </td>
                      <td style={{ padding: "4px 6px", textAlign: "center" }}>
                        {params.n_points ?? "-"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 10, color: "#7a8aab", marginTop: 4 }}>
            Rows with - mean the anchor has fewer than 3 sample points. Add more
            and re-derive; only filled rows are written on apply.
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
            <button
              type="button"
              onClick={handleApply}
              disabled={
                busy ||
                !Object.values(derived).some((p) => p.tx_power != null)
              }
              style={btn(true)}
            >
              ✓ apply
            </button>
          </div>
        </>
      )}
    </aside>
  );
}
