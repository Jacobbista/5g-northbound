// Asset Identity Map client. Talks to the placement-editor backend at
// `/api/assets`, which proxies the camara-gateway (the asset authority).
//
// Asset ONBOARDING UI is the KELT dashboard's, not the editor's (ownership
// split). These are the reusable primitives: read the map, write the map, and
// a non-destructive merge so a caller never blind-overwrites the registry.
const BASE = "/api/assets";

export async function getAssetMap() {
  const resp = await fetch(BASE, { headers: { Accept: "application/json" } });
  if (!resp.ok) throw new Error(`GET /assets -> ${resp.status}`);
  return resp.json();
}

export async function putAssetMap(map) {
  const resp = await fetch(BASE, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(map),
  });
  if (!resp.ok) throw new Error(`PUT /assets -> ${resp.status}`);
  return resp.json();
}

// Additive merge: read the current map, append/replace the given assets keyed
// by asset_id (existing entries for other ids are preserved), write it back.
// The safe write path - PUT replaces the whole map, so onboarding must merge.
export async function upsertAssets(assets) {
  const map = await getAssetMap();
  const byId = new Map((map.assets || []).map((a) => [a.asset_id, a]));
  for (const a of assets) byId.set(a.asset_id, { ...byId.get(a.asset_id), ...a });
  return putAssetMap({ version: map.version || 2, assets: [...byId.values()] });
}
