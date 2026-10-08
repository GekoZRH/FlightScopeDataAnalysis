"""Summary tables used by the printed card and the dashboard."""

from __future__ import annotations

from datetime import date
from typing import Dict, Optional

import numpy as np
import pandas as pd

from golf.config import StatsSettings
from golf.stats.univariate import COVERAGE_1S, COVERAGE_2S, fit_univariate

DESCRIBE_KEYS = ["n", "mean", "sd", "median", "kind", "p_skew", "lo68", "hi68", "lo95", "hi95"]
DEFAULT_METRICS = {"carry": "carry_m", "lateral": "lateral_m"}


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
    """One row per club/intent describing all the given shots (the selected sessions).

    Only shots with a carry and a lateral value count. `as_of`, if given, leaves
    out later sessions. Columns: label, club, variant, intent, status ('ok', or
    'short' when the club has fewer than `settings.min_shots` shots), n,
    `sessions` and `from`/`as_of` (the sessions the whole card covers), then for
    each metric `<name>_<key>` such as `carry_mean`, `carry_lo68`, `lateral_hi95`.
    Rows follow the order of `shots`, so pass the output of `select_bag` for card
    order.
    """
    metrics = metrics or DEFAULT_METRICS
    valid = shots.dropna(subset=["carry_m", "lateral_m", "label"])
    if as_of is not None:
        valid = valid[pd.to_datetime(valid["session_date"]) <= pd.Timestamp(as_of)]
    if valid.empty:
        return pd.DataFrame()

    days = valid["session_date"]
    covered = {"sessions": int(days.nunique()), "from": min(days), "as_of": max(days)}
    order = list(dict.fromkeys(shots["label"].dropna()))
    rows = []
    for label in order:
        group = valid[valid["label"] == label]
        if group.empty:
            continue
        first = group.iloc[0]
        row = {
            "label": label, "club": first["club"], "variant": first["variant"], "intent": int(first["intent"]),
            "status": "ok" if len(group) >= settings.min_shots else "short", "n": len(group), **covered,
        }
        for name, column in metrics.items():
            for key, value in describe(group[column], settings).items():
                row[f"{name}_{key}"] = value
        rows.append(row)
    return pd.DataFrame(rows)
