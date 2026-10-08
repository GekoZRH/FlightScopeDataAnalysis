"""Session-by-session statistics, to follow the mean and the spread over time."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from golf.stats.intervals import mean_ci, sd_ci

STAT_COLUMNS = [
    "n", "mean", "sd", "median", "q25", "q75", "min", "max",
    "mean_lo", "mean_hi", "sd_lo", "sd_hi",
]


def _stats(values: np.ndarray, level: float) -> dict:
    n = len(values)
    mean_lo, mean_hi = mean_ci(values, level)
    sd_lo, sd_hi = sd_ci(values, level)
    return {
        "n": n,
        "mean": float(np.mean(values)),
        "sd": float(np.std(values, ddof=1)) if n > 1 else float("nan"),
        "median": float(np.median(values)),
        "q25": float(np.percentile(values, 25)),
        "q75": float(np.percentile(values, 75)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "mean_lo": mean_lo, "mean_hi": mean_hi,
        "sd_lo": sd_lo, "sd_hi": sd_hi,
    }


def session_summary(shots: pd.DataFrame, value: str, *, by: Sequence[str] = ("label",), level: float = 0.95) -> pd.DataFrame:
    """One row per group and session: shot count, mean, spread, and 95% intervals.

    `sd_lo`/`sd_hi` and `mean_lo`/`mean_hi` are exact normal-theory intervals;
    they are NaN for sessions with a single shot.
    """
    by = list(by)
    data = shots.dropna(subset=[value] + by)
    rows = []
    for keys, group in data.groupby(by + ["session_date"], sort=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(by + ["session_date"], keys))
        row.update(_stats(group[value].to_numpy(dtype=float), level))
        rows.append(row)
    return pd.DataFrame(rows, columns=by + ["session_date"] + STAT_COLUMNS)


def rolling_sessions(
    shots: pd.DataFrame,
    value: str,
    *,
    window_sessions: int = 4,
    by: str = "label",
    level: float = 0.95,
) -> pd.DataFrame:
    """Statistics of the shots pooled over the last `window_sessions` sessions.

    One row per group and session: the window ends at that session and covers
    the sessions in which this group was actually hit. Pooling smooths the
    session-to-session noise, so a widening or narrowing spread is easier to see.
    """
    data = shots.dropna(subset=[value, by])
    rows = []
    for key, group in data.groupby(by, sort=False):
        sessions = sorted(group["session_date"].unique())
        for i, end in enumerate(sessions):
            included = sessions[max(0, i - window_sessions + 1): i + 1]
            pooled = group[group["session_date"].isin(included)][value].to_numpy(dtype=float)
            row = {by: key, "session_date": end, "sessions_in_window": len(included)}
            row.update(_stats(pooled, level))
            rows.append(row)
    return pd.DataFrame(rows, columns=[by, "session_date", "sessions_in_window"] + STAT_COLUMNS)
