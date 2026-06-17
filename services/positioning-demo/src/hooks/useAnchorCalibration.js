import { useEffect, useState } from "react";
import { CAMARA_API_BASE } from "../config";

// Fetches the gateway's /anchors/calibration vendor extension once: the real
// per-AP RF model params (tx_power reference + path-loss n) measured by the
// wifi calibration DERIVE, keyed by anchor id. Empty {} when unavailable, so
// the panel degrades to "no calibration" instead of showing invented values.
export function useAnchorCalibration(token) {
  const [params, setParams] = useState({});

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${CAMARA_API_BASE}/anchors/calibration`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!resp.ok) return;
        const data = await resp.json();
        if (!cancelled) setParams(data.params || {});
      } catch {
        /* degrade silently: no calibration shown */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return params;
}
