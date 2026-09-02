import { useEffect, useState } from "react";
import { CAMARA_API_BASE } from "../config";

const POLL_MS = 15000;

// Polls the gateway's /adapters proxy. Empty list means the engine is either
// unreachable or unconfigured - the UI treats that as "no diagnostics" rather
// than as an error.
//
// `paused` suspends polling without clearing the last-known adapter list, so
// the header badge keeps its last reading when the tab regains focus.
export function useAdapterHealth(token, { paused = false } = {}) {
  const [adapters, setAdapters] = useState([]);

  useEffect(() => {
    if (!token) return;
    if (paused) return;
    let cancelled = false;
    let timer = null;

    const tick = async () => {
      try {
        const resp = await fetch(`${CAMARA_API_BASE}/adapters`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (!cancelled) setAdapters(data.adapters || []);
      } catch {
        // Keep the last-known list on a transient failure - a single failed
        // poll must not flip the header to "n/a" until the next success.
      } finally {
        if (!cancelled) timer = setTimeout(tick, POLL_MS);
      }
    };
    tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [token, paused]);

  return adapters;
}
