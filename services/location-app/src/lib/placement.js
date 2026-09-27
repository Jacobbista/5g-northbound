// Placing a synthetic asset on the floor plan, and taking it off again.
//
// The gateway surface is asset-shaped: the caller names an assetId and the
// gateway resolves the positioning id and the source behind it. Coordinates
// are in the room frame: metres from the room's lower-left corner, x along the
// width, y along the depth. The response names the room.
import { CAMARA_API_BASE } from "../config";
import { sourcesAdvertising } from "./capabilities";


async function call(method, token, assetId, body) {
  const resp = await fetch(`${CAMARA_API_BASE}/assets/${encodeURIComponent(assetId)}/placement`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!resp.ok) {
    // The gateway answers a refusal in the CAMARA envelope, so surface its
    // message rather than a bare status the operator cannot act on.
    let detail = `HTTP ${resp.status}`;
    try {
      const err = await resp.json();
      if (err?.message) detail = err.message;
    } catch {
      // Non-JSON error body: the status is all there is.
    }
    throw new Error(detail);
  }
  return resp.json();
}

// Put the asset at a point and start it reporting from there. Placing an
// already-placed asset moves it. Returns where it actually landed, since the
// source clamps the point into the room.
export function placeAsset(token, assetId, { x, y }) {
  return call("PUT", token, assetId, { x, y });
}

// Stop the asset reporting. It then has no position, the same as any source
// that has gone quiet.
export function removeAsset(token, assetId) {
  return call("DELETE", token, assetId);
}

// Which sources accept placement, from what the adapters advertise. A source
// that measures its position has nothing to place, so it is absent here and
// its assets are never draggable.
export function placeableSources(adapters = []) {
  return sourcesAdvertising(adapters, "placement");
}
