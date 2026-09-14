"""Kalman smoothing for 2D position estimates, in two motion models.

The x and y axes are independent under diagonal process/measurement noise, so
each model runs two 1D filters. These are linear KFs - adequate when the
measurement is an already-computed position. An EKF/UKF would only be warranted
to fuse raw nonlinear measurements (RSSI ranges, ToA) directly. Pure Python, no
numpy.

  - `random-walk` (constant position, state [pos]). The prediction does not
    move the estimate, it only widens the uncertainty. Measurement noise
    therefore cannot become momentum, and a stationary device stays put.
  - `constant-velocity` (state [pos, vel]). The prediction extrapolates along
    the estimated velocity, which tracks genuine motion between measurements
    and, on a noisy source, converts a single bad fix into a drift that
    outlives it. Neither `process_noise` setting removes that: raising it
    trades the drift for jitter, lowering it makes the velocity estimate
    stiffer and the drift longer-lived.

Both reach the same steady-state responsiveness for a given `process_noise`
and measurement variance, so switching models does not trade latency. What
changes is whether the filter extrapolates.
"""


class Kalman1D:
    def __init__(self, process_var: float, init_var: float = 10.0):
        self.q = process_var
        self.x = 0.0
        self.v = 0.0
        self.P = [[init_var, 0.0], [0.0, init_var]]
        self._init = False

    def update(self, z: float, dt: float, r: float) -> float:
        if not self._init:
            self.x, self.v, self._init = z, 0.0, True
            return self.x

        dt = max(dt, 1e-3)
        # --- predict: F = [[1, dt], [0, 1]] ---
        self.x += dt * self.v
        P = self.P
        p00 = P[0][0] + dt * (P[1][0] + P[0][1]) + dt * dt * P[1][1]
        p01 = P[0][1] + dt * P[1][1]
        p10 = P[1][0] + dt * P[1][1]
        p11 = P[1][1]
        p00 += 0.25 * dt**4 * self.q
        p01 += 0.5 * dt**3 * self.q
        p10 += 0.5 * dt**3 * self.q
        p11 += dt**2 * self.q

        # --- update: H = [1, 0], measurement variance r ---
        s = p00 + r
        k0 = p00 / s
        k1 = p10 / s
        y = z - self.x
        self.x += k0 * y
        self.v += k1 * y
        self.P = [
            [(1 - k0) * p00, (1 - k0) * p01],
            [p10 - k1 * p00, p11 - k1 * p01],
        ]
        return self.x


class Tracker2D:
    def __init__(self, process_var: float = 0.5):
        self.kx = Kalman1D(process_var)
        self.ky = Kalman1D(process_var)

    def update(self, x: float, y: float, dt: float, r: float) -> tuple[float, float]:
        return self.kx.update(x, dt, r), self.ky.update(y, dt, r)


class RandomWalk1D:
    """Constant-position Kalman filter (state [pos]).

    Predict widens the uncertainty and leaves the estimate where it was, so
    there is no velocity state for measurement noise to load and nothing to
    carry the estimate away from a device that is not moving.
    """

    def __init__(self, process_var: float, init_var: float = 10.0):
        self.q = process_var
        self.x = 0.0
        self.P = init_var
        self._init = False

    def update(self, z: float, dt: float, r: float) -> float:
        if not self._init:
            self.x, self._init = z, True
            return self.x

        dt = max(dt, 1e-3)
        p = self.P + self.q * dt          # predict: uncertainty only
        k = p / (p + r)                   # update
        self.x += k * (z - self.x)
        self.P = (1 - k) * p
        return self.x


class RandomWalkTracker2D:
    def __init__(self, process_var: float = 0.5):
        self.kx = RandomWalk1D(process_var)
        self.ky = RandomWalk1D(process_var)

    def update(self, x: float, y: float, dt: float, r: float) -> tuple[float, float]:
        return self.kx.update(x, dt, r), self.ky.update(y, dt, r)


# The motion models this binary implements, and the tracker each one builds.
# Served on GET /contract so a deploy dashboard offers the set the image
# actually has rather than a free-text field, and enforced on PUT /bindings.
MOTION_MODELS = {
    "random-walk": RandomWalkTracker2D,
    "constant-velocity": Tracker2D,
}
DEFAULT_MOTION_MODEL = "random-walk"


def tracker_for(motion_model: str, process_var: float):
    """Build the tracker for a motion model. An unknown name falls back to the
    default rather than raising: the write path already refuses one, so a
    config that reaches here with a bad value came from an older file."""
    factory = MOTION_MODELS.get(motion_model, MOTION_MODELS[DEFAULT_MOTION_MODEL])
    return factory(process_var)
