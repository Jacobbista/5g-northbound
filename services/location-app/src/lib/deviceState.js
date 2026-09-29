import { livenessFor } from "./liveness.js";
import { isImprecise } from "./imprecision.js";

// Without a last-communication signal, a fix older than this is stale.
export const STALE_MS = 30000;

// The display state of one asset: "live", "imprecise", "stale" or "offline".
// One function for the sidebar row, the detail pill and the 3D marker, so they
// never disagree about the same asset.
export function deviceState({ position, deviceId }) {
  const imprecise = isImprecise(position);
  // Prefer the device's own last communication when the source reports it,
  // judged against that device's learned cadence. Neither the fix time (which
  // freezes for a still asset) nor observedAt (fresh on every tick) can tell a
  // quiet device from a live one.
  if (position?.lastSeen) {
    const state = livenessFor(deviceId, position.lastSeen);
    if (state !== "live") return state;
    return imprecise ? "imprecise" : "live";
  }
  // No last-communication signal: the fix age is the signal left.
  const liveAt = position?.lastLocationTime;
  if (!liveAt) return "offline";
  const ageMs = Date.now() - new Date(liveAt).getTime();
  if (ageMs > STALE_MS) return "stale";
  return imprecise ? "imprecise" : "live";
}
