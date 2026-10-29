"""The wedge distance drill: targets from your own data, and how close you get to them.

A drill session calls out a wedge and a target distance. The target club head speed is the speed at which that
wedge carries the target distance on average, taken from the straight line of carry against club head speed of
that wedge over your swing lengths of 10 o'clock and above (10, 11 and full). You then enter the club head speed you got
(and, if you like, the carry).

- The speed is what you train. The carry still depends on the strike: around the line, the carry of the same speed
  spreads by 6 to 9 m, mostly with the smash factor. So the distance next to a target speed is an estimate, and the
  miss in metres is estimated as the miss in mph times the slope of that wedge (m per mph). When a carry is entered
  too, the miss in metres is also measured directly.
- Targets are kept with each shot in the session file, so sessions stay comparable even when the line is later
  re-fitted with more data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats

from golf.ordering import club_rank
from golf.stats.intervals import wilson_interval

MIN_INTENT = 10                   # swing lengths used for the targets: 10 and 11 o'clock and full (12); 9 o'clock swings are left out
LADDER_STEP_M = 10
MIN_WEDGE_SHOTS = 30
MIN_R2 = 0.5
MIN_SPEED_RANGE_MPH = 15.0        # the swing lengths must cover a range of speeds, or the line says nothing
DEFAULT_SHOTS = 24
DEFAULT_TOLERANCE_MPH = 2.0
MIN_SHOTS_FOR_SESSION = 3         # a session with fewer entered shots is not counted in the progress


@dataclass(frozen=True)
class WedgeFit:
    wedge: str                    # "club variant", e.g. "gw 50"
    n: int
    slope: float                  # m of carry per mph of club head speed
    intercept: float
    r2: float
    resid_sd: float               # m: the spread of the carry around the line
    speed_min: float
    speed_max: float
    carry_min: float
    carry_max: float

    def speed_for(self, distance: float) -> float:
        return (distance - self.intercept) / self.slope

    def carry_at(self, speed: float) -> float:
        return self.intercept + self.slope * speed


def wedge_fits(pitching: pd.DataFrame) -> Dict[str, object]:
    """The speed-to-carry line of every wedge: {"fits": [WedgeFit], "unavailable": [(wedge, reason)]}, in bag order."""
    fits: List[WedgeFit] = []
    unavailable: List[tuple] = []
    if pitching is None or pitching.empty:
        return {"fits": fits, "unavailable": unavailable}
    data = pitching.dropna(subset=["club_speed_mph", "carry_m"]).copy()
    data["wedge"] = (data["club"].fillna("") + " " + data["variant"].fillna("")).str.strip()
    names = sorted(data["wedge"].unique(), key=lambda w: (club_rank(w.partition(" ")[0]), w))
    for wedge in names:
        group = data[data["wedge"] == wedge]
        if wedge == "" or len(group) < MIN_WEDGE_SHOTS:
            if wedge:
                unavailable.append((wedge, f"only {len(group)} shots with speed and carry, {MIN_WEDGE_SHOTS} are needed"))
            continue
        x, y = group["club_speed_mph"].to_numpy(float), group["carry_m"].to_numpy(float)
        if np.ptp(x) < MIN_SPEED_RANGE_MPH:
            unavailable.append((wedge, "the swing lengths cover too small a range of club head speeds"))
            continue
        slope, intercept = np.polyfit(x, y, 1)
        residual = y - (intercept + slope * x)
        r2 = 1.0 - float((residual ** 2).sum() / ((y - y.mean()) ** 2).sum())
        if r2 < MIN_R2 or slope <= 0:
            unavailable.append((wedge, f"club head speed explains only {100 * r2:.0f}% of the carry"))
            continue
        fits.append(WedgeFit(wedge, len(group), float(slope), float(intercept), r2, float(residual.std(ddof=2)),
                             float(x.min()), float(x.max()), float(y.min()), float(y.max())))
    return {"fits": fits, "unavailable": unavailable}


def ladder(fit: WedgeFit, step: int = LADDER_STEP_M) -> List[Dict[str, float]]:
    """Target distances in steps of `step` m that this wedge reaches with club head speeds inside what you have swung."""
    out = []
    first = int(math.ceil(fit.carry_min / step) * step)
    last = int(math.floor(fit.carry_max / step) * step)
    for distance in range(first, last + 1, step):
        speed = fit.speed_for(distance)
        if fit.speed_min - 1.0 <= speed <= fit.speed_max + 1.0:
            out.append({"distance": float(distance), "speed": float(round(speed))})
    return out


def plan_session(fits: List[WedgeFit], shots: int, rng: np.random.Generator) -> List[Dict]:
    """The shots of a session: every chosen wedge about equally often, targets spread over its ladder, in random order.

    Two shots in a row never use the same wedge when there is a choice, and a target is not repeated
    before the others of that wedge have been called.
    """
    if not fits:
        raise ValueError("Choose at least one wedge")
    if shots < len(fits):
        raise ValueError(f"A session needs at least one shot per wedge ({len(fits)})")
    ladders = {fit.wedge: ladder(fit) for fit in fits}
    for fit in fits:
        if not ladders[fit.wedge]:
            raise ValueError(f"The {fit.wedge} has no target distance in the range of speeds you have swung")
    counts = {fit.wedge: shots // len(fits) for fit in fits}
    for wedge in rng.permutation([fit.wedge for fit in fits])[: shots % len(fits)]:
        counts[wedge] += 1

    queues: Dict[str, List[Dict]] = {}
    for fit in fits:
        queue: List[Dict] = []
        while len(queue) < counts[fit.wedge]:
            queue += [ladders[fit.wedge][i] for i in rng.permutation(len(ladders[fit.wedge]))]
        queues[fit.wedge] = queue[: counts[fit.wedge]]
    by_wedge = {fit.wedge: fit for fit in fits}

    order: List[Dict] = []
    previous = None
    remaining = dict(counts)
    while sum(remaining.values()):
        choices = [w for w, c in remaining.items() if c > 0 and w != previous] or [w for w, c in remaining.items() if c > 0]
        weights = np.array([remaining[w] for w in choices], dtype=float)
        wedge = str(rng.choice(choices, p=weights / weights.sum()))
        target = queues[wedge].pop(0)
        remaining[wedge] -= 1
        order.append({"wedge": wedge, "target_m": target["distance"], "target_mph": target["speed"], "slope": by_wedge[wedge].slope})
        previous = wedge
    for number, row in enumerate(order, start=1):
        row["n"] = number
    return order


# --- how close you got --------------------------------------------------------------------------------------

def shot_errors(frame: pd.DataFrame) -> pd.DataFrame:
    """The entered shots of a drill table with their misses: err_mph (+ = too fast), err_m (estimated), abs, hit, carry_err_m."""
    done = frame.dropna(subset=["speed_mph"]).copy()
    done["err_mph"] = done["speed_mph"] - done["target_mph"]
    done["abs_err_mph"] = done["err_mph"].abs()
    done["err_m"] = done["err_mph"] * done["slope"]
    done["hit"] = done["abs_err_mph"] <= done["tolerance_mph"] + 1e-9
    done["carry_err_m"] = done["carry_m"] - done["target_m"]
    return done


def _interval(values: np.ndarray, level: float) -> tuple:
    """t interval of a mean (None, None below 5 values)."""
    if len(values) < 5 or np.std(values, ddof=1) == 0:
        return None, None
    half = stats.t.ppf(0.5 + level / 2.0, len(values) - 1) * np.std(values, ddof=1) / math.sqrt(len(values))
    return float(values.mean() - half), float(values.mean() + half)


_wilson = wilson_interval


def summarise(errors: pd.DataFrame, level: float = 0.95) -> Dict[str, Optional[float]]:
    """The numbers of a set of entered shots (a session, a wedge, a target)."""
    n = len(errors)
    out: Dict[str, Optional[float]] = {"shots": n, "mae_mph": None, "mae_lo": None, "mae_hi": None, "bias_mph": None, "sd_mph": None,
                                       "mae_m": None, "hit_rate": None, "hit_lo": None, "hit_hi": None, "carry_shots": 0, "carry_mae_m": None,
                                       "carry_bias_m": None}
    if not n:
        return out
    absolute = errors["abs_err_mph"].to_numpy(float)
    out.update(mae_mph=float(absolute.mean()), bias_mph=float(errors["err_mph"].mean()),
               sd_mph=float(errors["err_mph"].std(ddof=1)) if n > 1 else None, mae_m=float(errors["err_m"].abs().mean()))
    out["mae_lo"], out["mae_hi"] = _interval(absolute, level)
    hits = int(errors["hit"].sum())
    out["hit_rate"] = 100.0 * hits / n
    out["hit_lo"], out["hit_hi"] = _wilson(hits, n, level)
    carried = errors.dropna(subset=["carry_err_m"])
    out["carry_shots"] = len(carried)
    if len(carried) >= max(3, n // 2):                # a distance miss only when most of the shots have a carry
        out["carry_mae_m"] = float(carried["carry_err_m"].abs().mean())
        out["carry_bias_m"] = float(carried["carry_err_m"].mean())
    return out
