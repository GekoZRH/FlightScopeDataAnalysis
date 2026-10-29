"""A simple ball flight model, fitted to your own shots, to turn a change of launch angle or spin into metres of carry.

The ball flies in a vertical plane under gravity, drag and the lift of backspin:

    drag coefficient  Cd = cd0 + cd_s * S          S = spin * radius / speed (the spin ratio)
    lift coefficient  Cl = min(cl_a * S, cl_max)

The four numbers are fitted so that the model reproduces the carry and the peak height of the shots you give it. It
is not a physics reference: it describes how *your simulator* turns ball speed, launch angle and spin into carry,
good enough to compare two flights that differ a little. Always look at how well it fits (`rmse`, `r2`) before
believing a difference of a metre or two.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from scipy.optimize import least_squares

MPH = 0.44704                       # m/s per mph
RHO, RADIUS, MASS, GRAVITY = 1.2, 0.02135, 0.04593, 9.81
AREA = np.pi * RADIUS ** 2
STEP_S, STEPS = 0.04, 250           # integration step and number of steps: 10 s of flight is more than any drive (a finer step gives the same differences)
MIN_SHOTS = 40


def simulate(ball_ms, launch_deg, spin_rpm, params: Tuple[float, float, float, float]):
    """Carry (m), peak height (m) and flight time (s) of shots, for arrays of equal length. Euler steps in a vertical plane."""
    cd0, cd_s, cl_a, cl_max = params
    ball_ms, launch_deg, spin_rpm = (np.atleast_1d(np.asarray(a, dtype=float)) for a in (ball_ms, launch_deg, spin_rpm))
    n = len(ball_ms)
    angle = np.radians(launch_deg)
    vx, vy = ball_ms * np.cos(angle), ball_ms * np.sin(angle)
    x, y = np.zeros(n), np.zeros(n)
    omega = spin_rpm * 2.0 * np.pi / 60.0
    carry, flight = np.full(n, np.nan), np.full(n, np.nan)
    apex = np.zeros(n)
    flying = np.ones(n, dtype=bool)
    q = 0.5 * RHO * AREA / MASS
    for k in range(STEPS):
        v = np.hypot(vx, vy)
        s = omega * RADIUS / np.maximum(v, 1e-6)
        cd = cd0 + cd_s * s
        cl = np.minimum(cl_a * s, cl_max)
        vx_new = vx + (-q * cd * v * vx - q * cl * v * vy) * STEP_S
        vy_new = vy + (-GRAVITY - q * cd * v * vy + q * cl * v * vx) * STEP_S
        x_new, y_new = x + vx * STEP_S, y + vy * STEP_S
        landing = flying & (y_new < 0) & (k > 3)
        fraction = np.where(landing, y / np.maximum(y - y_new, 1e-9), 0.0)
        carry = np.where(landing, x + fraction * (x_new - x), carry)
        flight = np.where(landing, (k + fraction) * STEP_S, flight)
        flying &= ~landing
        apex = np.maximum(apex, np.where(flying, y_new, apex))
        vx, vy, x, y = vx_new, vy_new, x_new, y_new
        if not flying.any():
            break
    return carry, apex, flight


@dataclass(frozen=True)
class FlightModel:
    params: Tuple[float, float, float, float]
    n: int
    rmse: float             # m: how far the model carry is from the measured carry, on the shots it was fitted to
    r2: float               # share of the carry differences between shots that the model reproduces
    carry_sd: float         # m: the spread of the measured carries, to compare the rmse with

    def carry(self, ball_mph, launch_deg, spin_rpm) -> np.ndarray:
        """Model carry (m) for shots given as ball speed (mph), launch angle (deg) and backspin (rpm)."""
        return simulate(np.asarray(ball_mph, dtype=float) * MPH, launch_deg, spin_rpm, self.params)[0]


def fit_flight_model(ball_mph, launch_deg, spin_rpm, carry_m, apex_m=None) -> Optional[FlightModel]:
    """Fit the four numbers to measured shots. Returns None with too few shots or when the fit fails."""
    ball, launch, spin, carry = (np.asarray(a, dtype=float) for a in (ball_mph, launch_deg, spin_rpm, carry_m))
    apex = None if apex_m is None else np.asarray(apex_m, dtype=float)
    keep = np.isfinite(ball) & np.isfinite(launch) & np.isfinite(spin) & np.isfinite(carry)
    if apex is not None:
        keep &= np.isfinite(apex)
    if keep.sum() < MIN_SHOTS:
        return None
    ball, launch, spin, carry = ball[keep] * MPH, launch[keep], spin[keep], carry[keep]
    apex = None if apex is None else apex[keep]

    def residual(p):
        c, a, _ = simulate(ball, launch, spin, p)
        parts = [np.nan_to_num((c - carry) / 3.0, nan=50.0)]
        if apex is not None:
            parts.append((a - apex) / 2.0)
        return np.concatenate(parts)

    try:
        fit = least_squares(residual, x0=[0.22, 0.1, 1.0, 0.35], bounds=([0.1, -1.0, 0.3, 0.1], [0.5, 2.0, 4.0, 0.6]), ftol=1e-4, xtol=1e-4, gtol=1e-4)
    except (ValueError, FloatingPointError):
        return None
    model_carry = simulate(ball, launch, spin, fit.x)[0]
    ok = np.isfinite(model_carry)
    if ok.sum() < MIN_SHOTS:
        return None
    error = model_carry[ok] - carry[ok]
    r2 = 1.0 - float((error ** 2).sum() / ((carry[ok] - carry[ok].mean()) ** 2).sum())
    return FlightModel(tuple(float(v) for v in fit.x), int(ok.sum()), float(np.sqrt(np.mean(error ** 2))), r2, float(carry[ok].std(ddof=1)))
