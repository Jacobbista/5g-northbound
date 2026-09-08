// Liveness from the device's last communication, against a per-device adaptive
// threshold.
//
// Why adaptive: a vendor may report on a variable cadence (wittra drives it
// from an accelerometer - frequent while moving, sparse while still) and
// freezes the fix timestamp of a still asset that is still reporting. So the
// fix age cannot tell alive from dead, and no single silence threshold fits
// both a mover reporting every few seconds and a still tag reporting every few
// minutes. Each device is instead measured against its own observed rhythm: it
// reads stale once silent for longer than a multiple of its recent typical
// reporting gap, clamped so one missed report never flags a fast mover and a
// long-dead device is flagged even if it always reported slowly.

export const STALE_FACTOR = 3;
export const STALE_FLOOR_SECS = 30;
export const STALE_CAP_SECS = 3600;
const MAX_SAMPLES = 10;

export function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

// Seconds of silence past which a device reads stale. With no rhythm learned
// yet the cap applies: an unknown cadence must not flag a slow reporter dead.
export function staleBoundSecs(gaps) {
  const typical = median(gaps);
  if (typical == null) return STALE_CAP_SECS;
  return Math.min(STALE_CAP_SECS, Math.max(STALE_FLOOR_SECS, typical * STALE_FACTOR));
}

// Keep the most recent gaps only, so a device that changes rhythm (starts
// moving) re-calibrates instead of being judged by its idle past.
export function appendGap(gaps, prevSecs, nextSecs) {
  if (prevSecs == null || nextSecs == null || nextSecs <= prevSecs) return gaps;
  return [...gaps, nextSecs - prevSecs].slice(-MAX_SAMPLES);
}

export function toEpochSecs(value) {
  if (value == null) return null;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : ms / 1000;
}

const tracker = new Map(); // deviceId -> { last: epochSecs, gaps: number[] }

export function resetLiveness() {
  tracker.clear();
}

// Learn the device's rhythm. Only a CHANGED last-communication counts as a
// report: the same value arriving on every broadcast tick says nothing new.
export function recordLastSeen(deviceId, lastSeen) {
  const secs = toEpochSecs(lastSeen);
  if (!deviceId || secs == null) return;
  const entry = tracker.get(deviceId) || { last: null, gaps: [] };
  if (entry.last === secs) return;
  tracker.set(deviceId, { last: secs, gaps: appendGap(entry.gaps, entry.last, secs) });
}

export function gapsFor(deviceId) {
  return tracker.get(deviceId)?.gaps || [];
}

// "live" | "stale" | "offline" from the device's own last communication.
// offline only when there is no such signal at all.
export function livenessFor(deviceId, lastSeen, now = Date.now()) {
  const secs = toEpochSecs(lastSeen);
  if (secs == null) return "offline";
  const ageSecs = Math.max(0, now / 1000 - secs);
  return ageSecs > staleBoundSecs(gapsFor(deviceId)) ? "stale" : "live";
}
