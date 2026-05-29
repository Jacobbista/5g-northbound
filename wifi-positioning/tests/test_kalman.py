import random

from app.kalman import Tracker2D


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
