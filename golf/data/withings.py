"""Withings scale data from the official Health Mate "export your data" folder.

Two files are read:

- `weight.csv`  one row per weighing: weight, fat mass, bone mass, muscle mass and water (hydration), all in kg
- `height.csv`  your height in metres, used for the body mass index

The other files of the export (account, devices, ECG signals, `other.csv`, which only repeats the same values as
whole-number percentages) are not read. The export is read-only input: nothing in it is changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import pandas as pd

WEIGHT_COLUMNS = {
    "Weight (kg)": "weight_kg", "Fat mass (kg)": "fat_kg", "Bone mass (kg)": "bone_kg",
    "Muscle mass (kg)": "muscle_kg", "Hydration (kg)": "hydration_kg",
}
BODY_COLUMNS = ["date"] + list(WEIGHT_COLUMNS.values()) + ["bmi"]


@dataclass(frozen=True)
class WithingsData:
    folder: Path
    body: pd.DataFrame          # one row per day, see BODY_COLUMNS


def find_weight_file(folder: Path) -> Path:
    """The `weight.csv` of an export (the folder may also hold it one level down)."""
    folder = Path(folder)
    for candidate in (folder / "weight.csv", *sorted(folder.glob("*/weight.csv"))):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"No Withings export found in {folder} (expected the weight.csv of the Health Mate data export)")


def load_withings(folder) -> WithingsData:
    """Read the weighings. When there are several on a day the first (the morning one) is used.

    `date` is the calendar day of the weighing; the times in the export are taken as they are. A weighing
    without body composition (a plain scale reading) keeps its weight and has no fat, muscle or water.
    """
    weight_file = find_weight_file(Path(folder))
    raw = pd.read_csv(weight_file)
    if "Date" not in raw.columns or "Weight (kg)" not in raw.columns:
        raise ValueError(f"{weight_file} does not look like a Withings weight file (no Date and Weight (kg) columns)")
    frame = raw.rename(columns=WEIGHT_COLUMNS)
    frame["time"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["time"])
    for column in WEIGHT_COLUMNS.values():
        frame[column] = pd.to_numeric(frame[column], errors="coerce") if column in frame else float("nan")
    frame = frame.dropna(subset=["weight_kg"]).sort_values("time")
    frame["date"] = frame["time"].dt.date
    body = frame.drop_duplicates("date", keep="first")[["date"] + list(WEIGHT_COLUMNS.values())].reset_index(drop=True)

    if body.empty:
        raise ValueError(f"The Withings export in {folder} holds no weighings")
    body["bmi"] = _bmi(body, _load_heights(weight_file.parent / "height.csv"))
    return WithingsData(folder=Path(folder), body=body[BODY_COLUMNS])


def _load_heights(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=["time", "height_m"])
    raw = pd.read_csv(path)
    if "Date" not in raw.columns or "Height (m)" not in raw.columns:
        return pd.DataFrame(columns=["time", "height_m"])
    heights = pd.DataFrame({"time": pd.to_datetime(raw["Date"], errors="coerce"), "height_m": pd.to_numeric(raw["Height (m)"], errors="coerce")})
    return heights.dropna().sort_values("time")


def _bmi(body: pd.DataFrame, heights: pd.DataFrame) -> pd.Series:
    """Body mass index with the latest height recorded up to the weighing (the first height for earlier days)."""
    if heights.empty:
        return pd.Series(float("nan"), index=body.index)
    day = pd.to_datetime(body["date"])
    height = pd.merge_asof(pd.DataFrame({"day": day}).reset_index().sort_values("day"), heights, left_on="day", right_on="time", direction="backward")
    height = height.set_index("index")["height_m"].reindex(body.index).fillna(heights["height_m"].iloc[0])
    return body["weight_kg"] / height ** 2


def describe_withings(data: WithingsData) -> Dict:
    """Counts for the dashboard's data panel."""
    body = data.body
    return {
        "weighings": int(len(body)),
        "with_composition": int(body["fat_kg"].notna().sum()),
        "first": str(body["date"].min()), "last": str(body["date"].max()),
    }
