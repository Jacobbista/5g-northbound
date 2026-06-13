// EMA: exponentially-weighted moving average for 2D points. Pure, framework-free.
// alpha=1 -> no smoothing; alpha=0 -> never update. ~0.35 absorbs roughly three
// samples worth of jitter without introducing visible lag at 0.5 Hz polling.
export function ema2d(prev, next, alpha) {
  if (!prev) return { x: next.x, z: next.z };
  return {
    x: prev.x + alpha * (next.x - prev.x),
    z: prev.z + alpha * (next.z - prev.z),
  };
}
