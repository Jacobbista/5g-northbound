import { useEffect, useState } from "react";
import { CAMARA_API_BASE } from "../config";

const DETAILS_POLL_MS = 4000;

// Fetches the gateway's vendor-extension /assets/{assetId}/details endpoint
// for one asset. Surfaces engine-side fields (strategy, sources, accuracy)
// that the CAMARA Location response intentionally hides. Polls only while an
// assetId is supplied; pass null to pause.
//
// `paused` (e.g. driven by usePageActive) suspends polling without clearing
// the last-known details, so a backgrounded tab keeps showing its last
// position when refocused while pausing all network work in the meantime.
export function useDeviceDetails(token, assetId, { paused = false } = {}) {
  const [details, setDetails] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token || !assetId) {
      setDetails(null);
      setLoading(false);
      return;
    }
    if (paused) return; // keep last details on screen, stop the poll
    let cancelled = false;
    const poll = async () => {
      try {
        const url = `${CAMARA_API_BASE}/assets/${encodeURIComponent(assetId)}/details`;
        const resp = await fetch(url, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (resp.status === 404) {
          // Asset registered but no positional fix available -> "offline",
          // not a UI error.
          if (!cancelled) {
            setDetails(null);
            setError(null);
          }
          return;
        }
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (cancelled) return;
        setDetails(data);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    poll();
    const id = setInterval(poll, DETAILS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [token, assetId, paused]);

  return { details, error, loading };
}
