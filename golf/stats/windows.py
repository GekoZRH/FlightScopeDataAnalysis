"""Choose which shots represent the current form.

The printed card uses the last `window_weeks` weeks. A club or intent that has
fewer than `min_shots` shots in that period falls back to the last
`fallback_weeks` weeks, and then to its whole history ('all'), so every club
gets a usable range. The window used is recorded for each club so the card can
mark older data. A club with fewer than `min_shots` shots in total keeps all of
them and is marked 'short'.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Optional

import pandas as pd

from golf.config import StatsSettings


def select_window(
    shots: pd.DataFrame,
    settings: StatsSettings,
    *,
    as_of: Optional[date] = None,
    by: str = "label",
    require: Iterable[str] = ("carry_m", "lateral_m"),
) -> pd.DataFrame:
    """Return the shots of each `by` group that fall in its chosen window.

    Only shots with all `require` columns present are counted and returned.
    `as_of` is the last day included; by default it is the date of the latest
    session in the data, so a card printed right after a practice includes it.

    Added columns: `window` ('4w', '12w', 'all' or 'short'), `window_weeks` (0 for
    'all' and 'short', which are not limited in time) and `as_of`.
    """
    require = list(require)
    valid = shots.dropna(subset=require + [by]).copy()
    if valid.empty:
        return valid.assign(window=pd.Series(dtype="object"), window_weeks=pd.Series(dtype="int64"),
                            as_of=pd.Series(dtype="object"))

    days = pd.to_datetime(valid["session_date"])
    as_of_day = pd.Timestamp(as_of) if as_of is not None else days.max()
    valid = valid[days <= as_of_day]
    days = pd.to_datetime(valid["session_date"])

    def window_start(weeks: int) -> pd.Timestamp:
        return as_of_day - timedelta(days=weeks * 7 - 1)

    primary = days >= window_start(settings.window_weeks)
    fallback = days >= window_start(settings.fallback_weeks)

    parts = []
    for _, group in valid.groupby(by, sort=False):
        idx = group.index
        n_primary = int(primary.loc[idx].sum())
        n_fallback = int(fallback.loc[idx].sum())
        if n_primary >= settings.min_shots:
            chosen, name, weeks = idx[primary.loc[idx].to_numpy()], f"{settings.window_weeks}w", settings.window_weeks
        elif n_fallback >= settings.min_shots:
            chosen, name, weeks = idx[fallback.loc[idx].to_numpy()], f"{settings.fallback_weeks}w", settings.fallback_weeks
        elif len(idx) >= settings.min_shots:
            chosen, name, weeks = idx, "all", 0
        else:
            chosen, name, weeks = idx, "short", 0
        if len(chosen):
            parts.append(valid.loc[chosen].assign(window=name, window_weeks=weeks, as_of=as_of_day.date()))

    if not parts:
        return valid.iloc[0:0].assign(window="", window_weeks=0, as_of=as_of_day.date())
    return pd.concat(parts).sort_values(["timestamp", "shot_index"], kind="stable")
