"""One row per night of Garmin data, to see how the Garmin measures relate to each other.

Unlike `context.py` (what was recorded before a practice session) this uses every night in the export, so
it has hundreds of rows instead of a handful of sessions. A night's training measures only count what
ended before you went to bed.
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from golf.data.garmin import GarminData
from golf.stats.context import PREDICTORS

TRAINING = "Training before the night"

# key -> (title, group in the menus)
DAILY_MEASURES: Dict[str, Tuple[str, str]] = {
    **{key: PREDICTORS[key] for key in ("sleep_h", "sleep_score", "deep_min", "rem_min", "awake_min")},
    "bedtime_h": ("Bedtime (clock hour, 25 = 1 am)", "Sleep"),
    **{key: PREDICTORS[key] for key in ("hrv_ms", "night_hr")},
    "strength_min_24h": ("Strength training time, 24 h before bed (min)", TRAINING),
    "strength_load_24h": ("Strength training load, 24 h before bed", TRAINING),
    "strength_min_72h": ("Strength training time, 72 h before bed (min)", TRAINING),
    "cardio_min_24h": ("Cardio time, 24 h before bed (min)", TRAINING),
    "cardio_min_72h": ("Cardio time, 72 h before bed (min)", TRAINING),
}


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


def daily_table(garmin: GarminData, timezone: str) -> pd.DataFrame:
    """One row per night, indexed by the day you woke up, with the columns of `DAILY_MEASURES`."""
    sleep = garmin.sleep
    if sleep.empty:
        return pd.DataFrame(columns=list(DAILY_MEASURES))
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
    for group, prefix in (("strength", "strength"), ("cardio", "cardio")):
        chosen = acts[acts["group"] == group] if not acts.empty else acts
        ends = chosen["end_utc"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy("datetime64[ns]") if len(chosen) else np.array([], dtype="datetime64[ns]")
        minutes = chosen["minutes"].to_numpy(dtype=float) if len(chosen) else np.array([])
        load = chosen["load"].fillna(0).to_numpy(dtype=float) if len(chosen) else np.array([])
        table[f"{prefix}_min_24h"] = _sum_before(bed, ends, minutes, 24)
        table[f"{prefix}_min_72h"] = _sum_before(bed, ends, minutes, 72)
        if prefix == "strength":
            table["strength_load_24h"] = _sum_before(bed, ends, load, 24)
    return table[list(DAILY_MEASURES)].sort_index()
