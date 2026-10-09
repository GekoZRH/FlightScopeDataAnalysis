"""One result number per practice session, comparable between sessions.

To relate golf results to sleep or training, every session needs a single number that says how good it
was compared with what is usual, independent of which clubs or weights happened to be used.

Because you improve over the weeks, a rising trend can look like an effect of whatever else changed
over time. So each value can be compared with the *trend* of that club or weight instead of with its
overall average (`detrend=True`).
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

MIN_SESSIONS_FOR_TREND = 4


def _expected(days: np.ndarray, values: np.ndarray, detrend: bool) -> np.ndarray:
    """The usual level at each day: a straight line through time (if allowed and possible), else the mean."""
    if detrend and len(values) >= MIN_SESSIONS_FOR_TREND and np.ptp(days) > 0:
        slope, intercept = np.polyfit(days, values, 1)
        return slope * days + intercept
    return np.full(len(values), float(np.mean(values)))


def relative_to_usual(table: pd.DataFrame, *, detrend: bool) -> pd.DataFrame:
    """Combine per-club session values into one number per session.

    `table` has the columns date, club and value (for example the mean club head speed of that club in that
    session). Each value becomes the percentage by which it differs from the usual level of the same club;
    a session's number is the average over the clubs hit in it.
    Returns the columns date, value (percent) and clubs (how many clubs went into it).
    """
    parts = []
    for _, group in table.groupby("club"):
        group = group.sort_values("date")
        days = pd.to_datetime(group["date"]).map(pd.Timestamp.toordinal).to_numpy(dtype=float)
        values = group["value"].to_numpy(dtype=float)
        if len(values) < 2:                      # a club seen in one session has no "usual" to compare with
            continue
        expected = _expected(days, values, detrend)
        valid = expected > 0
        parts.append(pd.DataFrame({"date": group["date"].to_numpy()[valid],
                                   "value": 100.0 * (values[valid] / expected[valid] - 1.0)}))
    if not parts:
        return pd.DataFrame(columns=["date", "value", "clubs"])
    combined = pd.concat(parts)
    out = combined.groupby("date")["value"].agg(["mean", "size"]).reset_index()
    return out.rename(columns={"mean": "value", "size": "clubs"})


def swing_speed(swing: pd.DataFrame, *, detrend: bool, club: Optional[str] = None, min_shots: int = 3) -> pd.DataFrame:
    """Club head speed of each full-swing session, in percent compared with the usual speed of the same club(s)."""
    return _per_club(swing, "club_speed_mph", "mean", detrend, club, min_shots)


def swing_spread(swing: pd.DataFrame, *, detrend: bool, club: Optional[str] = None, min_shots: int = 5) -> pd.DataFrame:
    """Carry spread (standard deviation) of each full-swing session, in percent compared with the usual spread."""
    return _per_club(swing, "carry_m", "std", detrend, club, min_shots)


def _per_club(swing: pd.DataFrame, column: str, statistic: str, detrend: bool, club: Optional[str], min_shots: int) -> pd.DataFrame:
    data = swing.dropna(subset=[column])
    if club:
        data = data[data["label"] == club]
    grouped = data.groupby(["session_date", "label"])[column].agg([statistic, "size"]).reset_index()
    grouped = grouped[grouped["size"] >= min_shots]
    table = grouped.rename(columns={"session_date": "date", "label": "club", statistic: "value"})[["date", "club", "value"]]
    return relative_to_usual(table, detrend=detrend)


def stack_speed(stack: pd.DataFrame, *, detrend: bool, reference_weight: Optional[float] = None) -> pd.DataFrame:
    """Stack speed of each session, expressed for one reference weight, in mph.

    Different weights are used in different sessions, and a heavier club is slower. The speed loss per gram is
    estimated from the weights *within* sessions, and every session's average is moved to the reference weight
    (default: the weight that appears in the most sessions). With `detrend` the value is the difference to the
    straight-line trend through the sessions, in mph; without it, the speed at the reference weight itself.
    Returns the columns date, value, weight (the reference) and swings.
    """
    data = stack.dropna(subset=["weight_g", "club_speed_mph"])
    if data.empty:
        return pd.DataFrame(columns=["date", "value", "weight", "swings"])
    if reference_weight is None:
        reference_weight = float(data.groupby("weight_g")["session_date"].nunique().sort_values(kind="stable").index[-1])

    weight_in_session = data.groupby("session_date")["weight_g"].transform("mean")
    speed_in_session = data.groupby("session_date")["club_speed_mph"].transform("mean")
    dw, dv = data["weight_g"] - weight_in_session, data["club_speed_mph"] - speed_in_session
    slope = float((dw * dv).sum() / (dw ** 2).sum()) if (dw ** 2).sum() > 0 else 0.0

    adjusted = data["club_speed_mph"] - slope * (data["weight_g"] - reference_weight)
    sessions = adjusted.groupby(data["session_date"]).agg(["mean", "size"]).reset_index()
    sessions.columns = ["date", "value", "swings"]
    if detrend:
        days = pd.to_datetime(sessions["date"]).map(pd.Timestamp.toordinal).to_numpy(dtype=float)
        sessions["value"] = sessions["value"].to_numpy() - _expected(days, sessions["value"].to_numpy(), True)
    sessions["weight"] = reference_weight
    return sessions[["date", "value", "weight", "swings"]]
