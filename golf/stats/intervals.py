"""Confidence intervals for the mean and spread of a set of shots.

Per-session samples are small (often 5-15 shots). For those the exact
normal-theory intervals (t for the mean, chi-square for the standard
deviation) are used: bootstrapping a standard deviation from so few shots gives
intervals that are too narrow. The bootstrap is used where samples are larger
(see `compare.py`).
"""

from __future__ import annotations

from typing import Callable, Tuple

import numpy as np
from scipy import stats

NAN_PAIR = (float("nan"), float("nan"))


def _clean(values) -> np.ndarray:
    x = np.asarray(values, dtype=float)
    return x[np.isfinite(x)]


def mean_ci(values, level: float = 0.95) -> Tuple[float, float]:
    x = _clean(values)
    if len(x) < 2:
        return NAN_PAIR
    half = stats.t.ppf(0.5 + level / 2, df=len(x) - 1) * np.std(x, ddof=1) / np.sqrt(len(x))
    m = float(np.mean(x))
    return m - float(half), m + float(half)


def sd_ci(values, level: float = 0.95) -> Tuple[float, float]:
    x = _clean(values)
    n = len(x)
    if n < 2:
        return NAN_PAIR
    s = float(np.std(x, ddof=1))
    low = s * np.sqrt((n - 1) / stats.chi2.ppf(0.5 + level / 2, df=n - 1))
    high = s * np.sqrt((n - 1) / stats.chi2.ppf(0.5 - level / 2, df=n - 1))
    return float(low), float(high)


def bootstrap_ci(
    values,
    statistic: Callable[[np.ndarray], float],
    *,
    level: float = 0.95,
    n_boot: int = 2000,
    rng: np.random.Generator | None = None,
) -> Tuple[float, float]:
    """Percentile bootstrap interval of any statistic of one sample."""
    x = _clean(values)
    if len(x) < 2:
        return NAN_PAIR
    rng = rng or np.random.default_rng(0)
    draws = rng.choice(x, size=(n_boot, len(x)), replace=True)
    estimates = np.apply_along_axis(statistic, 1, draws)
    tail = (1.0 - level) / 2.0 * 100
    low, high = np.percentile(estimates, [tail, 100 - tail])
    return float(low), float(high)
