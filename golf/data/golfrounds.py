"""Golf rounds from the Garmin data export (`DI_CONNECT/DI-GOLF`): the scorecards you kept on the watch or in the app.

- `Golf-SCORECARD.json` has every round with its strokes, tee box (course rating and slope) and, per hole, the
  strokes, the putts, where the tee shot went (fairway hit, left or right) and the penalty strokes.
- `Golf-SCORECARD_RAWDATA-<round id>.fit` (one per round) also has the course name and, per hole, the par and the
  stroke index, which the JSON does not. The numbers of the messages in it are not documented by Garmin: they were
  read off the files and checked against the scorecards (hole 193: number, par, stroke index; course 190: name).

Only full rounds of 18 holes that count for your statistics are used. The export is read-only input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from golf.data.fit import read_fit

SCORECARD_FILE = "Golf-SCORECARD.json"
COURSE_MESSAGE, HOLE_MESSAGE = 190, 193           # FIT messages: the course, one hole (number, par, stroke index)

ROUND_COLUMNS = ["round_id", "start_utc", "date", "course", "tee", "rating", "slope", "strokes", "par"]
HOLE_COLUMNS = ["round_id", "hole", "par", "stroke_index", "strokes", "putts", "fairway", "penalties"]


@dataclass(frozen=True)
class GolfRounds:
    folder: Path
    rounds: pd.DataFrame        # one row per full round, see ROUND_COLUMNS
    holes: pd.DataFrame         # one row per hole of those rounds, see HOLE_COLUMNS


def find_golf_folder(folder: Path) -> Optional[Path]:
    """The `DI-GOLF` folder of an export (the extracted export, its DI_CONNECT folder, or the folder itself), or None."""
    folder = Path(folder)
    for candidate in (folder, folder / "DI-GOLF", folder / "DI_CONNECT" / "DI-GOLF"):
        if (candidate / SCORECARD_FILE).is_file():
            return candidate
    return None


def _fit_details(path: Path) -> Dict:
    """Course name and per-hole par and stroke index of a round's raw file ({} if there is none or it cannot be read)."""
    if not path.is_file():
        return {}
    try:
        messages = read_fit(path)
    except (ValueError, OSError, IndexError):
        return {}
    details: Dict = {"course": None, "holes": {}}
    for message in messages:
        if message.number == COURSE_MESSAGE and isinstance(message.fields.get(1), str):
            details["course"] = message.fields[1].strip() or None
        elif message.number == HOLE_MESSAGE and isinstance(message.fields.get(0), int):
            par, index = message.fields.get(2), message.fields.get(3)
            details["holes"][message.fields[0]] = (par if isinstance(par, int) and 3 <= par <= 6 else None,
                                                   index if isinstance(index, int) and 1 <= index <= 18 else None)
    return details


def load_golf_rounds(folder, timezone: str) -> GolfRounds:
    """Read the full 18-hole rounds of a Garmin export. Raises FileNotFoundError if the export has no golf data."""
    golf = find_golf_folder(Path(folder))
    if golf is None:
        raise FileNotFoundError(f"No golf scorecards ({SCORECARD_FILE}) found in {folder}")
    with open(golf / SCORECARD_FILE, encoding="utf-8") as handle:
        scorecards = json.load(handle).get("data", [])

    rounds, holes = [], []
    for card in scorecards:
        if card.get("holesCompleted") != 18 or card.get("excludeFromStats") or card.get("inProgress") or not card.get("startTime"):
            continue
        start = pd.Timestamp(card["startTime"])
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        details = _fit_details(golf / f"Golf-SCORECARD_RAWDATA-{card['id']}.fit")
        fit_holes = details.get("holes", {})
        card_holes = card.get("holes", [])
        pars = [fit_holes.get(h["number"], (None, None))[0] for h in card_holes]
        rounds.append({
            "round_id": card["id"], "start_utc": start, "date": start.tz_convert(timezone).date(),
            "course": details.get("course") or f"course {card.get('courseGlobalId', '?')}",
            "tee": card.get("teeBox"), "rating": card.get("teeBoxRating"), "slope": card.get("teeBoxSlope"),
            "strokes": card.get("strokes"),
            "par": float(sum(pars)) if pars and all(p is not None for p in pars) else np.nan,
        })
        for h, par in zip(card_holes, pars):
            holes.append({
                "round_id": card["id"], "hole": h["number"], "par": np.nan if par is None else par,
                "stroke_index": np.nan if fit_holes.get(h["number"], (None, None))[1] is None else fit_holes[h["number"]][1],
                "strokes": h.get("strokes"), "putts": h.get("putts", np.nan), "fairway": h.get("fairwayShotOutcome"),
                "penalties": h.get("penalties", np.nan),
            })
    round_table = pd.DataFrame(rounds, columns=ROUND_COLUMNS)
    hole_table = pd.DataFrame(holes, columns=HOLE_COLUMNS)
    for column in ("rating", "slope", "strokes"):
        round_table[column] = pd.to_numeric(round_table[column], errors="coerce")
    for column in ("hole", "par", "stroke_index", "strokes", "putts", "penalties"):
        hole_table[column] = pd.to_numeric(hole_table[column], errors="coerce")
    round_table = round_table.sort_values("start_utc").reset_index(drop=True)
    return GolfRounds(folder=golf, rounds=round_table, holes=hole_table)


def describe_golf_rounds(data: GolfRounds) -> Dict:
    rounds = data.rounds
    return {
        "rounds": int(len(rounds)),
        "first": str(rounds["date"].min()) if len(rounds) else "", "last": str(rounds["date"].max()) if len(rounds) else "",
    }
