"""Garmin watch data from the official "export your data" ZIP: sleep, overnight vitals and activities.

Only three parts of the export are read, all under `DI_CONNECT`:

- `DI-Connect-Wellness/*_sleepData.json`        one record per night (stages and sleep score)
- `DI-Connect-Wellness/*_healthStatusData.json` overnight heart rate variability and heart rate
- `DI-Connect-Fitness/*_summarizedActivities.json`  one record per activity (strength, running ...)

The export is read-only input: nothing in it is changed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

# Activities counted as cardio. Walking, golf and the rest are not.
CARDIO_TYPES = {
    "running", "treadmill_running", "trail_running", "indoor_cardio", "cycling", "indoor_cycling",
    "lap_swimming", "open_water_swimming", "hiking", "elliptical", "stair_climbing", "rowing", "indoor_rowing",
}
STRENGTH_TYPES = {"strength_training"}

SLEEP_COLUMNS = ["date", "start_utc", "end_utc", "asleep_h", "deep_min", "light_min", "rem_min", "awake_min", "score"]
VITAL_COLUMNS = ["date", "hrv_ms", "night_hr"]
ACTIVITY_COLUMNS = ["type", "group", "start_utc", "end_utc", "minutes", "avg_hr", "load", "sets", "reps"]


@dataclass(frozen=True)
class GarminData:
    folder: Path
    sleep: pd.DataFrame
    vitals: pd.DataFrame
    activities: pd.DataFrame


def find_export_folders(folder: Path) -> Dict[str, Path]:
    """Locate the wellness and fitness folders of an export.

    `folder` may be the extracted export, its `DI_CONNECT` folder, or a folder that holds the two
    `DI-Connect-*` folders directly.
    """
    folder = Path(folder)
    found: Dict[str, Path] = {}
    for key, name in (("wellness", "DI-Connect-Wellness"), ("fitness", "DI-Connect-Fitness")):
        for candidate in (folder / name, folder / "DI_CONNECT" / name):
            if candidate.is_dir():
                found[key] = candidate
                break
    if not found:
        raise FileNotFoundError(
            f"No Garmin export found in {folder} (expected a DI_CONNECT folder with DI-Connect-Wellness and DI-Connect-Fitness)"
        )
    return found


def _read_json_files(folder: Path, pattern: str) -> Iterable:
    for path in sorted(folder.glob(pattern)):
        with open(path, encoding="utf-8") as handle:
            yield json.load(handle)


def _utc(text: Optional[str]) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC") if text else pd.NaT


def load_sleep(wellness: Path) -> pd.DataFrame:
    """One row per night. `date` is the day you woke up on."""
    rows = []
    for records in _read_json_files(wellness, "*_sleepData.json"):
        for r in records:
            if "sleepEndTimestampGMT" not in r or "calendarDate" not in r:
                continue
            deep, light, rem, awake = (float(r.get(k) or 0) for k in
                                       ("deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds", "awakeSleepSeconds"))
            rows.append({
                "date": pd.Timestamp(r["calendarDate"]).date(),
                "start_utc": _utc(r.get("sleepStartTimestampGMT")),
                "end_utc": _utc(r.get("sleepEndTimestampGMT")),
                "asleep_h": (deep + light + rem) / 3600.0,
                "deep_min": deep / 60.0, "light_min": light / 60.0, "rem_min": rem / 60.0, "awake_min": awake / 60.0,
                "score": (r.get("sleepScores") or {}).get("overallScore"),
            })
    frame = pd.DataFrame(rows, columns=SLEEP_COLUMNS)
    if frame.empty:
        return frame
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    # the export files overlap a little: keep one record per night (the one that ends last)
    frame = frame.sort_values(["date", "end_utc"]).drop_duplicates("date", keep="last")
    return frame.sort_values("end_utc").reset_index(drop=True)


def load_vitals(wellness: Path) -> pd.DataFrame:
    """Overnight heart rate variability and heart rate, one row per morning (`date` is the day you woke up)."""
    rows = []
    for records in _read_json_files(wellness, "*_healthStatusData.json"):
        for r in records:
            if "calendarDate" not in r:
                continue
            values = {m.get("type"): m.get("value") for m in r.get("metrics", [])}
            rows.append({"date": pd.Timestamp(r["calendarDate"]).date(), "hrv_ms": values.get("HRV"), "night_hr": values.get("HR")})
    frame = pd.DataFrame(rows, columns=VITAL_COLUMNS)
    for column in ("hrv_ms", "night_hr"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def load_activities(fitness: Path) -> pd.DataFrame:
    """One row per recorded activity, with start and end in UTC."""
    rows = []
    for blocks in _read_json_files(fitness, "*_summarizedActivities.json"):
        for block in blocks:
            for a in block.get("summarizedActivitiesExport", []):
                if a.get("startTimeGmt") is None:
                    continue
                kind = str(a.get("activityType") or "")
                start = pd.Timestamp(float(a["startTimeGmt"]), unit="ms", tz="UTC")
                minutes = float(a.get("duration") or 0) / 60000.0
                rows.append({
                    "type": kind,
                    "group": "strength" if kind in STRENGTH_TYPES else ("cardio" if kind in CARDIO_TYPES else "other"),
                    "start_utc": start, "end_utc": start + pd.Timedelta(minutes=minutes), "minutes": minutes,
                    "avg_hr": a.get("avgHr"), "load": a.get("activityTrainingLoad"),
                    "sets": a.get("totalSets"), "reps": a.get("totalReps"),
                })
    frame = pd.DataFrame(rows, columns=ACTIVITY_COLUMNS)
    for column in ("avg_hr", "load", "sets", "reps"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.drop_duplicates(["type", "start_utc"]).sort_values("start_utc").reset_index(drop=True)


def load_garmin(folder) -> GarminData:
    """Read the sleep, vitals and activities of a Garmin export. Missing parts give empty tables."""
    folders = find_export_folders(Path(folder))
    empty = pd.DataFrame
    sleep = load_sleep(folders["wellness"]) if "wellness" in folders else empty(columns=SLEEP_COLUMNS)
    vitals = load_vitals(folders["wellness"]) if "wellness" in folders else empty(columns=VITAL_COLUMNS)
    activities = load_activities(folders["fitness"]) if "fitness" in folders else empty(columns=ACTIVITY_COLUMNS)
    if sleep.empty and vitals.empty and activities.empty:
        raise FileNotFoundError(f"The Garmin export in {folder} holds no sleep, heart rate or activity data")
    return GarminData(folder=Path(folder), sleep=sleep, vitals=vitals, activities=activities)


def describe_garmin(data: GarminData) -> Dict:
    """Counts for the dashboard's data panel."""
    activities = data.activities
    return {
        "nights": int(len(data.sleep)),
        "mornings_with_hrv": int(data.vitals["hrv_ms"].notna().sum()) if not data.vitals.empty else 0,
        "strength": int((activities["group"] == "strength").sum()) if not activities.empty else 0,
        "cardio": int((activities["group"] == "cardio").sum()) if not activities.empty else 0,
        "first": str(data.sleep["date"].min()) if not data.sleep.empty else "",
        "last": str(data.sleep["date"].max()) if not data.sleep.empty else "",
    }
