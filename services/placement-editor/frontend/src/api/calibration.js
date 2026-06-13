// Thin client for the WiFi calibration tool. Every call goes through the
// placement-editor backend at `/api/wifi/calibration/*`, which proxies to
// the wifi-positioning service. Keeps the browser on a single origin so
// no CORS is needed on the adapter.

const BASE = "/api/wifi/calibration";

async function jsonFetch(path, options = {}) {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await resp.text();
  let parsed = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    // not JSON; surface the raw text in the error
  }
  if (!resp.ok) {
    const detail = parsed?.detail || text || resp.statusText;
    throw new Error(`HTTP ${resp.status}: ${detail}`);
  }
  return parsed;
}

export const startCapture = ({ x_m, y_m, target_scans = 10 }) =>
  jsonFetch("/capture", {
    method: "POST",
    body: JSON.stringify({ x_m, y_m, target_scans }),
  });

export const pollCapture = (sessionId) => jsonFetch(`/capture/${sessionId}`);

export const cancelCapture = (sessionId) =>
  jsonFetch(`/capture/${sessionId}`, { method: "DELETE" });

export const getState = () => jsonFetch("/state");

export const deleteSample = (sampleId) =>
  jsonFetch(`/samples/${sampleId}`, { method: "DELETE" });

export const clearSamples = () =>
  jsonFetch("/samples", { method: "DELETE" });

export const derive = () => jsonFetch("/derive", { method: "POST" });

export const apply = (per_anchor = null) =>
  jsonFetch("/apply", {
    method: "POST",
    body: JSON.stringify({ per_anchor }),
  });
