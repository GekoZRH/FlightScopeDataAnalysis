"""Distribution of one measurement (carry, lateral, club speed ...).

A normal distribution is used unless the data clearly show skew. Skew is a
real feature of golf carry (mishits fall short, they do not fly further), but a
skew-normal fitted to a handful of shots is unreliable, so it is only chosen
when enough shots are available *and* a likelihood-ratio test shows it fits
significantly better than a normal distribution.

Ranges are central intervals. The two standard ones cover the same share of
shots as +-1 and +-2 standard deviations of a normal distribution, so for
normal data they are the familiar 1 sigma / 2 sigma values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np
from scipy import stats

COVERAGE_1S = math.erf(1 / math.sqrt(2))   # 0.6827
COVERAGE_2S = math.erf(2 / math.sqrt(2))   # 0.9545

MIN_SCALE = 1e-9


@dataclass(frozen=True)
class Fit:
    """A fitted distribution: kind is 'normal' or 'skewnorm'."""

    kind: str
    n: int
    loc: float
    scale: float
    shape: float = 0.0            # skew-normal shape; 0 for a normal distribution
    p_skew: float = float("nan")  # likelihood-ratio p-value of skew-normal vs normal

    def _dist(self):
        if self.kind == "normal":
            return stats.norm(loc=self.loc, scale=self.scale)
        return stats.skewnorm(self.shape, loc=self.loc, scale=self.scale)

    @property
    def mean(self) -> float:
        return float(self._dist().mean())

    @property
    def sd(self) -> float:
        return float(self._dist().std())

    def pdf(self, x):
        return self._dist().pdf(x)

    def cdf(self, x):
        return self._dist().cdf(x)

    def ppf(self, q):
        return self._dist().ppf(q)

    def interval(self, coverage: float) -> Tuple[float, float]:
        """Central interval containing `coverage` of the shots."""
        tail = (1.0 - coverage) / 2.0
        return float(self.ppf(tail)), float(self.ppf(1.0 - tail))

    def prob_between(self, low: float, high: float) -> float:
        return float(self.cdf(high) - self.cdf(low))


def fit_univariate(values, *, min_n_skew: int = 25, alpha: float = 0.05, allow_skew: bool = True) -> Fit:
    """Fit a normal distribution, or a skew-normal when it is clearly better."""
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        raise ValueError("At least two values are required to fit a distribution")

    mean = float(np.mean(x))
    sd = max(float(np.std(x, ddof=1)), MIN_SCALE)
    normal = Fit(kind="normal", n=n, loc=mean, scale=sd)
    if not allow_skew or n < min_n_skew or np.ptp(x) == 0:
        return normal

    try:
        shape, loc, scale = stats.skewnorm.fit(x)
    except (RuntimeError, ValueError, FloatingPointError):
        return normal
    scale = abs(float(scale))
    if not all(np.isfinite([shape, loc, scale])) or scale < MIN_SCALE:
        return normal

    ll_skew = float(np.sum(stats.skewnorm.logpdf(x, shape, loc=loc, scale=scale)))
    ll_norm = float(np.sum(stats.norm.logpdf(x, loc=mean, scale=max(float(np.std(x)), MIN_SCALE))))
    if not np.isfinite(ll_skew):
        return normal
    p_value = float(stats.chi2.sf(max(0.0, 2.0 * (ll_skew - ll_norm)), df=1))

    if p_value < alpha:
        return Fit(kind="skewnorm", n=n, loc=float(loc), scale=scale, shape=float(shape), p_skew=p_value)
    return Fit(kind="normal", n=n, loc=mean, scale=sd, p_skew=p_value)
