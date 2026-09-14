import random

from app.kalman import (
    DEFAULT_MOTION_MODEL,
    MOTION_MODELS,
    RandomWalkTracker2D,
    Tracker2D,
    tracker_for,
)


def test_kalman_reduces_noise_on_static_target():
    random.seed(0)
    tr = Tracker2D(process_var=0.1)
    truth = (5.0, 5.0)
    raw_err = filt_err = 0.0
    for _ in range(50):
        zx = truth[0] + random.gauss(0, 1.0)
        zy = truth[1] + random.gauss(0, 1.0)
        x, y = tr.update(zx, zy, dt=0.1, r=1.0)
        raw_err += (zx - truth[0]) ** 2 + (zy - truth[1]) ** 2
        filt_err += (x - truth[0]) ** 2 + (y - truth[1]) ** 2
    assert filt_err < raw_err * 0.5


def test_random_walk_does_not_drift_after_a_bad_fix():
    """The failure the model exists for: one outlier, then truthful
    measurements. Constant-velocity loads the outlier into its velocity state
    and keeps moving; random-walk has no velocity to load."""
    truth = 5.0
    cv = Tracker2D(process_var=1.0)
    rw = RandomWalkTracker2D(process_var=1.0)
    for tr in (cv, rw):
        tr.update(truth, truth, dt=1.0, r=1.0)
        tr.update(truth, truth, dt=1.0, r=1.0)
        tr.update(truth + 8.0, truth, dt=1.0, r=1.0)   # the bad fix
    cv_x = rw_x = None
    for _ in range(4):                                  # truth again, four times
        cv_x, _ = cv.update(truth, truth, dt=1.0, r=1.0)
        rw_x, _ = rw.update(truth, truth, dt=1.0, r=1.0)
    # Constant-velocity is still travelling away from a target that has been
    # reporting the truth for four cycles; random-walk has returned to it.
    assert abs(rw_x - truth) < abs(cv_x - truth)
    assert abs(rw_x - truth) < 0.5


def test_random_walk_smooths_a_static_target():
    random.seed(0)
    tr = RandomWalkTracker2D(process_var=0.1)
    truth = (5.0, 5.0)
    raw_err = filt_err = 0.0
    for _ in range(50):
        zx = truth[0] + random.gauss(0, 1.0)
        zy = truth[1] + random.gauss(0, 1.0)
        x, y = tr.update(zx, zy, dt=0.1, r=1.0)
        raw_err += (zx - truth[0]) ** 2 + (zy - truth[1]) ** 2
        filt_err += (x - truth[0]) ** 2 + (y - truth[1]) ** 2
    assert filt_err < raw_err * 0.5


def test_random_walk_keeps_up_with_a_moving_target():
    """The cost of the swap, pinned. Constant-velocity has no steady-state lag
    against a target moving at a constant velocity: that is the motion it
    extrapolates, by construction. Random-walk trails, by about 0.6 m at 1 m/s
    with `process_noise` 1.0, and by more as that value falls. Bounded here at
    a metre so a change that makes the trailing worse fails."""
    cv = Tracker2D(process_var=1.0)
    rw = RandomWalkTracker2D(process_var=1.0)
    cv_err = rw_err = 0.0
    for i in range(30):
        truth = 1.0 * i
        cx, _ = cv.update(truth, 0.0, dt=1.0, r=1.0)
        rx, _ = rw.update(truth, 0.0, dt=1.0, r=1.0)
        if i >= 10:                                     # after both settle
            cv_err += abs(cx - truth)
            rw_err += abs(rx - truth)
    assert (rw_err - cv_err) / 20 < 1.0


def test_tracker_for_builds_each_published_model():
    for name, factory in MOTION_MODELS.items():
        assert isinstance(tracker_for(name, 0.5), factory)
    # An unknown name is refused at the write path, so here it falls back
    # rather than raising on a config written by an older version.
    assert isinstance(
        tracker_for("no-such-model", 0.5), MOTION_MODELS[DEFAULT_MOTION_MODEL]
    )
