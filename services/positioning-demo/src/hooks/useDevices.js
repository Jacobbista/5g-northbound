import { useEffect, useState } from "react";
import { CAMARA_API_BASE } from "../config";

const PALETTE = ["#1976d2", "#43a047", "#e67e22", "#8e44ad", "#c0392b", "#16a085"];

// Fetches the registered device list from the gateway's vendor-extension
// discovery endpoint. Falls back to an empty list on error so the UI keeps
// rendering instead of blowing up.
export function useDevices(token) {
  const [devices, setDevices] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${CAMARA_API_BASE}/devices`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (cancelled) return;
        setDevices(
          (data.devices || []).map((d, i) => ({
            phoneNumber: d.phoneNumber,
            deviceId: d.deviceId,
            label: d.label || d.deviceId,
            simulated: Boolean(d.simulated),
            color: PALETTE[i % PALETTE.length],
          }))
        );
        setError(null);
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return { devices, error, loading };
}
