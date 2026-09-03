import { useEffect, useRef, useState } from "react";
import { CAMARA_API_BASE } from "../config";

// Live position feed from the gateway's WebSocket.
//
// `CAMARA_API_BASE` is http(s); the WebSocket URL swaps the scheme to ws(s)
// and points at `/positions/stream`. Browsers cannot set an Authorization
// header on a WS handshake, so the token rides the Sec-WebSocket-Protocol
// header instead of the URL: the client offers ["bearer.jwt", <token>] and the
// gateway echoes "bearer.jwt". This keeps the token out of the URL, access logs
// and history. The gateway validates it against the same Keycloak realm + role
// as the REST endpoints.
//
// Returns:
//   {
//     byDeviceId: { <device_id>: { latitude, longitude, accuracy_m, timestamp, sources, strategy } },
//     connected: bool,
//   }
//
// Connection lifecycle:
//   - Opens on mount once a token is available.
//   - Reconnects with exponential backoff capped at 8 s when the upstream
//     closes (engine restart, network blip).
//   - `paused` closes the socket and keeps the last payload visible.
const RECONNECT_INITIAL_MS = 500;
const RECONNECT_MAX_MS = 8000;

// The token carrier: a scheme marker the gateway echoes to accept the handshake.
const WS_TOKEN_SCHEME = "bearer.jwt";

function buildWsUrl() {
  // CAMARA_API_BASE typically reads like "http://localhost:8087". Swap to
  // ws/wss while keeping host + port. URL constructor handles both
  // relative ("/api") and absolute bases. No token in the URL: it rides the
  // Sec-WebSocket-Protocol header (see connect()).
  const base = new URL(CAMARA_API_BASE, window.location.origin);
  const proto = base.protocol === "https:" ? "wss:" : "ws:";
  const path = `${base.pathname.replace(/\/$/, "")}/positions/stream`;
  return `${proto}//${base.host}${path}`;
}

export function usePositionsStream(token, { paused = false } = {}) {
  const [byDeviceId, setByDeviceId] = useState({});
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const backoffRef = useRef(RECONNECT_INITIAL_MS);

  useEffect(() => {
    if (!token || paused) {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      setConnected(false);
      return;
    }

    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      const ws = new WebSocket(buildWsUrl(), [WS_TOKEN_SCHEME, token]);
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) return;
        backoffRef.current = RECONNECT_INITIAL_MS;
        setConnected(true);
      };

      ws.onmessage = (event) => {
        if (cancelled) return;
        try {
          const payload = JSON.parse(event.data);
          if (!Array.isArray(payload)) return;
          setByDeviceId((prev) => {
            const next = { ...prev };
            for (const item of payload) {
              if (!item?.device_id) continue;
              next[item.device_id] = item;
            }
            return next;
          });
        } catch {
          // ignore malformed frame; the engine should never send one
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setConnected(false);
        wsRef.current = null;
        const delay = backoffRef.current;
        backoffRef.current = Math.min(delay * 2, RECONNECT_MAX_MS);
        reconnectTimerRef.current = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        // onclose fires immediately after onerror; let it handle reconnect.
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      setConnected(false);
    };
  }, [token, paused]);

  return { byDeviceId, connected };
}
