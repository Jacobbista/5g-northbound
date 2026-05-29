"""Constant-velocity Kalman filter for smoothing 2D position estimates.

The x and y axes are independent under a constant-velocity model with diagonal
process/measurement noise, so we run two 1D filters (state [pos, vel]). This is
a linear KF — adequate when the measurement is an already-computed position. An
EKF/UKF would only be warranted to fuse raw nonlinear measurements (RSSI ranges,
ToA) directly. Pure Python, no numpy.
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
