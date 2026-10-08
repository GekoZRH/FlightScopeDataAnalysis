"""Compare two sets of shots, e.g. the recent weeks against the weeks before.

A change is only reported when its bootstrap interval excludes "no change",
so one lucky or unlucky session does not read as progress.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


@dataclass(frozen=True)
class Comparison:
    estimate: float          # statistic(recent) / statistic(before), or their difference
    low: float
    high: float
    n_recent: int
    n_before: int
    direction: int | None    # -1 lower/tighter, +1 higher/broader, 0 no clear change, None too few shots


def _sample_sd(a: np.ndarray) -> float:
    return float(np.std(a, ddof=1))


def compare_groups(
    recent,
    before,
    statistic: Callable[[np.ndarray], float] = _sample_sd,
    *,
    ratio: bool = True,
    level: float = 0.95,
    n_boot: int = 2000,
    min_n: int = 8,
    rng: np.random.Generator | None = None,
) -> Comparison:
    """Bootstrap the change in a statistic between two samples.

    Default: ratio of standard deviations (recent / before). Below 1 means the
    shots have become tighter. Use `ratio=False` for a difference, e.g. of means.
    """
    a = np.asarray(recent, dtype=float)
    b = np.asarray(before, dtype=float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    nan = float("nan")
    if len(a) < min_n or len(b) < min_n:
        return Comparison(nan, nan, nan, len(a), len(b), None)

    rng = rng or np.random.default_rng(0)
    sa = np.apply_along_axis(statistic, 1, rng.choice(a, size=(n_boot, len(a)), replace=True))
    sb = np.apply_along_axis(statistic, 1, rng.choice(b, size=(n_boot, len(b)), replace=True))
    change = sa / sb if ratio else sa - sb
    point = statistic(a) / statistic(b) if ratio else statistic(a) - statistic(b)

    tail = (1.0 - level) / 2.0 * 100
    low, high = np.percentile(change, [tail, 100 - tail])
    neutral = 1.0 if ratio else 0.0
    direction = -1 if high < neutral else (1 if low > neutral else 0)
    return Comparison(float(point), float(low), float(high), len(a), len(b), direction)
