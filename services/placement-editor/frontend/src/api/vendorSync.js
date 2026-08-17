// Thin client for the vendor-discovery flow. Calls go through the
// placement-editor backend (/api/vendor/*), which proxies to whichever
// vendor-adapter pod the editor is wired to. No vendor-specific code here;
// shape of `devices[]` is whatever the active schema's discover mapping
// produces.

const BASE = "/api/vendor";

async function jsonFetch(path) {
  const resp = await fetch(`${BASE}${path}`);
  const text = await resp.text();
  let parsed = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    // surface raw text in the error
  }
  if (!resp.ok) {
    const detail = parsed?.detail || text || resp.statusText;
    throw new Error(`HTTP ${resp.status}: ${detail}`);
  }
  return parsed;
}

export const discoverDevices = () => jsonFetch("/discover");
export const fetchVendorSchema = () => jsonFetch("/schema");
