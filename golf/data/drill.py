"""Drill sessions on disk: one CSV file per session in the drill folder.

A session file is written when the session starts, with every planned shot (the wedge and its target) and empty
result columns. Each entered shot is written into its row at once, so nothing is lost if the browser is closed, and a
session can be continued later. The file is plain CSV and can be opened in a spreadsheet.
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

COLUMNS = ["session", "started", "n", "wedge", "target_m", "target_mph", "slope", "tolerance_mph", "speed_mph", "carry_m", "entered"]
SESSION_ID = re.compile(r"^drill_\d{4}-\d{2}-\d{2}_\d{6}(_\d+)?$")
TEXT = {"session": "object", "started": "object", "wedge": "object", "entered": "object"}      # an empty column must not become numbers
SPEED_RANGE = (10.0, 150.0)       # mph accepted as a club head speed
CARRY_RANGE = (0.0, 250.0)        # m accepted as a carry


def _path(folder: Path, session: str) -> Path:
    if not SESSION_ID.match(session):
        raise ValueError(f"Not a drill session: {session}")
    return Path(folder) / f"{session}.csv"


def _write(path: Path, frame: pd.DataFrame) -> None:
    """Write the file in one go (to a temporary file first), so it is never left half written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(handle)
    try:
        frame[COLUMNS].to_csv(temporary, index=False, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def start_session(folder: Path, plan: List[Dict], tolerance_mph: float, now: Optional[datetime] = None) -> str:
    """Create the session file with the planned shots. Returns the session id."""
    now = now or datetime.now()
    base = f"drill_{now:%Y-%m-%d_%H%M%S}"
    session, suffix = base, 1
    while (Path(folder) / f"{session}.csv").exists():                 # two sessions started within the same second
        suffix += 1
        session = f"{base}_{suffix}"
    frame = pd.DataFrame([
        {"session": session, "started": now.isoformat(timespec="seconds"), "n": row["n"], "wedge": row["wedge"], "target_m": row["target_m"],
         "target_mph": row["target_mph"], "slope": round(row["slope"], 4), "tolerance_mph": tolerance_mph, "speed_mph": None, "carry_m": None, "entered": None}
        for row in plan
    ], columns=COLUMNS)
    _write(_path(folder, session), frame)
    return session


def load_session(folder: Path, session: str) -> pd.DataFrame:
    path = _path(folder, session)
    if not path.is_file():
        raise ValueError(f"No such drill session: {session}")
    return pd.read_csv(path, encoding="utf-8", dtype=TEXT)[COLUMNS]


def record_shot(folder: Path, session: str, n: int, speed_mph: float, carry_m: Optional[float] = None, now: Optional[datetime] = None) -> pd.DataFrame:
    """Enter (or correct) the result of shot `n`. Returns the updated session table."""
    if not SPEED_RANGE[0] <= speed_mph <= SPEED_RANGE[1]:
        raise ValueError(f"A club head speed of {speed_mph:g} mph is not plausible (expected {SPEED_RANGE[0]:g} to {SPEED_RANGE[1]:g})")
    if carry_m is not None and not CARRY_RANGE[0] <= carry_m <= CARRY_RANGE[1]:
        raise ValueError(f"A carry of {carry_m:g} m is not plausible (expected {CARRY_RANGE[0]:g} to {CARRY_RANGE[1]:g})")
    frame = load_session(folder, session)
    rows = frame.index[frame["n"] == n]
    if len(rows) != 1:
        raise ValueError(f"Shot {n} is not part of this session")
    row = rows[0]
    frame.loc[row, "speed_mph"] = speed_mph
    frame.loc[row, "carry_m"] = carry_m
    frame.loc[row, "entered"] = (now or datetime.now()).isoformat(timespec="seconds")
    _write(_path(folder, session), frame)
    return frame


def load_all(folder: Optional[Path]) -> pd.DataFrame:
    """Every shot of every session in the folder (empty if there is none). Files that are not drill sessions are skipped."""
    frames = []
    if folder is not None and Path(folder).is_dir():
        for path in sorted(Path(folder).glob("drill_*.csv")):
            if not SESSION_ID.match(path.stem):
                continue
            try:
                frame = pd.read_csv(path, encoding="utf-8", dtype=TEXT)
            except (OSError, ValueError, pd.errors.ParserError):
                continue
            if set(COLUMNS) <= set(frame.columns):
                frames.append(frame[COLUMNS])
    rows = [row for frame in frames for row in frame.to_dict("records")]
    table = pd.DataFrame(rows, columns=COLUMNS)
    for column in ("speed_mph", "carry_m"):
        table[column] = pd.to_numeric(table[column], errors="coerce")
    return table
