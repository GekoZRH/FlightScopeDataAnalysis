"""Stack (speed training) sessions: swings with weighted clubs.

The simulator writes the same kind of CSV file as for other practice, but the
`Club` column holds the weight of the club, for example `235g`, and only the
club speed and the two plane angles are recorded.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

from golf.data.columns import standardise_columns

ENCODING = "windows-1252"
TIME_FORMAT = "%Y-%m-%d; %H-%M-%S"

_WEIGHT = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*g\s*$", re.IGNORECASE)

STACK_COLUMNS = [
    "mode", "session_date", "timestamp", "source_file", "shot_index", "player",
    "raw_club", "weight_g", "label", "v_plane_deg", "h_plane_deg", "club_speed_mph",
]


def parse_weight(text) -> float:
    """Weight in grams from a `Club` value such as '235g'; NaN if it is not a weight."""
    if text is None or (isinstance(text, float) and text != text):
        return float("nan")
    match = _WEIGHT.match(str(text))
    return float(match.group(1).replace(",", ".")) if match else float("nan")


def stack_files(folder: Path) -> List[Path]:
    """The CSV files of a stack data folder: directly in it, or one folder level below it.

    The training app stores one folder per session, so both layouts are read.
    """
    folder = Path(folder)
    return sorted(folder.glob("*.csv")) + sorted(folder.glob("*/*.csv"))


def read_stack_file(path) -> pd.DataFrame:
    """Read one stack CSV file. Rows are kept even when the weight cannot be read (weight_g is then NaN)."""
    path = Path(path)
    raw = pd.read_csv(path, encoding=ENCODING, dtype=str)
    for required in ("Time", "Club", "Club Speed [mph]"):
        if required not in raw.columns:
            raise ValueError(f"{path.name}: missing required column {required!r}")

    timestamp = pd.to_datetime(raw["Time"].str.strip(), format=TIME_FORMAT, errors="coerce")
    weight = raw["Club"].map(parse_weight)
    measures = standardise_columns(raw)
    frame = pd.DataFrame({
        "mode": "stack",
        "session_date": timestamp.dt.date,
        "timestamp": timestamp,
        "source_file": path.name,
        "shot_index": pd.to_numeric(raw.get("Index"), errors="coerce").astype("Int64"),
        "player": raw.get("Player"),
        "raw_club": raw["Club"],
        "weight_g": weight,
        "label": [f"{w:g} g" if np.isfinite(w) else None for w in weight],
        "v_plane_deg": measures["v_plane_deg"],
        "h_plane_deg": measures["h_plane_deg"],
        "club_speed_mph": measures["club_speed_mph"],
    })
    return frame[STACK_COLUMNS]


def load_stack(folder) -> pd.DataFrame:
    """Load every stack session of a folder into one table, one row per swing, in time order."""
    folder = Path(folder)
    files = stack_files(folder)
    if not files:
        raise FileNotFoundError(f"No CSV files found in {folder}")
    shots = pd.concat([read_stack_file(f) for f in files], ignore_index=True)
    return shots.sort_values(["timestamp", "source_file", "shot_index"], kind="stable").reset_index(drop=True)


def unreadable_weights(shots: pd.DataFrame) -> pd.DataFrame:
    """Club values that are not a weight such as '235g', with how often they occur."""
    bad = shots[shots["weight_g"].isna()]
    if bad.empty:
        return pd.DataFrame(columns=["raw_club", "shots", "files"])
    return (
        bad.groupby("raw_club", dropna=False)
        .agg(shots=("raw_club", "size"), files=("source_file", "nunique"))
        .reset_index()
    )
