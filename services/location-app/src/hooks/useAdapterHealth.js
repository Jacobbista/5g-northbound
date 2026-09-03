import { useEffect, useRef, useState } from "react";
import { CAMARA_API_BASE } from "../config";

const POLL_MS = 15000;

// Graduated severity from consecutive not-live readings, so a single missed poll
// reads as a warning (amber) and only a sustained outage reads as an error (red).
// One reading -> "warn", two or more in a row -> "error". Timing-independent.
function severityFor(streak) {
  if (streak === 0) return "ok";
  return streak === 1 ? "warn" : "error";
}

// Polls the gateway's /adapters proxy. Empty list means the engine is either
// unreachable or unconfigured - the UI treats that as "no diagnostics" rather
// than as an error.
//
// `paused` suspends polling without clearing the last-known adapter list, so
// the header badge keeps its last reading when the tab regains focus.
export function useAdapterHealth(token, { paused = false } = {}) {
  const [adapters, setAdapters] = useState([]);
  // Consecutive not-live count per adapter, driving the graduated severity.
  const streaksRef = useRef({});

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
        const enriched = (data.adapters || []).map((a) => {
          const notLive = a.state ? a.state !== "live" : a.in_cooldown;
          const streak = notLive ? (streaksRef.current[a.name] || 0) + 1 : 0;
          streaksRef.current[a.name] = streak;
          return { ...a, severity: severityFor(streak) };
        });
        if (!cancelled) setAdapters(enriched);
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
