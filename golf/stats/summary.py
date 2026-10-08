"""Summary tables used by the printed card and the dashboard."""

from __future__ import annotations

from datetime import date
from typing import Dict, Optional

import numpy as np
import pandas as pd

from golf.config import StatsSettings
from golf.stats.univariate import COVERAGE_1S, COVERAGE_2S, fit_univariate
from golf.stats.windows import select_window

DESCRIBE_KEYS = ["n", "mean", "sd", "median", "kind", "p_skew", "lo68", "hi68", "lo95", "hi95"]
DEFAULT_METRICS = {"carry": "carry_m", "lateral": "lateral_m"}
STATUS = {"all": "history", "short": "short"}


def describe(values, settings: StatsSettings, *, allow_skew: bool = True) -> dict:
    """Mean, spread and the central 68% / 95% ranges of one measurement.

    `mean` and `sd` come from the fitted model (normal or skew-normal), `median`
    from the shots themselves. Mishits are never removed.
    """
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        out = {key: float("nan") for key in DESCRIBE_KEYS}
        out.update(n=len(x), kind="")
        return out

    fit = fit_univariate(x, min_n_skew=settings.min_shots_skew, alpha=settings.skew_alpha, allow_skew=allow_skew)
    lo68, hi68 = fit.interval(COVERAGE_1S)
    lo95, hi95 = fit.interval(COVERAGE_2S)
    return {
        "n": len(x), "mean": fit.mean, "sd": fit.sd, "median": float(np.median(x)),
        "kind": fit.kind, "p_skew": fit.p_skew,
        "lo68": lo68, "hi68": hi68, "lo95": lo95, "hi95": hi95,
    }


def card_table(
    shots: pd.DataFrame,
    settings: StatsSettings,
    *,
    as_of: Optional[date] = None,
    metrics: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """One row per club/intent describing the current form (the card window).

    Columns: label, club, variant, intent, window ('4w', '12w', 'all' or 'short'),
    status ('ok' for a recent window, 'history' for all history, 'short' if the
    club has too few shots in total), n, then for each metric `<name>_<key>` such as
    `carry_mean`, `carry_lo68`, `lateral_hi95`. Rows follow the order of
    `shots`, so pass the output of `select_bag` for card order.
    """
    metrics = metrics or DEFAULT_METRICS
    recent = select_window(shots, settings, require=("carry_m", "lateral_m"))
    order = list(dict.fromkeys(shots["label"].dropna()))
    rows = []
    for label in order:
        group = recent[recent["label"] == label]
        if group.empty:
            continue
        first = group.iloc[0]
        row = {
            "label": label, "club": first["club"], "variant": first["variant"],
            "intent": int(first["intent"]), "window": first["window"],
            "status": STATUS[first["window"]] if first["window"] in STATUS else "ok",
            "n": len(group), "as_of": first["as_of"],
        }
        for name, column in metrics.items():
            for key, value in describe(group[column], settings).items():
                row[f"{name}_{key}"] = value
        rows.append(row)
    return pd.DataFrame(rows)
