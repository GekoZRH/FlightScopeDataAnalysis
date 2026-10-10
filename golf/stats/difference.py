"""Difference between the averages of two groups, with an interval (Welch's t-test interval).

Used to ask whether nights that follow something (for example a strength session shortly before bed) differ from
nights that do not. Welch's interval does not assume the two groups vary equally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class Difference:
    n_a: int
    n_b: int
    mean_a: float
    mean_b: float
    diff: float          # mean_a - mean_b
    low: float
    high: float


def mean_difference(a, b, *, level: float = 0.95, min_n: int = 3) -> Optional[Difference]:
    """Mean of `a` minus mean of `b` with its interval; missing values are dropped.

    Returns None when a group has fewer than `min_n` values (its spread cannot be judged) or when neither group
    varies at all.
    """
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    x, y = x[np.isfinite(x)], y[np.isfinite(y)]
    if len(x) < max(min_n, 2) or len(y) < max(min_n, 2):
        return None
    vx, vy = np.var(x, ddof=1) / len(x), np.var(y, ddof=1) / len(y)
    if vx + vy == 0:
        return None
    se = float(np.sqrt(vx + vy))
    df = (vx + vy) ** 2 / ((vx ** 2 / (len(x) - 1) if vx else 0.0) + (vy ** 2 / (len(y) - 1) if vy else 0.0))
    half = float(stats.t.ppf(0.5 + level / 2.0, df)) * se
    diff = float(np.mean(x) - np.mean(y))
    return Difference(len(x), len(y), float(np.mean(x)), float(np.mean(y)), diff, diff - half, diff + half)
