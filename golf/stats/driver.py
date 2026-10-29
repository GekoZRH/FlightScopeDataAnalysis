"""How much carry a driver could gain by hitting the optimal launch angle and spin for its ball speed and angle of attack.

For every driver shot the optimal launch angle and spin rate are read from the chart (`targets.OptimalChart`: ball speed
and angle of attack in, optimal launch and spin out). The gap to what you did is the *launch gap* and *spin gap*. To say
what a gap is worth in metres, a ball flight model is fitted to your own driver shots (`flightmodel`) and the carry of
each shot is calculated again with the chart's launch angle, the chart's spin, or both: the difference is the gain. Only
differences of the model are used, so a constant error of the model drops out.

Read the numbers with these limits in mind:
- The chart is a general optimum (for total distance); your simulator and your driver may differ a little from it.
- The model reproduces your carries to about 3 m (see `model`); the gain in metres is an estimate, and a small gain
  (about a metre) is within what the model can tell.
- The attack angle rows ask what the optimum would be with a different attack angle: they assume you could then
  also deliver the chart's launch angle and spin for it.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats

from golf.stats.flightmodel import FlightModel, fit_flight_model
from golf.targets import OptimalChart

MIN_SHOTS = 30
MIN_SESSIONS = 3
WINDOW_LAUNCH_DEG = 1.0           # a shot is "close to the chart" within this launch angle ...
WINDOW_SPIN_RPM = 250.0           # ... and this spin rate
AOA_STEPS = (1.0, 2.0, 3.0)       # attack angle changes asked about
MAP_STEP = (0.5, 100.0)           # the carry map: launch angle step (deg) and spin step (rpm)
MAP_MARGIN = (1.5, 300.0)         # the map reaches this far beyond your shots and the chart value: the model is only reliable where there are shots
MAX_POINTS = 600

NEEDED = ["carry_m", "ball_speed_mph", "launch_v_deg", "spin_rpm", "spin_axis_deg", "aoa_deg", "height_m", "session_date"]


def _mean_interval(values: np.ndarray, sessions: np.ndarray, level: float) -> Dict[str, Optional[float]]:
    """Mean of shot values with an interval that allows for shots of a session being alike (leave one session out, t on sessions - 1)."""
    ok = np.isfinite(values)
    values, sessions = values[ok], sessions[ok]
    if len(values) == 0:
        return {"mean": None, "lo": None, "hi": None}
    mean = float(values.mean())
    unique = list(dict.fromkeys(sessions))
    if len(unique) < MIN_SESSIONS:
        return {"mean": mean, "lo": None, "hi": None}
    left_out = np.array([values[sessions != s].mean() for s in unique])
    g = len(unique)
    se = float(np.sqrt(((g - 1) / g) * ((left_out - left_out.mean()) ** 2).sum()))
    half = float(stats.t.ppf(0.5 + level / 2.0, g - 1)) * se
    return {"mean": mean, "lo": mean - half, "hi": mean + half}


def _scenario(name: str, launch: float, spin: float, carry: float, now: float, reference: Optional[float] = None, kind: str = "") -> Dict:
    return {"name": name, "kind": kind, "launch": launch, "spin": spin, "carry": carry, "gain": carry - now,
            "gain_over_chart": None if reference is None else carry - reference}


def analyse_driver(shots: pd.DataFrame, chart: OptimalChart, *, level: float = 0.95, model: Optional[FlightModel] = None) -> Optional[Dict]:
    """The analysis of the driver shots given (see the module description), or None if the data does not allow it.

    `model` may be passed to reuse a flight model already fitted to exactly these shots.
    """
    if any(column not in shots.columns for column in NEEDED):
        return None
    data = shots.dropna(subset=NEEDED).reset_index(drop=True)
    sessions = data["session_date"].astype(str).to_numpy()
    if len(data) < MIN_SHOTS or len(set(sessions)) < MIN_SESSIONS:
        return None

    ball, launch, spin = (data[c].to_numpy(float) for c in ("ball_speed_mph", "launch_v_deg", "spin_rpm"))
    aoa, carry, apex = (data[c].to_numpy(float) for c in ("aoa_deg", "carry_m", "height_m"))
    back = np.cos(np.radians(data["spin_axis_deg"].to_numpy(float)))          # the part of the spin that lifts the ball
    if model is None:
        model = fit_flight_model(ball, launch, spin * back, carry, apex)
    if model is None:
        return None

    opt_launch, opt_spin = chart.lookup(ball, aoa)
    now = model.carry(ball, launch, spin * back)
    gain_launch = model.carry(ball, opt_launch, spin * back) - now
    gain_spin = model.carry(ball, launch, opt_spin * back) - now
    gain_both = model.carry(ball, opt_launch, opt_spin * back) - now
    gap_launch, gap_spin = launch - opt_launch, spin - opt_spin
    close = (np.abs(gap_launch) <= WINDOW_LAUNCH_DEG) & (np.abs(gap_spin) <= WINDOW_SPIN_RPM)

    # a typical shot: the averages of the shots
    b0, a0, l0, s0, k0 = float(ball.mean()), float(aoa.mean()), float(launch.mean()), float(spin.mean()), float(back.mean())
    ol, os_ = (float(v[0]) for v in chart.lookup(b0, a0))
    carry_at = lambda b, l, s: float(model.carry([b], [l], [s * k0])[0])
    now0 = carry_at(b0, l0, s0)
    both0 = carry_at(b0, ol, os_)
    scenarios = [
        _scenario("Your driver now", l0, s0, now0, now0, kind="now"),
        _scenario("Launch angle at the chart value", ol, s0, carry_at(b0, ol, s0), now0, kind="launch"),
        _scenario("Spin at the chart value", l0, os_, carry_at(b0, l0, os_), now0, kind="spin"),
        _scenario("Launch angle and spin at the chart values", ol, os_, both0, now0, kind="both"),
    ]
    for step in AOA_STEPS:
        al, as_ = (float(v[0]) for v in chart.lookup(b0, a0 + step))
        scenarios.append(_scenario(f"Attack angle {step:+.0f} deg, launch and spin at the chart values for it", al, as_, carry_at(b0, al, as_), now0, both0, kind="aoa"))
    scenarios.append(_scenario("Ball speed +1 mph, launch and spin as now", l0, s0, carry_at(b0 + 1.0, l0, s0), now0, kind="speed"))

    rows = []
    for session in sorted(set(sessions)):
        pick = sessions == session
        rows.append({"session": session, "shots": int(pick.sum()), "launch_gap": float(gap_launch[pick].mean()), "spin_gap": float(gap_spin[pick].mean()),
                     "gain": float(np.nanmean(gain_both[pick])), "close": float(100.0 * close[pick].mean())})

    launch_edges = (min(np.quantile(launch, 0.01), ol, l0) - MAP_MARGIN[0], max(np.quantile(launch, 0.99), ol, l0) + MAP_MARGIN[0])
    spin_edges = (min(np.quantile(spin, 0.01), os_, s0) - MAP_MARGIN[1], max(np.quantile(spin, 0.99), os_, s0) + MAP_MARGIN[1])
    launch_axis = np.arange(np.floor(launch_edges[0] / MAP_STEP[0]) * MAP_STEP[0], launch_edges[1] + 1e-9, MAP_STEP[0])
    spin_axis = np.arange(np.floor(spin_edges[0] / MAP_STEP[1]) * MAP_STEP[1], spin_edges[1] + 1e-9, MAP_STEP[1])
    grid_l, grid_s = np.meshgrid(launch_axis, spin_axis)
    surface = model.carry(np.full(grid_l.size, b0), grid_l.ravel(), grid_s.ravel() * k0).reshape(grid_l.shape)

    step = max(1, len(data) // MAX_POINTS)
    return {
        "n": int(len(data)), "sessions": int(len(set(sessions))),
        "model": {"n": model.n, "rmse": model.rmse, "r2": model.r2, "carry_sd": model.carry_sd},
        "typical": {"ball_mph": b0, "aoa_deg": a0, "launch": l0, "spin": s0, "opt_launch": ol, "opt_spin": os_},
        "gaps": {"launch": _mean_interval(gap_launch, sessions, level), "spin": _mean_interval(gap_spin, sessions, level)},
        "gains": {"launch": _mean_interval(gain_launch, sessions, level), "spin": _mean_interval(gain_spin, sessions, level),
                  "both": _mean_interval(gain_both, sessions, level)},
        "close": float(100.0 * close.mean()), "window": {"launch": WINDOW_LAUNCH_DEG, "spin": WINDOW_SPIN_RPM},
        "scenarios": scenarios, "session_rows": rows,
        "points": [{"launch": float(launch[i]), "spin": float(spin[i]), "carry": float(carry[i]), "opt_launch": float(opt_launch[i]), "opt_spin": float(opt_spin[i])}
                   for i in range(0, len(data), step)],
        "map": {"launch": launch_axis.tolist(), "spin": spin_axis.tolist(), "carry": surface.tolist()},
        "_model": model,
    }
