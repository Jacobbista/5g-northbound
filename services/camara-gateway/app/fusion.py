"""Asset-level fusion: reconcile the per-capability fixes of one asset into one.

This is a-posteriori (fix-level) fusion: each source has already produced a
position estimate, so the gateway combines estimates, never raw observables. It
lives at the gateway because that is the layer that knows an asset's
capabilities; the engine stays asset-agnostic and fuses only redundant reports
of the same positioning id.

Estimates combine by inverse-variance weighting: a fix of accuracy `a` gets
weight `1/a^2`, so a sharper source dominates and the fused radius shrinks. A
capability with no current fix contributes nothing, so an asset stays located as
its coverage changes."""

import math
from typing import Any, Optional


def fuse_fixes(fixes: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Combine per-capability fixes into one. Each fix is a dict with
    `latitude`, `longitude`, `accuracy_m`, and optionally `altitude`,
    `timestamp`, `observed_at`, `sources`. Returns the fused fix, or None when
    no fix carries a usable position."""
    usable = [
        f for f in fixes
        if f.get("latitude") is not None
        and f.get("longitude") is not None
        and isinstance(f.get("accuracy_m"), (int, float))
        and f["accuracy_m"] > 0
    ]
    if not usable:
        return None
    if len(usable) == 1:
        return _normalise(usable[0])

    weights = [1.0 / (f["accuracy_m"] ** 2) for f in usable]
    wsum = sum(weights)
    lat = sum(w * f["latitude"] for w, f in zip(weights, usable)) / wsum
    lon = sum(w * f["longitude"] for w, f in zip(weights, usable)) / wsum
    accuracy = math.sqrt(1.0 / wsum)

    # Altitude and timestamps come from the sharpest fix (lowest accuracy_m);
    # not every source reports altitude, and the freshest position anchors time.
    best = min(usable, key=lambda f: f["accuracy_m"])
    sources: list[str] = []
    for f in usable:
        for s in _sources_of(f):
            if s not in sources:
                sources.append(s)

    out: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "accuracy_m": accuracy,
        "altitude": best.get("altitude"),
        "sources": sources,
    }
    ts = _latest(usable, "timestamp")
    if ts is not None:
        out["timestamp"] = ts
    obs = _latest(usable, "observed_at")
    if obs is not None:
        out["observed_at"] = obs
    return out


def _normalise(fix: dict[str, Any]) -> dict[str, Any]:
    out = dict(fix)
    out["sources"] = _sources_of(fix)
    return out


def _sources_of(fix: dict[str, Any]) -> list[str]:
    s = fix.get("sources")
    if isinstance(s, list) and s:
        return list(s)
    single = fix.get("source")
    return [single] if single else []


def _latest(fixes: list[dict[str, Any]], key: str) -> Any:
    vals = [f[key] for f in fixes if f.get(key) is not None]
    return max(vals) if vals else None
