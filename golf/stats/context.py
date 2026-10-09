"""What the Garmin watch recorded before each practice session: sleep, overnight vitals, strength and cardio.

Only things that happened *before* the first swing of a session are used, so a measure can be a possible
cause of the result and never a consequence of it.
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from golf.data.garmin import GarminData

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

LOOKBACK_STRENGTH_HOURS = 14 * 24      # "hours since the last strength session" is only given within two weeks
MAX_HOURS_AFTER_WAKING = 24            # the night counts for the session only if it ended within a day before it


def session_context(starts: pd.Series, garmin: GarminData, timezone: str) -> pd.DataFrame:
    """One row of Garmin measures per session.

    `starts` maps a session date to the local time of its first swing (a naive timestamp). The columns are
    the keys of `PREDICTORS`; a value is NaN when the watch has nothing for it.
    """
    sleep, vitals, acts = garmin.sleep, garmin.vitals, garmin.activities
    strength = acts[acts["group"] == "strength"]
    cardio = acts[acts["group"] == "cardio"]
    vitals_by_date = vitals.set_index("date") if not vitals.empty else vitals

    rows = {}
    for day, local_start in starts.items():
        start = pd.Timestamp(local_start).tz_localize(timezone, ambiguous=False, nonexistent="shift_forward").tz_convert("UTC")
        row = {key: np.nan for key in PREDICTORS}
        row["session_hour"] = local_start.hour + local_start.minute / 60.0

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
        rows[day] = row
    return pd.DataFrame.from_dict(rows, orient="index")[list(PREDICTORS)]
