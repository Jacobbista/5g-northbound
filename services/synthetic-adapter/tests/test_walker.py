import time

from app.config import Settings
from app.walker import (
    WaypointWalker,
    _crossing_blocked,
    _Segment,
    _segments_intersect,
    _State,
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


def _fidelity_series(cfg, device="d1", ticks=600, dt=1.0):
    """Drive one device's quality over simulated time and collect what it would
    report. Steps the model directly with an explicit dt so the series does not
    depend on the wall clock or on how fast the test machine runs."""
    w = WaypointWalker(cfg)
    w._state[device] = _State(x=1.0, y=1.0, z=1.0, last_ts=0.0)
    rng = w._rng_for(device)
    out = []
    for i in range(ticks):
        w._advance_quality(w._state[device], rng, dt, i * dt)
        out.append(w.fidelity(device))
    return out


def test_fidelity_stays_inside_the_declared_band():
    # A draw outside the band would contradict the adapter's own accuracy_class
    # declaration, which is the whole point of declaring one.
    cfg = Settings(width_m=10.0, depth_m=10.0, height_m=3.0, rng_seed=1)
    for accuracy, confidence in _fidelity_series(cfg):
        assert cfg.accuracy_min_m <= accuracy <= cfg.accuracy_max_m
        assert cfg.confidence_min <= confidence <= cfg.confidence_max


def test_fidelity_is_reproducible_under_a_seed():
    # `rng_seed` already promises reproducible trajectories. The synthesised
    # fidelity draws from the same per-device RNG, so it keeps that promise.
    cfg = lambda: Settings(width_m=10.0, depth_m=10.0, height_m=3.0, rng_seed=7)
    assert _fidelity_series(cfg()) == _fidelity_series(cfg())


def test_accuracy_and_confidence_move_together():
    # One latent quality drives both, so a worse radius always comes with less
    # confidence. Independent draws would emit pairs no real source produces,
    # and the fusion weight is confidence over accuracy, so the pair is what
    # actually matters.
    cfg = Settings(width_m=10.0, depth_m=10.0, height_m=3.0, rng_seed=3)
    samples = _fidelity_series(cfg)
    worst = max(samples, key=lambda s: s[0])
    best = min(samples, key=lambda s: s[0])
    assert worst[1] < best[1]


def test_accuracy_is_skewed_toward_the_good_end():
    # Indoor error is not symmetric: an obstructed path lengthens the measured
    # distance and never shortens it. Most fixes sit near the good end of the
    # band with a thin tail toward the bad one, so the median lands well below
    # the midpoint, which a symmetric draw would not do.
    cfg = Settings(width_m=10.0, depth_m=10.0, height_m=3.0, rng_seed=11)
    samples = sorted(s[0] for s in _fidelity_series(cfg))
    median = samples[len(samples) // 2]
    assert median < (cfg.accuracy_min_m + cfg.accuracy_max_m) / 2
    # The tail is real, not a flat line: degraded stretches do occur.
    assert samples[-1] > median


def test_quality_degrades_in_episodes_not_per_tick():
    # Indoor degradation lasts seconds. A stretch that dips must stay dipped
    # for several consecutive ticks rather than flicker back immediately.
    cfg = Settings(width_m=10.0, depth_m=10.0, height_m=3.0, rng_seed=5)
    series = [a for a, _ in _fidelity_series(cfg, ticks=800)]
    threshold = (cfg.accuracy_min_m + cfg.accuracy_max_m) / 2
    longest = run = 0
    for a in series:
        run = run + 1 if a > threshold else 0
        longest = max(longest, run)
    assert longest >= 3, "degradation is flickering per tick, not lasting"
