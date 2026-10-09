"""Read FlightScope CSV exports into one tidy table with one row per shot."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Optional

import pandas as pd

from golf.data.columns import METRIC_COLUMNS, standardise_columns
from golf.data.labels import FULL_SWING, LabelParser

if TYPE_CHECKING:
    from golf.config import Config

ENCODING = "windows-1252"
TIME_FORMAT = "%Y-%m-%d; %H-%M-%S"   # e.g. "2026-04-03; 11-09-12"

IDENTITY_COLUMNS = [
    "mode", "session_date", "timestamp", "source_file", "shot_index", "player",
    "raw_club", "club", "variant", "intent", "label", "shot_type",
]
COLUMNS = IDENTITY_COLUMNS + METRIC_COLUMNS


def read_shot_file(path, mode: str, parser: Optional[LabelParser] = None) -> pd.DataFrame:
    """Read one export file. Nothing is dropped; unparsed rows are left marked as such.

    Rows where `club` is missing could not be understood (see `unparsed_labels`),
    and rows where `timestamp` is missing had no readable time.
    """
    parser = parser or LabelParser()
    path = Path(path)
    raw = pd.read_csv(path, encoding=ENCODING, dtype=str)
    for required in ("Time", "Club"):
        if required not in raw.columns:
            raise ValueError(f"{path.name}: missing required column {required!r}")

    parsed = [parser.parse(value) for value in raw["Club"]]

    timestamp = pd.to_datetime(raw["Time"].str.strip(), format=TIME_FORMAT, errors="coerce")
    frame = pd.DataFrame({
        "mode": mode,
        "session_date": timestamp.dt.date,
        "timestamp": timestamp,
        "source_file": path.name,
        "shot_index": pd.to_numeric(raw.get("Index"), errors="coerce").astype("Int64"),
        "player": raw.get("Player"),
        "raw_club": raw["Club"],
        "club": [p.club for p in parsed],
        "variant": [p.variant for p in parsed],
        "intent": pd.array([p.intent for p in parsed], dtype="Int64"),
        "label": [p.label for p in parsed],
        "shot_type": raw.get("Shot Type"),
    })
    return pd.concat([frame, standardise_columns(raw)], axis=1)[COLUMNS]


def load_shots(mode: str, config: "Config | None" = None, directory=None) -> pd.DataFrame:
    """Load every CSV of one mode ('swing', 'pitching' or 'stack') into a single table.

    For swing and pitching only the top level of the data folder is read, so older
    exports can be kept out of the analysis by moving them into a subfolder (e.g.
    'legacy data'). Stack data is read from the folder and from one level below it.
    """
    from golf.config import load_config

    config = config or load_config()
    folder = Path(directory) if directory else config.data_dir(mode)
    if folder is None:
        raise FileNotFoundError(f"No folder is chosen for {mode} data")
    if mode == "stack":
        from golf.data.stack import load_stack

        return load_stack(folder)
    files = sorted(folder.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files found in {folder}")

    parser = config.label_parser()
    frames = [read_shot_file(f, mode, parser) for f in files]
    shots = pd.concat(frames, ignore_index=True)
    return shots.sort_values(["timestamp", "source_file", "shot_index"], kind="stable").reset_index(drop=True)


def unparsed_labels(shots: pd.DataFrame) -> pd.DataFrame:
    """Raw club labels that could not be understood, with how often and where they occur."""
    bad = shots[shots["club"].isna()]
    if bad.empty:
        return pd.DataFrame(columns=["raw_club", "shots", "files"])
    return (
        bad.groupby("raw_club", dropna=False)
        .agg(shots=("raw_club", "size"), files=("source_file", "nunique"))
        .reset_index()
    )
