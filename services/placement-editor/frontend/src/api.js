// Same-origin: editor is served by the same FastAPI process that owns /api/*.
const BASE = "";

export async function loadLayout() {
  const resp = await fetch(`${BASE}/api/layout`);
  if (resp.status === 404) return null;
  if (!resp.ok) throw new Error(`load failed: HTTP ${resp.status}`);
  return resp.json();
}

export async function saveLayout(layout) {
  const resp = await fetch(`${BASE}/api/layout`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(layout),
  });
  if (!resp.ok) throw new Error(`save failed: HTTP ${resp.status}`);
  return resp.json();
}
