"""What the watch and the scale recorded before each practice session: sleep, overnight vitals, training, body measures.

Only things that happened *before* the first swing of a session are used, so a measure can be a possible
cause of the result and never a consequence of it.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from golf.data.garmin import GarminData
from golf.data.withings import WithingsData

# key -> (title, group in the menus)
PREDICTORS: Dict[str, Tuple[str, str]] = {
    "sleep_h": ("Sleep duration the night before (h)", "Sleep"),
    "sleep_score": ("Sleep score the night before", "Sleep"),
    "deep_min": ("Deep sleep (min)", "Sleep"),
    "rem_min": ("REM sleep (min)", "Sleep"),
    "awake_min": ("Awake during the night (min)", "Sleep"),
    "hrv_ms": ("Overnight heart rate variability (ms)", "Recovery"),
    "night_hr": ("Overnight heart rate (bpm)", "Recovery"),
    "strength_24h": ("Strength sessions in the last 24 h", "Strength training"),
    "strength_72h": ("Strength sessions in the last 72 h", "Strength training"),
    "strength_hours_since": ("Hours since the last strength session", "Strength training"),
    "strength_load_72h": ("Strength training load, last 72 h", "Strength training"),
    "strength_min_72h": ("Strength training time, last 72 h (min)", "Strength training"),
    "cardio_min_48h": ("Cardio time, last 48 h (min)", "Cardio"),
    "cardio_min_7d": ("Cardio time, last 7 days (min)", "Cardio"),
    "hours_awake": ("Hours since waking up", "Timing"),
    "session_hour": ("Time of day of the session (h)", "Timing"),
}

BODY = "Body (scale)"
# No body mass index here: with a fixed height it is the weight again, and would count as a second test of the same thing.
BODY_PREDICTORS: Dict[str, Tuple[str, str]] = {
    "weight_kg": ("Weight, latest weighing (kg)", BODY),
    "fat_kg": ("Fat mass, latest weighing (kg)", BODY),
    "fat_pct": ("Body fat, latest weighing (%)", BODY),
    "muscle_kg": ("Muscle mass, latest weighing (kg)", BODY),
    "hydration_kg": ("Water, latest weighing (kg)", BODY),
}
ALL_PREDICTORS: Dict[str, Tuple[str, str]] = {**PREDICTORS, **BODY_PREDICTORS}

LOOKBACK_STRENGTH_HOURS = 14 * 24      # "hours since the last strength session" is only given within two weeks
MAX_HOURS_AFTER_WAKING = 24            # the night counts for the session only if it ended within a day before it
MAX_WEIGHING_AGE_DAYS = 14             # the body measures count only from a weighing at most this many days old


def available_predictors(garmin: Optional[GarminData], withings: Optional[WithingsData]) -> Dict[str, Tuple[str, str]]:
    """The measures that can be related to a result with the data that is loaded."""
    chosen: Dict[str, Tuple[str, str]] = {}
    if garmin is not None:
        chosen.update(PREDICTORS)
    if withings is not None:
        chosen.update(BODY_PREDICTORS)
    return chosen


def session_context(starts: pd.Series, garmin: Optional[GarminData], timezone: str, withings: Optional[WithingsData] = None) -> pd.DataFrame:
    """One row of health measures per session.

    `starts` maps a session date to the local time of its first swing (a naive timestamp). The columns are
    the keys of `ALL_PREDICTORS`; a value is NaN when the watch or the scale has nothing for it (or none is loaded).
    The body measures come from the latest weighing on or before the day of the session, if it is at most
    `MAX_WEIGHING_AGE_DAYS` old.
    """
    rows = {}
    for day, local_start in starts.items():
        row = {key: np.nan for key in ALL_PREDICTORS}
        row["session_hour"] = local_start.hour + local_start.minute / 60.0
        if garmin is not None:
            row.update(_garmin_row(garmin, pd.Timestamp(local_start), timezone))
        if withings is not None:
            row.update(_body_row(withings, pd.Timestamp(day)))
        rows[day] = row
    return pd.DataFrame.from_dict(rows, orient="index")[list(ALL_PREDICTORS)]


def _body_row(withings: WithingsData, day: pd.Timestamp) -> Dict[str, float]:
    body = withings.body
    dates = pd.to_datetime(body["date"])
    before = dates[dates <= day.normalize()]
    if before.empty or (day.normalize() - before.max()).days > MAX_WEIGHING_AGE_DAYS:
        return {}
    latest = body.loc[before.idxmax()]
    return {
        "weight_kg": latest["weight_kg"], "fat_kg": latest["fat_kg"],
        "fat_pct": latest["fat_kg"] / latest["weight_kg"] * 100.0,
        "muscle_kg": latest["muscle_kg"], "hydration_kg": latest["hydration_kg"],
    }


def _garmin_row(garmin: GarminData, local_start: pd.Timestamp, timezone: str) -> Dict[str, float]:
    sleep, vitals, acts = garmin.sleep, garmin.vitals, garmin.activities
    strength = acts[acts["group"] == "strength"]
    cardio = acts[acts["group"] == "cardio"]
    vitals_by_date = vitals.set_index("date") if not vitals.empty else vitals

    start = local_start.tz_localize(timezone, ambiguous=False, nonexistent="shift_forward").tz_convert("UTC")
    row: Dict[str, float] = {}

    if not sleep.empty:
        before = sleep[sleep["end_utc"] <= start]
        if not before.empty:
            night = before.iloc[-1]
            hours = (start - night["end_utc"]).total_seconds() / 3600.0
            if hours <= MAX_HOURS_AFTER_WAKING:
                row.update(sleep_h=night["asleep_h"], sleep_score=night["score"], deep_min=night["deep_min"],
                           rem_min=night["rem_min"], awake_min=night["awake_min"], hours_awake=hours)
                if not vitals.empty and night["date"] in vitals_by_date.index:
                    row.update(hrv_ms=vitals_by_date.loc[night["date"], "hrv_ms"],
                               night_hr=vitals_by_date.loc[night["date"], "night_hr"])

    if not strength.empty:
        done = strength[strength["end_utc"] <= start]
        hours_ago = (start - done["end_utc"]).dt.total_seconds() / 3600.0
        last72 = done[hours_ago <= 72]
        row.update(
            strength_24h=float((hours_ago <= 24).sum()),
            strength_72h=float(len(last72)),
            strength_load_72h=float(last72["load"].fillna(0).sum()),
            strength_min_72h=float(last72["minutes"].sum()),
        )
        if len(hours_ago) and hours_ago.min() <= LOOKBACK_STRENGTH_HOURS:
            row["strength_hours_since"] = float(hours_ago.min())
    else:
        row.update(strength_24h=0.0, strength_72h=0.0, strength_load_72h=0.0, strength_min_72h=0.0)

    done_cardio = cardio[cardio["end_utc"] <= start] if not cardio.empty else cardio
    for key, hours in (("cardio_min_48h", 48), ("cardio_min_7d", 7 * 24)):
        recent = done_cardio[(start - done_cardio["end_utc"]).dt.total_seconds() / 3600.0 <= hours] if len(done_cardio) else done_cardio
        row[key] = float(recent["minutes"].sum()) if len(recent) else 0.0
    return row
