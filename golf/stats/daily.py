"""One row per day of health data (Garmin watch and Withings scale), to see how the measures relate to each other.

Unlike `context.py` (what was recorded before a practice session) this uses every day in the exports, so
it has hundreds of rows instead of a handful of sessions. A night's training measures only count what
ended before you went to bed. A day is the day you woke up on (Garmin) or the day of the weighing (Withings).
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from golf.data.garmin import GarminData
from golf.data.withings import WithingsData
from golf.stats.context import PREDICTORS

TRAINING = "Training before the night"
BODY = "Body (scale)"

# key -> (title, group in the menus)
GARMIN_MEASURES: Dict[str, Tuple[str, str]] = {
    **{key: PREDICTORS[key] for key in ("sleep_h", "sleep_score", "deep_min", "rem_min", "awake_min")},
    "bedtime_h": ("Bedtime (clock hour, 25 = 1 am)", "Sleep"),
    **{key: PREDICTORS[key] for key in ("hrv_ms", "night_hr")},
    "strength_min_4h": ("Strength training time, 4 h before bed (min)", TRAINING),
    "strength_min_12h": ("Strength training time, 12 h before bed (min)", TRAINING),
    "strength_min_24h": ("Strength training time, 24 h before bed (min)", TRAINING),
    "strength_load_24h": ("Strength training load, 24 h before bed", TRAINING),
    "strength_min_72h": ("Strength training time, 72 h before bed (min)", TRAINING),
    "cardio_min_24h": ("Cardio time, 24 h before bed (min)", TRAINING),
    "cardio_min_72h": ("Cardio time, 72 h before bed (min)", TRAINING),
}
BODY_MEASURES: Dict[str, Tuple[str, str]] = {
    "weight_kg": ("Weight (kg)", BODY),
    "bmi": ("Body mass index", BODY),
    "fat_kg": ("Fat mass (kg)", BODY),
    "fat_pct": ("Body fat (%)", BODY),
    "muscle_kg": ("Muscle mass (kg)", BODY),
    "hydration_kg": ("Water (kg)", BODY),
}
DAILY_MEASURES: Dict[str, Tuple[str, str]] = {**GARMIN_MEASURES, **BODY_MEASURES}

# Nights are recorded almost every day, weighings only every week or two: the smoothed lines need longer windows.
# group -> ((short days, long days), (nights needed for the short mean, for the long mean))
TREND_WINDOWS = {BODY: ((30, 90), (2, 3))}
DEFAULT_WINDOWS = ((7, 28), (3, 10))


def windows_for(measure: str):
    """The two averaging windows (in days) and the number of values each needs, for one measure."""
    return TREND_WINDOWS.get(DAILY_MEASURES[measure][1], DEFAULT_WINDOWS)


def available_measures(garmin: Optional[GarminData], withings: Optional[WithingsData]) -> Dict[str, Tuple[str, str]]:
    """The measures that can be shown with the data that is loaded."""
    chosen: Dict[str, Tuple[str, str]] = {}
    if garmin is not None:
        chosen.update(GARMIN_MEASURES)
    if withings is not None:
        chosen.update(BODY_MEASURES)
    return chosen


def _bedtime(start_utc: pd.Series, timezone: str) -> pd.Series:
    """Local clock hour of falling asleep; after midnight counts on from 24 (1 am is 25)."""
    local = start_utc.dt.tz_convert(timezone)
    hour = local.dt.hour + local.dt.minute / 60.0
    return (hour - 12.0) % 24.0 + 12.0


def _sum_before(bed: np.ndarray, ends: np.ndarray, values: np.ndarray, hours: int) -> np.ndarray:
    """For each bedtime the sum of `values` of activities that ended within `hours` before it."""
    window = np.timedelta64(hours, "h")
    out = np.zeros(len(bed))
    for i, b in enumerate(bed):
        inside = (ends <= b) & (ends >= b - window)
        out[i] = values[inside].sum()
    return out


def _garmin_table(garmin: GarminData, timezone: str) -> pd.DataFrame:
    sleep = garmin.sleep
    table = sleep.set_index("date")[["asleep_h", "score", "deep_min", "rem_min", "awake_min"]].rename(
        columns={"asleep_h": "sleep_h", "score": "sleep_score"})
    table["bedtime_h"] = _bedtime(sleep["start_utc"], timezone).to_numpy()
    for column in ("hrv_ms", "night_hr"):
        table[column] = np.nan
    if not garmin.vitals.empty:
        vitals = garmin.vitals.set_index("date")
        table["hrv_ms"] = vitals["hrv_ms"].reindex(table.index)
        table["night_hr"] = vitals["night_hr"].reindex(table.index)

    bed = sleep["start_utc"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy("datetime64[ns]")
    acts = garmin.activities
    for group in ("strength", "cardio"):
        chosen = acts[acts["group"] == group] if not acts.empty else acts
        ends = chosen["end_utc"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy("datetime64[ns]") if len(chosen) else np.array([], dtype="datetime64[ns]")
        minutes = chosen["minutes"].to_numpy(dtype=float) if len(chosen) else np.array([])
        load = chosen["load"].fillna(0).to_numpy(dtype=float) if len(chosen) else np.array([])
        hours = (4, 12, 24, 72) if group == "strength" else (24, 72)
        for h in hours:
            table[f"{group}_min_{h}h"] = _sum_before(bed, ends, minutes, h)
        if group == "strength":
            table["strength_load_24h"] = _sum_before(bed, ends, load, 24)
    return table


def _body_table(withings: WithingsData) -> pd.DataFrame:
    body = withings.body.set_index("date")
    body = body.assign(fat_pct=body["fat_kg"] / body["weight_kg"] * 100.0)
    return body[list(BODY_MEASURES)]


def daily_table(garmin: Optional[GarminData], timezone: str, withings: Optional[WithingsData] = None) -> pd.DataFrame:
    """One row per day, indexed by date, with the columns of `DAILY_MEASURES`.

    A night is a row on the day you woke up, a weighing a row on its day; a day with both has both. A measure
    the day does not have is NaN (and never 0, except training, which is 0 minutes on a night with none).
    """
    parts = []
    if garmin is not None and not garmin.sleep.empty:
        parts.append(_garmin_table(garmin, timezone))
    if withings is not None and not withings.body.empty:
        parts.append(_body_table(withings))
    if not parts:
        return pd.DataFrame(columns=list(DAILY_MEASURES))
    table = parts[0] if len(parts) == 1 else parts[0].join(parts[1], how="outer")
    return table.reindex(columns=list(DAILY_MEASURES)).sort_index()


def rolling_means(series: pd.Series, windows=(7, 28), minimum=(3, 10)) -> pd.DataFrame:
    """Smoothed course of one measure: the mean of the last `windows[0]` and of the last `windows[1]` days.

    `series` is indexed by date and has no missing values. Measurements are not evenly spaced (watch off,
    no weighing), so the windows are counted in days, and a mean is only shown when its window holds at
    least `minimum` values.
    """
    if series.empty:
        return pd.DataFrame(columns=["short", "long"])
    series = pd.Series(series.to_numpy(dtype=float), index=pd.to_datetime(series.index)).sort_index()
    out = pd.DataFrame({
        "short": series.rolling(f"{windows[0]}D", min_periods=minimum[0]).mean(),
        "long": series.rolling(f"{windows[1]}D", min_periods=minimum[1]).mean(),
    })
    out.index = [d.date() for d in out.index]
    return out
