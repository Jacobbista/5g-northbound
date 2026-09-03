import { useEffect, useState } from "react";
import { CAMARA_API_BASE } from "../config";

// Fetches the gateway's device-diagnostics extension for one asset on demand
// (device selection), not on the stream cadence. Vendor fidelity: link quality,
// accuracy provenance, motion. Pass null to clear.
export function useDeviceDiagnostics(token, assetId) {
  const [diagnostics, setDiagnostics] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  // Clear the previous asset's diagnostics on selection change so a panel switch
  // never shows the old asset's battery / x_vendor for a frame.
  useEffect(() => {
    setDiagnostics(null);
    setError(null);
  }, [assetId]);

  useEffect(() => {
    if (!token || !assetId) {
      setDiagnostics(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const url = `${CAMARA_API_BASE}/device-diagnostics/v0/${encodeURIComponent(assetId)}`;
        const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
        if (cancelled) return;
        setDiagnostics(resp.ok ? (await resp.json()).diagnostics : null);
        setError(resp.ok ? null : `HTTP ${resp.status}`);
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, assetId]);

  return { diagnostics, loading, error };
}
