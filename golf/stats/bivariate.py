"""Joint distribution of lateral and carry distance.

Each direction keeps its own marginal (normal or skew-normal) and the two are
tied together with a Gaussian copula, so the correlation between lateral miss
and carry is kept. With two normal marginals this is exactly the familiar
bivariate normal ("covariance ellipse").
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from golf.stats.univariate import Fit, fit_univariate

_EPS = 1e-12
_MAX_RHO = 0.999


@dataclass(frozen=True)
class Bivariate:
    x: Fit        # lateral
    y: Fit        # carry
    rho: float    # correlation of the normal scores

    def pdf(self, x, y):
        u = np.clip(self.x.cdf(x), _EPS, 1 - _EPS)
        v = np.clip(self.y.cdf(y), _EPS, 1 - _EPS)
        a, b = stats.norm.ppf(u), stats.norm.ppf(v)
        r = self.rho
        copula = np.exp(-(r * r * (a * a + b * b) - 2 * r * a * b) / (2 * (1 - r * r))) / np.sqrt(1 - r * r)
        return self.x.pdf(x) * self.y.pdf(y) * copula

    def sample(self, n: int, rng: np.random.Generator):
        cov = [[1.0, self.rho], [self.rho, 1.0]]
        z = rng.multivariate_normal([0.0, 0.0], cov, size=n)
        u = stats.norm.cdf(z)
        return self.x.ppf(u[:, 0]), self.y.ppf(u[:, 1])

    def density_level(self, coverage: float, n: int = 200_000, seed: int = 0) -> float:
        """Density value whose contour encloses `coverage` of the shots.

        Found by sampling from the model: the region of highest density that
        holds `coverage` of the probability ends where the density drops to the
        (1 - coverage) quantile of the density at sampled points.
        """
        rng = np.random.default_rng(seed)
        x, y = self.sample(n, rng)
        return float(np.quantile(self.pdf(x, y), 1.0 - coverage))


def fit_bivariate(lateral, carry, **fit_kwargs) -> Bivariate:
    """Fit lateral and carry jointly. Pairs with a missing value are dropped."""
    x = np.asarray(lateral, dtype=float)
    y = np.asarray(carry, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 3:
        raise ValueError("At least three shots are required for a joint fit")

    fx = fit_univariate(x, **fit_kwargs)
    fy = fit_univariate(y, **fit_kwargs)
    a = stats.norm.ppf(np.clip(fx.cdf(x), _EPS, 1 - _EPS))
    b = stats.norm.ppf(np.clip(fy.cdf(y), _EPS, 1 - _EPS))
    rho = float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else 0.0
    rho = float(np.clip(rho, -_MAX_RHO, _MAX_RHO))
    return Bivariate(x=fx, y=fy, rho=rho)
