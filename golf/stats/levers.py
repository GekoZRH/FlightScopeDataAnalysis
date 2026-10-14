"""Which factors go with distance, for one club: the levers of carry.

Two views, each a regression of the carry of every shot of one club on standardised factors, so that each effect is
*the change in carry in metres for one standard deviation more of that factor, the others held at their usual level*.
That puts factors with different units on one scale: a big effect per standard deviation is worth working on.

- **What the ball does**: club head speed, smash factor (how efficiently the speed is passed on, i.e. strike
  quality), launch angle and spin rate. These decide the carry directly.
- **What the club does**: club head speed, attack angle, dynamic loft, club path and face to path. These are the
  delivery numbers that produce launch and spin, so their effect on carry runs through the ball flight. They explain
  less of the carry than the ball flight does, because strike location (not measured for most shots) is missing.

What this is and is not:
- It is estimated from the natural shot-to-shot variation of that club in your data, so it is valid near your usual
  values. Where a factor has no clear effect it is either unimportant or already near its best value.
- It is an association within your shots, not an experiment. Factors move together, and the regression separates
  them only as far as the data allows (the low point of the swing is left out because it is almost the same
  measurement as the attack angle).
- For club path and face to path the sign is the direction (negative is left), and a "best" value is usually near zero:
  a linear effect there says which side loses carry, not that more is always better.
- Club head speed is shown for comparison, but it is not counted as a lever.
- Shots of one session are not independent (same day, same mat, same feel). The intervals allow for that: the
  spread of an effect is judged from how much it changes when one whole session is left out (a jackknife by session),
  with a t distribution on sessions - 1 degrees of freedom. In simulations a bootstrap that redraws whole sessions
  called a non-existent effect clear too often when there were only a handful of sessions (17% instead of 5% with 5
  sessions); the leave-one-session-out intervals stay at 3 to 6%. With few sessions the intervals are wide, and that
  is the honest answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

# column, title, unit, counts as a lever (something you can work on)
BALL_FLIGHT = (
    ("club_speed_mph", "Club head speed", "mph", False),
    ("smash", "Smash factor (strike quality)", "", True),
    ("launch_v_deg", "Launch angle", "deg", True),
    ("spin_rpm", "Spin rate", "rpm", True),
)
CLUB = (
    ("club_speed_mph", "Club head speed", "mph", False),
    ("aoa_deg", "Attack angle", "deg", True),
    ("dynamic_loft_deg", "Dynamic loft", "deg", True),
    ("club_path_deg", "Club path (negative = left)", "deg", True),
    ("ftp_deg", "Face to path (negative = left)", "deg", True),
)
GROUPS: Tuple[Tuple[str, str, tuple], ...] = (
    ("ball", "What the ball does", BALL_FLIGHT),
    ("club", "What the club does", CLUB),
)
MIN_SHOTS = 30
MIN_SESSIONS = 4


@dataclass(frozen=True)
class Lever:
    key: str
    title: str
    unit: str
    lever: bool          # False for the reference factor (club head speed)
    mean: float
    sd: float            # one standard deviation of the factor in this club's shots, in its own unit
    effect: float        # change in carry (m) for one standard deviation more of the factor
    low: float
    high: float

    @property
    def clear(self) -> bool:
        return self.low > 0 or self.high < 0


@dataclass(frozen=True)
class Levers:
    n: int
    sessions: int
    carry_mean: float
    carry_sd: float
    r2: float
    factors: List[Lever]

    def biggest(self) -> Optional[Lever]:
        """The lever with the largest clear effect, or None if no lever has a clear effect."""
        clear = [f for f in self.factors if f.lever and f.clear]
        return max(clear, key=lambda f: abs(f.effect)) if clear else None


def levers_of(shots: pd.DataFrame, factors, *, level: float = 0.95) -> Optional[Levers]:
    """The levers of carry for the shots of one club (columns carry_m, session_date and the columns of `factors`).

    Returns None when there are too few shots or sessions with all the factors, or a factor does not vary.
    """
    columns = [column for column, *_ in factors]
    if any(column not in shots.columns for column in columns):
        return None
    data = shots.dropna(subset=["carry_m", "session_date"] + columns)
    sessions = data["session_date"].to_numpy()
    unique = list(dict.fromkeys(sessions))
    if len(data) < MIN_SHOTS or len(unique) < MIN_SESSIONS:
        return None
    x = data[columns].to_numpy(dtype=float)
    y = data["carry_m"].to_numpy(dtype=float)
    mean, sd = x.mean(axis=0), x.std(axis=0, ddof=1)
    if np.any(sd == 0):
        return None
    design = np.column_stack([np.ones(len(x)), (x - mean) / sd])
    n, k = design.shape

    def fit(rows: np.ndarray) -> np.ndarray:
        return np.linalg.lstsq(design[rows], y[rows], rcond=None)[0]

    beta = fit(np.ones(n, dtype=bool))
    residual = y - design @ beta
    r2 = 1.0 - float((residual ** 2).sum() / ((y - y.mean()) ** 2).sum())

    # leave one whole session out at a time: how much the effects move says how far to trust them
    g = len(unique)
    left_out = np.array([fit(sessions != session) for session in unique])
    centred = left_out - left_out.mean(axis=0)
    se = np.sqrt(((g - 1) / g) * (centred ** 2).sum(axis=0))
    half = stats.t.ppf(0.5 + level / 2.0, g - 1) * se
    low, high = beta - half, beta + half

    out = [
        Lever(key=column, title=title, unit=unit, lever=lever, mean=float(mean[i]), sd=float(sd[i]),
              effect=float(beta[i + 1]), low=float(low[i + 1]), high=float(high[i + 1]))
        for i, (column, title, unit, lever) in enumerate(factors)
    ]
    return Levers(n=len(data), sessions=len(unique), carry_mean=float(y.mean()), carry_sd=float(y.std(ddof=1)), r2=r2, factors=out)


def distance_levers(shots: pd.DataFrame, *, level: float = 0.95) -> Dict[str, Optional[Levers]]:
    """Both views of one club: group key ("ball", "club") -> its levers, or None if the data does not allow it."""
    return {key: levers_of(shots, factors, level=level) for key, _, factors in GROUPS}
