import { useEffect, useState } from "react";
import { CAMARA_API_BASE } from "../config";

const PALETTE = ["#1976d2", "#43a047", "#e67e22", "#8e44ad", "#c0392b", "#16a085"];

// Fetches the Asset Identity Map from the gateway (GET /assets). Assets, not
// subscribers: keyed by assetId, with positioningId for the live-stream join.
// Falls back to an empty list on error so the UI keeps rendering.
export function useDevices(token) {
  const [devices, setDevices] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${CAMARA_API_BASE}/assets`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (cancelled) return;
        setDevices(
          (data.assets || []).map((a, i) => {
            // Asset schema v3: an asset binds one or more capabilities. The live
            // stream keys on the primary capability's positioning id (the
            // gateway sets the fused entry's device_id to it), so join on that.
            const primary = (a.capabilities && a.capabilities[0]) || {};
            return {
              assetId: a.asset_id,
              positioningId: a.positioning_id ?? primary.positioning_id,
              kind: a.kind,
              source: a.source ?? primary.source,
              org: a.org,
              label: a.label || a.asset_id,
              color: PALETTE[i % PALETTE.length],
            };
          })
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
