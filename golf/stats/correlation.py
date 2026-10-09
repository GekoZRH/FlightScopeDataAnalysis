"""Correlation between two measures, with an interval that shows how much (or little) it can tell.

With a few dozen sessions a correlation is very uncertain, so the interval is as important as the number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class Correlation:
    n: int
    r: float
    low: float          # lower end of the interval of r
    high: float         # upper end of the interval of r
    slope: float        # least-squares line y = slope * x + intercept
    intercept: float


def correlate(x, y, *, level: float = 0.95, min_n: int = 5) -> Optional[Correlation]:
    """Pearson correlation of two samples with a Fisher-z interval.

    Pairs with a missing value are dropped. Returns None when there are fewer than `min_n` pairs or when
    one of the measures does not vary (a correlation does not exist then).
    """
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    n = len(a)
    if n < max(min_n, 4) or np.std(a) == 0 or np.std(b) == 0:
        return None

    r = float(np.clip(np.corrcoef(a, b)[0, 1], -0.999999, 0.999999))
    half = stats.norm.ppf(0.5 + level / 2.0) / np.sqrt(n - 3)
    low, high = np.tanh(np.arctanh(r) - half), np.tanh(np.arctanh(r) + half)
    slope, intercept = np.polyfit(a, b, 1)
    return Correlation(n=n, r=r, low=float(low), high=float(high), slope=float(slope), intercept=float(intercept))
