import json
import logging
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import Settings

log = logging.getLogger(__name__)

# A device is "at" its waypoint when within this distance; the walker then
# picks a new one. Small enough that the device doesn't visibly stop, large
# enough that float jitter never holds it back from advancing.
_WAYPOINT_TOLERANCE_M = 0.4
# When a step would cross a wall, back off by this margin so the device
# never lands flush against the wall (avoids re-collision next step).
_WALL_MARGIN_M = 0.15
# Cap dt between polls so a long pause doesn't teleport the device. The
# adapter typically polls at 1 Hz; if a poll is missed for minutes the
# device should still only advance a few seconds' worth of distance.
_MAX_DT_S = 2.0


@dataclass
class _Segment:
    """Wall segment in floor-plan-local metres. Stores derived geometry
    once so per-step intersection checks stay cheap."""

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
    x: float
    y: float
    z: float
    waypoint: Optional[tuple[float, float]] = None
    last_ts: float = 0.0


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


def _load_segments_from_layout(path: Path) -> tuple[list[_Segment], Optional[tuple[float, float]]]:
    """Parse the placement-editor layout JSON and pull inner walls + the
    room footprint for the first room. Returns (segments, (w_m, d_m)).
    A missing / unparseable layout returns ([], None) so the walker falls
    back to the configured AABB without crashing the service.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        log.warning("mock-positioning: cannot read layout %s: %s", path, exc)
        return [], None
    rooms = data.get("rooms") or []
    room = rooms[0] if rooms else None
    if room is None:
        # Legacy v1: room dimensions at the top level, walls under "walls".
        w = float(data.get("room_w", 0) or 0)
        d = float(data.get("room_h", 0) or 0)
        wall_data = data.get("walls") or []
        bounds = (w, d) if w > 0 and d > 0 else None
    else:
        w = float(room.get("width_m", 0) or 0)
        d = float(room.get("height_m", 0) or 0)
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

    # Perimeter walls - derived from the room's polygon shape when present
    # (`room.shape: [[x, y], ...]`), otherwise from the four cardinal sides
    # of the bbox. Each edge becomes a wall segment whose openings are the
    # entries in `perimeter_openings` matching its edge_index. Legacy
    # `side` fields are lifted to indices using the rectangle convention.
    if room is not None and bounds is not None:
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
    """Compute room perimeter edges in floor-local metres.

    Polygon-shaped rooms (`shape: [[x, y], ...]`) yield one edge per vertex
    pair. Rectangle rooms fall back to the four cardinal edges with the
    convention shared with the placement-editor:
        0 = N (0,0)→(W,0), 1 = E (W,0)→(W,H),
        2 = S (0,H)→(W,H), 3 = W (0,0)→(0,H).
    Each edge: {"start": (x,y), "dir": (dx,dy) unit, "length": metres}.
    Degenerate (~0) edges are dropped.
    """
    w_m, d_m = bounds
    shape = room.get("shape") if isinstance(room, dict) else None
    if isinstance(shape, list) and len(shape) >= 3:
        base_x = float(room.get("x_m") or 0)
        base_y = float(room.get("y_m") or 0)
        pts = []
        for p in shape:
            try:
                pts.append((float(p[0]) - base_x, float(p[1]) - base_y))
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
        {"start": (0.0, 0.0), "dir": (1.0, 0.0), "length": w_m},
        {"start": (w_m, 0.0), "dir": (0.0, 1.0), "length": d_m},
        {"start": (0.0, d_m), "dir": (1.0, 0.0), "length": w_m},
        {"start": (0.0, 0.0), "dir": (0.0, 1.0), "length": d_m},
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
        inset = 0.5
        x = rng.uniform(inset, max(inset, self._cfg.width_m - inset))
        z = rng.uniform(inset, max(inset, self._cfg.depth_m - inset))
        return x, z

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
        sx, sz = src
        dx, dz = dst
        step_len = math.hypot(dx - sx, dz - sz)
        if step_len < 1e-6:
            return dst
        for seg in self._segments:
            hit = _segments_intersect(src, dst, seg)
            if hit is None:
                continue
            ix, iz, dist_along = hit
            if not _crossing_blocked(dist_along, seg.open_ranges):
                continue  # crossing passes through an opening
            t = math.hypot(ix - sx, iz - sz) / step_len
            if best_t is None or t < best_t:
                best_t = t
                best_seg = seg
        if best_t is None:
            return dst
        # Back off so the device doesn't stick to the wall surface.
        safe_t = max(0.0, best_t - _WALL_MARGIN_M / max(step_len, 1e-6))
        return (sx + (dx - sx) * safe_t, sz + (dz - sz) * safe_t)

    def step(self, device_id: str) -> tuple[float, float, float, float]:
        now = time.time()
        st = self._state.get(device_id)
        rng = self._rng_for(device_id)
        if st is None:
            st = _State(
                x=self._cfg.width_m / 2,
                y=self._cfg.height_m / 2,
                z=self._cfg.depth_m / 2,
                last_ts=now,
            )
            self._state[device_id] = st
            return st.x, st.y, st.z, now

        # Compute dt since last poll; first poll on a returning device may
        # arrive seconds later, but capped so a long gap can't teleport it.
        dt = min(_MAX_DT_S, max(0.0, now - st.last_ts))
        st.last_ts = now

        # Pick a waypoint if needed.
        if st.waypoint is None:
            st.waypoint = self._new_waypoint(rng)

        wx, wz = st.waypoint
        dx = wx - st.x
        dz = wz - st.z
        dist = math.hypot(dx, dz)
        if dist <= _WAYPOINT_TOLERANCE_M:
            st.waypoint = self._new_waypoint(rng)
            return st.x, st.y, st.z, now

        # Advance toward the waypoint by speed_mps * dt, capped at the
        # remaining distance so we don't overshoot.
        advance = min(dist, self._cfg.speed_mps * dt)
        ux = dx / dist
        uz = dz / dist
        target = (st.x + ux * advance, st.z + uz * advance)
        nx, nz = self._blocked_advance((st.x, st.z), target)
        moved = math.hypot(nx - st.x, nz - st.z)
        st.x = self._clamp(nx, 0.0, self._cfg.width_m)
        st.z = self._clamp(nz, 0.0, self._cfg.depth_m)
        # A wall blocked the advance (we moved less than 80% of the
        # intended step). Drop the waypoint so a new direction is picked.
        if moved < advance * 0.8:
            st.waypoint = None
        return st.x, st.y, st.z, now


# Backwards-compatible alias. Anything importing `RandomWalker` (tests,
# main.py) keeps working without churn.
RandomWalker = WaypointWalker


def build_walker(cfg: Settings) -> WaypointWalker:
    """Construct the walker, loading wall geometry from the configured
    layout path when available. Bounds in the layout override the env
    defaults so the mock matches the room the user actually drew."""
    segments: list[_Segment] = []
    if cfg.layout_path:
        path = Path(cfg.layout_path)
        if path.is_file():
            segments, bounds = _load_segments_from_layout(path)
            if bounds:
                # Patch the AABB so waypoints are sampled inside the
                # operator's actual room, not whatever defaults config had.
                w, d = bounds
                cfg.width_m = w
                cfg.depth_m = d
                log.info(
                    "mock-positioning: loaded layout %s - bounds=%.1fx%.1f, %d walls",
                    path,
                    w,
                    d,
                    len(segments),
                )
        else:
            log.warning("mock-positioning: layout path %s not found", path)
    return WaypointWalker(cfg, segments=segments)
