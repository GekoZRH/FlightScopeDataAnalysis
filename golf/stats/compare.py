"""Compare two sets of shots, e.g. the recent weeks against the weeks before.

A change is only reported when its bootstrap interval excludes "no change",
so one lucky or unlucky session does not read as progress.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Union

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


# Statistics that can be computed on all bootstrap samples at once (fast path).
_VECTORISED = {
    "sd": lambda a, axis: np.std(a, ddof=1, axis=axis),
    "mean": lambda a, axis: np.mean(a, axis=axis),
}


def _evaluate(statistic, samples: np.ndarray) -> np.ndarray:
    """Statistic of every row of `samples`."""
    if isinstance(statistic, str):
        return _VECTORISED[statistic](samples, 1)
    return np.apply_along_axis(statistic, 1, samples)


def _single(statistic, values: np.ndarray) -> float:
    return float(_evaluate(statistic, values[None, :])[0])


def compare_groups(
    recent,
    before,
    statistic: Union[str, Callable[[np.ndarray], float]] = "sd",
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
    `statistic` is 'sd', 'mean' or a function of one sample.
    """
    a = np.asarray(recent, dtype=float)
    b = np.asarray(before, dtype=float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    nan = float("nan")
    if len(a) < min_n or len(b) < min_n:
        return Comparison(nan, nan, nan, len(a), len(b), None)

    rng = rng or np.random.default_rng(0)
    sa = _evaluate(statistic, rng.choice(a, size=(n_boot, len(a)), replace=True))
    sb = _evaluate(statistic, rng.choice(b, size=(n_boot, len(b)), replace=True))
    change = sa / sb if ratio else sa - sb
    point = _single(statistic, a) / _single(statistic, b) if ratio else _single(statistic, a) - _single(statistic, b)

    tail = (1.0 - level) / 2.0 * 100
    low, high = np.percentile(change, [tail, 100 - tail])
    neutral = 1.0 if ratio else 0.0
    direction = -1 if high < neutral else (1 if low > neutral else 0)
    return Comparison(float(point), float(low), float(high), len(a), len(b), direction)


def compare_normal(
    recent,
    before,
    what: str = "sd",
    *,
    level: float = 0.95,
    min_n: int = 5,
) -> Comparison:
    """Exact (normal-theory) change in the mean or the spread between two samples.

    Meant for small samples, such as one session against the sessions before it,
    where a bootstrap of the spread is too optimistic. The estimate is
    `recent - before` for 'mean' (Welch interval) or for 'sd' (F-ratio interval,
    converted to a difference in the units of the data). It assumes the shots are
    roughly normal; heavy tails make the 'sd' interval too narrow.
    """
    from scipy import stats

    a = np.asarray(recent, dtype=float)
    b = np.asarray(before, dtype=float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    nan = float("nan")
    if len(a) < max(min_n, 2) or len(b) < max(min_n, 2):
        return Comparison(nan, nan, nan, len(a), len(b), None)

    alpha = 1.0 - level
    va, vb = np.var(a, ddof=1), np.var(b, ddof=1)
    if what == "mean":
        se2 = va / len(a) + vb / len(b)
        if se2 == 0:
            return Comparison(0.0, 0.0, 0.0, len(a), len(b), 0)
        df = se2 ** 2 / ((va / len(a)) ** 2 / (len(a) - 1) + (vb / len(b)) ** 2 / (len(b) - 1))
        half = stats.t.ppf(1 - alpha / 2, df) * np.sqrt(se2)
        point = float(np.mean(a) - np.mean(b))
        low, high = point - float(half), point + float(half)
    elif what == "sd":
        if vb == 0 or va == 0:
            return Comparison(nan, nan, nan, len(a), len(b), None)
        f = va / vb
        df1, df2 = len(a) - 1, len(b) - 1
        ratio_low = np.sqrt(f / stats.f.ppf(1 - alpha / 2, df1, df2))
        ratio_high = np.sqrt(f / stats.f.ppf(alpha / 2, df1, df2))
        sd_before = float(np.sqrt(vb))
        point = float(np.sqrt(va)) - sd_before
        low, high = sd_before * (ratio_low - 1), sd_before * (ratio_high - 1)
    else:
        raise ValueError("what must be 'mean' or 'sd'")

    direction = -1 if high < 0 else (1 if low > 0 else 0)
    return Comparison(point, float(low), float(high), len(a), len(b), direction)
