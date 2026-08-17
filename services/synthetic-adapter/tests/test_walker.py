import time

from app.config import Settings
from app.walker import (
    WaypointWalker,
    _crossing_blocked,
    _Segment,
    _segments_intersect,
)


def test_walker_clamps_to_bounds():
    cfg = Settings(width_m=10.0, depth_m=10.0, height_m=3.0, speed_mps=100.0, rng_seed=1)
    walker = WaypointWalker(cfg)
    for _ in range(200):
        x, y, z, _ = walker.step("dev1")
        assert 0.0 <= x <= 10.0
        assert 0.0 <= y <= 3.0
        assert 0.0 <= z <= 10.0


def test_walker_seeds_each_device_at_centre():
    cfg = Settings(width_m=10.0, depth_m=20.0, height_m=2.0, speed_mps=0.0)
    walker = WaypointWalker(cfg)
    x, y, z, _ = walker.step("d1")
    assert (x, y, z) == (5.0, 1.0, 10.0)


def test_walker_devices_independent():
    cfg = Settings(width_m=10.0, depth_m=10.0, height_m=3.0, speed_mps=2.0, rng_seed=1)
    walker = WaypointWalker(cfg)
    for _ in range(10):
        walker.step("d1")
        time.sleep(0.01)
    for _ in range(3):
        walker.step("d2")
        time.sleep(0.01)
    assert walker._state["d1"] != walker._state["d2"]


def test_walker_moves_toward_waypoint():
    cfg = Settings(width_m=10.0, depth_m=10.0, height_m=3.0, speed_mps=2.0, rng_seed=42)
    walker = WaypointWalker(cfg)
    walker.step("d1")  # seed at centre, returns (5, 1.5, 5)
    # Force a known waypoint so the test isn't RNG-dependent.
    walker._state["d1"].waypoint = (8.0, 5.0)
    walker._state["d1"].last_ts -= 0.5  # pretend half a second passed
    _, _, _, _ = walker.step("d1")
    st = walker._state["d1"]
    # Moved toward the waypoint but not past it (capped by speed * dt).
    assert st.x > 5.0
    assert st.x <= 8.0


def test_wall_blocks_step_without_opening():
    # Wall vertical at x=5 from y=0 to y=10.
    wall = _Segment(x1=5.0, y1=0.0, x2=5.0, y2=10.0, thickness=0.2)
    cfg = Settings(width_m=10.0, depth_m=10.0, height_m=3.0, speed_mps=100.0, rng_seed=1)
    walker = WaypointWalker(cfg, segments=[wall])
    walker.step("d1")  # seed at centre (5, 1.5, 5) - on the wall; OK for the test
    walker._state["d1"].x = 2.0
    walker._state["d1"].z = 5.0
    walker._state["d1"].waypoint = (8.0, 5.0)
    walker._state["d1"].last_ts -= 1.0
    walker.step("d1")
    # Wall sits at x=5; the device should stop short of it.
    assert walker._state["d1"].x < 5.0


def test_opening_lets_step_through():
    wall = _Segment(x1=5.0, y1=0.0, x2=5.0, y2=10.0, thickness=0.2)
    # Opening from y=4 to y=6 - a 2 m doorway centred on the path.
    wall.open_ranges = [(4.0, 6.0)]
    cfg = Settings(width_m=10.0, depth_m=10.0, height_m=3.0, speed_mps=100.0, rng_seed=1)
    walker = WaypointWalker(cfg, segments=[wall])
    walker.step("d1")
    walker._state["d1"].x = 2.0
    walker._state["d1"].z = 5.0
    walker._state["d1"].waypoint = (8.0, 5.0)
    walker._state["d1"].last_ts -= 1.0
    walker.step("d1")
    # Path went through the opening; device made it past the wall.
    assert walker._state["d1"].x > 5.0


def test_segments_intersect_basic():
    seg = _Segment(x1=0.0, y1=0.0, x2=10.0, y2=0.0, thickness=0.1)
    hit = _segments_intersect((5.0, -1.0), (5.0, 1.0), seg)
    assert hit is not None
    ix, iy, dist = hit
    assert abs(ix - 5.0) < 1e-6
    assert abs(iy - 0.0) < 1e-6
    assert abs(dist - 5.0) < 1e-6


def test_crossing_blocked_respects_ranges():
    assert _crossing_blocked(5.0, []) is True
    assert _crossing_blocked(5.0, [(4.0, 6.0)]) is False
    assert _crossing_blocked(3.0, [(4.0, 6.0)]) is True
