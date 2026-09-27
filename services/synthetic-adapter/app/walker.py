import json
import logging
import math
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

from .config import Settings

log = logging.getLogger(__name__)

# A device is "at" its waypoint when within this distance; the walker then
# picks a new one. Small enough that the device doesn't visibly stop, large
# enough that float jitter never holds it back from advancing.
_WAYPOINT_TOLERANCE_M = 0.4
# When a step would cross a wall, back off by this margin so the device
# never lands flush against the wall (avoids re-collision next step).
_WALL_MARGIN_M = 0.15
# Keep the device this far inside the room AABB: waypoints are sampled with
# it, and the emitted position is clamped to it, so the marker never renders
# on or past the perimeter wall.
_ROOM_INSET_M = 0.5
# Cap dt between polls so a long pause doesn't teleport the device. The
# adapter typically polls at 1 Hz; if a poll is missed for minutes the
# device should still only advance a few seconds' worth of distance.
_MAX_DT_S = 2.0

# Quality relaxes back toward this level between episodes, and sinks toward
# this floor during one. Neither is reached exactly: the pull is proportional
# to the remaining gap, so the value keeps moving without ever snapping.
_QUALITY_BASELINE = 0.92
_QUALITY_DEGRADED = 0.15
# Fraction of the remaining gap closed per second. Slow enough that the
# rendered radius breathes rather than flickers.
_QUALITY_RATE_PER_S = 0.55
# Jitter added per second of drift, so a clean stretch is not a flat line.
_QUALITY_JITTER = 0.05
# Curve applied to (1 - quality) when mapping onto the accuracy band. Above 1
# it pushes the mass toward the good end and leaves a thin tail toward the
# bad one, which is the shape indoor error actually has.
_ACCURACY_SKEW = 2.2
# A freshly placed device sits still for this long before it starts wandering.
# Without it the first poll already moves it a metre, so the marker appears
# away from where it was dropped and the placement reads as imprecise.
_SETTLE_S = 2.0


@dataclass
class _Segment:
    """Wall segment in room metres. Stores derived geometry once so per-step
    intersection checks stay cheap."""

    x1: float
    y1: float
    x2: float
    y2: float
    thickness: float
    # 1-D ranges along the segment (distance from (x1, y1)) where the wall
    # is OPEN (door / window). A movement crossing the wall inside one of
    # these ranges does not block.
    open_ranges: list[tuple[float, float]] = field(default_factory=list)

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)


@dataclass
class _State:
    # Room frame: x along the width, y along the depth, z the height above the
    # floor. Origin at the room's lower-left corner.
    x: float
    y: float
    z: float
    waypoint: Optional[tuple[float, float]] = None
    last_ts: float = 0.0
    # Fix quality in [0, 1], 1 = clean. One latent variable drives both the
    # reported accuracy and the reported confidence, because in a real source
    # they move together: an obstructed or badly-conditioned fix is both less
    # precise AND less trusted. Drawing them independently would emit pairs no
    # real source produces, and the fusion weight is literally
    # `confidence / accuracy`, so the pair is exactly what matters.
    quality: float = 1.0
    degraded_until: float = 0.0
    # Stays put until this time. Set on placement so the device is still where
    # it was dropped when the first fix reaches the consumer.
    hold_until: float = 0.0
    # Whether this device is currently reporting. Only consulted when
    # `spawn_required` is on; otherwise every device walks from boot.
    active: bool = True


def _segments_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    s: _Segment,
) -> Optional[tuple[float, float, float]]:
    """Intersection of the device's planned step p1→p2 with wall segment s.

    Returns (ix, iy, dist_along_wall) if they cross inside both segments,
    None otherwise. dist_along_wall is the distance from (s.x1, s.y1) to the
    crossing point; callers use it to check whether the crossing falls
    inside an opening on the wall.
    """
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = s.x1, s.y1
    x4, y4 = s.x2, s.y2
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-9:
        return None  # parallel / collinear: ignore
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
    if not (0.0 <= t <= 1.0 and 0.0 <= u <= 1.0):
        return None
    ix = x1 + t * (x2 - x1)
    iy = y1 + t * (y2 - y1)
    dist = u * s.length
    return ix, iy, dist


def _crossing_blocked(dist_along: float, ranges: list[tuple[float, float]]) -> bool:
    for a, b in ranges:
        if a <= dist_along <= b:
            return False
    return True


BLUEPRINT_VERSION = 3


def _first_room(data: dict) -> Optional[dict]:
    """The first room of a version 3 blueprint, or None. An older document uses
    another frame and is not read."""
    if data.get("version") != BLUEPRINT_VERSION:
        log.warning(
            "synthetic-adapter: blueprint version %r; this adapter reads version %d",
            data.get("version"), BLUEPRINT_VERSION,
        )
        return None
    rooms = data.get("rooms") or []
    return rooms[0] if rooms and rooms[0].get("id") else None


def _load_segments_from_data(data: dict) -> tuple[list[_Segment], Optional[tuple[float, float]]]:
    """Walls and footprint of the first room of a version 3 blueprint, in the
    room frame. Returns (segments, (width_m, depth_m)). Empty or malformed input
    returns ([], None) so the walker falls back to the configured extent without
    crashing the service.
    """
    room = _first_room(data)
    if room is None:
        return [], None
    w = float(room.get("width_m", 0) or 0)
    d = float(room.get("depth_m", 0) or 0)
    wall_data = room.get("walls") or []
    bounds = (w, d) if w > 0 and d > 0 else None
    segments: list[_Segment] = []
    for w_obj in wall_data:
        try:
            seg = _Segment(
                x1=float(w_obj["x1"]),
                y1=float(w_obj["y1"]),
                x2=float(w_obj["x2"]),
                y2=float(w_obj["y2"]),
                thickness=float(w_obj.get("thickness") or 0.2),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if seg.length < 0.05:
            continue
        # Convert openings into 1-D pass-through ranges along the wall.
        for o in w_obj.get("openings") or []:
            try:
                a = max(0.0, min(seg.length, float(o["start_m"])))
                b = max(0.0, min(seg.length, float(o["end_m"])))
            except (KeyError, TypeError, ValueError):
                continue
            if b - a > 0.02:
                seg.open_ranges.append((min(a, b), max(a, b)))
        segments.append(seg)

    # Perimeter walls, from the room outline when present, otherwise from the
    # four sides of the rectangle. Each edge becomes a wall segment whose
    # openings are the `perimeter_openings` entries matching its edge_index.
    # `side` fields are lifted to indices using the rectangle convention.
    if bounds is not None:
        edges = _perimeter_edges(room, bounds)
        perim_open = room.get("perimeter_openings") or []
        side_to_index = {"N": 0, "E": 1, "S": 2, "W": 3}
        for idx, edge in enumerate(edges):
            seg = _Segment(
                x1=edge["start"][0],
                y1=edge["start"][1],
                x2=edge["start"][0] + edge["dir"][0] * edge["length"],
                y2=edge["start"][1] + edge["dir"][1] * edge["length"],
                thickness=0.15,
            )
            for o in perim_open:
                ei = o.get("edge_index")
                if ei is None:
                    ei = side_to_index.get(o.get("side"))
                if ei is None or int(ei) != idx:
                    continue
                try:
                    a = max(0.0, min(edge["length"], float(o["start_m"])))
                    b = max(0.0, min(edge["length"], float(o["end_m"])))
                except (KeyError, TypeError, ValueError):
                    continue
                if b - a > 0.02:
                    seg.open_ranges.append((min(a, b), max(a, b)))
            segments.append(seg)
    return segments, bounds


def _perimeter_edges(
    room: dict, bounds: tuple[float, float]
) -> list[dict]:
    """Room perimeter edges in room metres.

    An outline (`shape: [[x, y], ...]`, room coordinates) yields one edge per
    vertex pair. A rectangle yields the four sides of blueprint version 3, each
    starting from the corner its offsets are measured from:
        0 = N (0,D)->(W,D), 1 = E (W,D)->(W,0),
        2 = S (0,0)->(W,0), 3 = W (0,D)->(0,0).
    Each edge: {"start": (x,y), "dir": (dx,dy) unit, "length": metres}.
    Degenerate (~0) edges are dropped.
    """
    w_m, d_m = bounds
    shape = room.get("shape") if isinstance(room, dict) else None
    if isinstance(shape, list) and len(shape) >= 3:
        pts = []
        for p in shape:
            try:
                pts.append((float(p[0]), float(p[1])))
            except (IndexError, TypeError, ValueError):
                continue
        edges = []
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 0.05:
                continue
            edges.append({
                "start": (x1, y1),
                "dir": (dx / length, dy / length),
                "length": length,
            })
        return edges
    return [
        {"start": (0.0, d_m), "dir": (1.0, 0.0), "length": w_m},
        {"start": (w_m, d_m), "dir": (0.0, -1.0), "length": d_m},
        {"start": (0.0, 0.0), "dir": (1.0, 0.0), "length": w_m},
        {"start": (0.0, d_m), "dir": (0.0, -1.0), "length": d_m},
    ]


class WaypointWalker:
    """Per-device waypoint walker. Each device picks a random target inside
    the room and moves toward it at `speed_mps`. When it reaches the target
    (within tolerance) or a wall blocks the path, it picks a new target.

    If a layout JSON is configured and parses cleanly, inner walls (with
    openings) constrain movement: a step that would cross a solid wall
    stops short of it. Without a layout, the walker just rectangles inside
    the AABB defined by `width_m` × `depth_m`.
    """

    def __init__(self, cfg: Settings, segments: Optional[list[_Segment]] = None):
        self._cfg = cfg
        self._state: dict[str, _State] = {}
        self._rngs: dict[str, random.Random] = {}
        self._segments: list[_Segment] = segments or []
        # The room the walk happens in. Fixes are reported in its frame, and
        # the engine places the room in the venue. None until the blueprint
        # names one.
        self.room_id: Optional[str] = None
        self._room_attempt = 0.0

    def reload_layout(self) -> bool:
        """(Re)load the room, its extent and its walls from the engine
        blueprint (or the mounted file). Returns True once a room is known.
        Idempotent - safe to call repeatedly."""
        data = _load_layout_data(self._cfg)
        if data is None:
            return False
        room = _first_room(data)
        if room is None:
            return False
        segments, bounds = _load_segments_from_data(data)
        self._segments = segments
        if bounds:
            self._cfg.width_m, self._cfg.depth_m = bounds
        self.room_id = str(room["id"])
        return True

    def ensure_room(self) -> Optional[str]:
        """The room id, retrying the blueprint load (throttled) when the engine
        was unreachable at boot. A walk with no room cannot be placed in the
        venue, so the caller reports no fix until one is known."""
        if self.room_id is not None:
            return self.room_id
        now = time.time()
        if now - self._room_attempt >= 10.0:
            self._room_attempt = now
            if self.reload_layout():
                log.info("synthetic-adapter: blueprint room %s loaded late", self.room_id)
        return self.room_id

    @staticmethod
    def _clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    def _rng_for(self, device_id: str) -> random.Random:
        rng = self._rngs.get(device_id)
        if rng is None:
            seed = self._cfg.rng_seed or 0
            mixed = (seed ^ (hash(device_id) & 0xFFFFFFFF)) if seed else None
            rng = random.Random(mixed)
            self._rngs[device_id] = rng
        return rng

    def _new_waypoint(self, rng: random.Random) -> tuple[float, float]:
        # Sample uniformly inside the AABB with a small inset so the device
        # never picks a point right on a wall.
        inset = _ROOM_INSET_M
        x = rng.uniform(inset, max(inset, self._cfg.width_m - inset))
        y = rng.uniform(inset, max(inset, self._cfg.depth_m - inset))
        return x, y

    def _blocked_advance(
        self,
        src: tuple[float, float],
        dst: tuple[float, float],
    ) -> tuple[float, float]:
        """Walk from src to dst, stopping just before any solid wall along
        the path. If no wall blocks, returns dst as-is.
        """
        if not self._segments:
            return dst
        # Find the nearest blocking intersection along the step.
        best_t: Optional[float] = None
        best_seg: Optional[_Segment] = None
        sx, sy = src
        dx, dy = dst
        step_len = math.hypot(dx - sx, dy - sy)
        if step_len < 1e-6:
            return dst
        for seg in self._segments:
            hit = _segments_intersect(src, dst, seg)
            if hit is None:
                continue
            ix, iy, dist_along = hit
            if not _crossing_blocked(dist_along, seg.open_ranges):
                continue  # crossing passes through an opening
            t = math.hypot(ix - sx, iy - sy) / step_len
            if best_t is None or t < best_t:
                best_t = t
                best_seg = seg
        if best_t is None:
            return dst
        # Back off so the device doesn't stick to the wall surface.
        safe_t = max(0.0, best_t - _WALL_MARGIN_M / max(step_len, 1e-6))
        return (sx + (dx - sx) * safe_t, sy + (dy - sy) * safe_t)

    def step(self, device_id: str) -> tuple[float, float, float, float]:
        """Advance the device and return (x, y, z, ts) in the room frame."""
        now = time.time()
        st = self._state.get(device_id)
        rng = self._rng_for(device_id)
        if st is None:
            st = _State(
                x=self._cfg.width_m / 2,
                y=self._cfg.depth_m / 2,
                z=self._cfg.height_m / 2,
                last_ts=now,
            )
            self._state[device_id] = st
            return st.x, st.y, st.z, now

        # Compute dt since last poll; first poll on a returning device may
        # arrive seconds later, but capped so a long gap can't teleport it.
        dt = min(_MAX_DT_S, max(0.0, now - st.last_ts))
        st.last_ts = now
        self._advance_quality(st, rng, dt, now)

        # Just placed: hold the drop point so the first fix a consumer sees is
        # the point the operator chose, not one a second of walking away.
        if now < st.hold_until:
            return st.x, st.y, st.z, now

        # Pick a waypoint if needed.
        if st.waypoint is None:
            st.waypoint = self._new_waypoint(rng)

        wx, wy = st.waypoint
        dx = wx - st.x
        dy = wy - st.y
        dist = math.hypot(dx, dy)
        if dist <= _WAYPOINT_TOLERANCE_M:
            st.waypoint = self._new_waypoint(rng)
            return st.x, st.y, st.z, now

        # Advance toward the waypoint by speed_mps * dt, capped at the
        # remaining distance so we don't overshoot.
        advance = min(dist, self._cfg.speed_mps * dt)
        ux = dx / dist
        uy = dy / dist
        target = (st.x + ux * advance, st.y + uy * advance)
        nx, ny = self._blocked_advance((st.x, st.y), target)
        moved = math.hypot(nx - st.x, ny - st.y)
        st.x = self._clamp(nx, _ROOM_INSET_M, max(_ROOM_INSET_M, self._cfg.width_m - _ROOM_INSET_M))
        st.y = self._clamp(ny, _ROOM_INSET_M, max(_ROOM_INSET_M, self._cfg.depth_m - _ROOM_INSET_M))
        # A wall blocked the advance (we moved less than 80% of the
        # intended step). Drop the waypoint so a new direction is picked.
        if moved < advance * 0.8:
            st.waypoint = None
        return st.x, st.y, st.z, now

    def _advance_quality(self, st: _State, rng: random.Random, dt: float, now: float) -> None:
        """Move fix quality one tick, in episodes rather than per-tick noise.

        Between episodes quality relaxes toward the baseline. With a small
        chance per second it drops into a degraded stretch lasting a few
        seconds, the way a tag passing behind a rack loses its clean paths for
        as long as it is back there. The pull is a fraction of the remaining
        gap per second, so the behaviour does not change if the poll rate does.
        """
        if dt <= 0.0:
            return
        if now >= st.degraded_until and rng.random() < self._cfg.degrade_probability * dt:
            st.degraded_until = now + self._cfg.degrade_seconds
        target = _QUALITY_DEGRADED if now < st.degraded_until else _QUALITY_BASELINE
        pull = min(1.0, _QUALITY_RATE_PER_S * dt)
        q = st.quality + (target - st.quality) * pull
        q += rng.uniform(-_QUALITY_JITTER, _QUALITY_JITTER) * dt
        st.quality = self._clamp(q, 0.0, 1.0)

    def fidelity(self, device_id: str) -> tuple[float, float]:
        """(accuracy in metres, confidence in [0, 1]) for this device's current
        fix quality. Both are synthesised, not measured: this adapter locates
        nothing. Read after `step`, which advances the quality they map from.

        Accuracy rides `(1 - quality)` through a curve above 1, so the value
        sits near the good end of the band and runs toward the bad end only
        during a degraded stretch. Confidence tracks quality directly, which
        keeps the pair coherent: the fixes that read as imprecise are the same
        fixes that read as untrusted.
        """
        cfg = self._cfg
        st = self._state.get(device_id)
        q = st.quality if st is not None else _QUALITY_BASELINE
        lo, hi = cfg.accuracy_min_m, cfg.accuracy_max_m
        accuracy = lo + (hi - lo) * ((1.0 - q) ** _ACCURACY_SKEW)
        confidence = cfg.confidence_min + (cfg.confidence_max - cfg.confidence_min) * q
        return (
            round(self._clamp(accuracy, lo, hi), 2),
            round(self._clamp(confidence, cfg.confidence_min, cfg.confidence_max), 3),
        )

    # --- placement ---------------------------------------------------------
    #
    # Coordinates here are in the room frame, the frame the walker keeps and
    # the blueprint stores: origin at the room's lower-left corner, x along the
    # width, y along the depth.

    def is_active(self, device_id: str) -> bool:
        """Whether this device currently reports a position.

        With `spawn_required` off every configured device walks from boot, as
        it always has. With it on a device reports nothing until placed, which
        is not a failure: it is the same 'no fix' an adapter reports for a
        device it cannot currently locate.
        """
        if not self._cfg.spawn_required:
            return True
        st = self._state.get(device_id)
        return st is not None and st.active

    def place(self, device_id: str, x: float, y: float) -> tuple[float, float]:
        """Put a device at a point and start it walking from there. Returns the
        point it actually landed on.

        The point is clamped into the same inset the walk itself respects, so a
        drop slightly outside the room, or on a wall, lands just inside rather
        than seeding the walk in a place the walk could never reach. Placing an
        already-placed device moves it, which is what dropping it again means.
        """
        inset = _ROOM_INSET_M
        cx = self._clamp(x, inset, max(inset, self._cfg.width_m - inset))
        cy = self._clamp(y, inset, max(inset, self._cfg.depth_m - inset))
        self._state[device_id] = _State(
            x=cx,
            y=cy,
            z=self._cfg.height_m / 2,
            # No waypoint yet: the next step picks one, so the device starts
            # moving from where it was dropped rather than resuming an old leg.
            waypoint=None,
            last_ts=time.time(),
            active=True,
            hold_until=time.time() + _SETTLE_S,
        )
        return cx, cy

    def remove(self, device_id: str) -> bool:
        """Stop a device reporting. Returns whether it was there to remove.

        The state goes with it, so placing it again starts clean rather than
        resuming the walk it had before.
        """
        return self._state.pop(device_id, None) is not None


# Backwards-compatible alias. Anything importing `RandomWalker` (tests,
# main.py) keeps working without churn.
RandomWalker = WaypointWalker


def _load_layout_data(cfg: Settings) -> Optional[dict]:
    """Get the room geometry the demo also renders. The engine is the
    blueprint authority, so prefer GET {POSITIONING_ENGINE_URL}/blueprint -
    this keeps the walker's walls in sync with what the operator drew (the
    mounted seed file goes stale once they edit in the placement editor).
    Falls back to the mounted layout file, then to None (AABB-only)."""
    engine = os.environ.get("POSITIONING_ENGINE_URL", "").rstrip("/")
    if engine:
        try:
            resp = httpx.get(f"{engine}/blueprint", timeout=5.0)
            if resp.status_code == 200:
                log.info("synthetic-adapter: loaded blueprint from engine %s", engine)
                return resp.json()
            log.warning("synthetic-adapter: engine /blueprint -> %s; falling back to file", resp.status_code)
        except Exception as exc:  # network / parse - degrade to the seed file
            log.warning("synthetic-adapter: engine blueprint fetch failed (%s); falling back to file", exc)
    if cfg.layout_path:
        path = Path(cfg.layout_path)
        if path.is_file():
            try:
                return json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                log.warning("synthetic-adapter: cannot read layout %s: %s", path, exc)
        else:
            log.warning("synthetic-adapter: layout path %s not found", path)
    return None


def build_walker(cfg: Settings) -> WaypointWalker:
    """Construct the walker and load its room from the engine blueprint
    (authority) or the mounted layout file. If the engine is not yet reachable
    at boot, the walker starts without a room and retries on the next
    measurements (see ensure_room)."""
    walker = WaypointWalker(cfg)
    if walker.reload_layout():
        log.info(
            "synthetic-adapter: room %s, bounds=%.1fx%.1f",
            walker.room_id, cfg.width_m, cfg.depth_m,
        )
    else:
        log.warning("synthetic-adapter: no blueprint room at boot; will retry on demand")
    return walker
