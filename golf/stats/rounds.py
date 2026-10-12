"""Statistics of full 18-hole rounds: score, fairways, greens in regulation, putting, penalties.

Everything is calculated from the strokes, putts, tee shot outcome and penalties of each hole, and the par of
each hole. A statistic is only given for a round when enough of its holes have the data it needs (the app does not
record every putt or every fairway), and it is calculated on the holes that have it, never on guessed values.

Definitions
- Fairway: tee shots on par 4 and par 5 holes that have an outcome; "hit" is a hit fairway.
- Green in regulation (GIR): strokes minus putts at most par minus 2 (the ball was on the green with two putts
  to spare). Penalty strokes count as strokes, so a hole with a penalty is judged more strictly.
- Scrambling: of the holes without a green in regulation, the share finished in par or better.
- Penalties: a hole without a recorded penalty count is taken as having none.
- Differential: (strokes - course rating) * 113 / slope, the number the handicap system compares.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

MIN_FAIRWAY_HOLES = 6          # fairway tee shots a round needs for its fairway percentage
MIN_GREEN_HOLES = 9            # holes with putts a round needs for green and putting statistics
MIN_SCRAMBLE_CHANCES = 4       # missed greens a round needs for its scrambling percentage

# key -> (title, how it is shown); the measures that can be followed round by round
ROUND_MEASURES: Dict[str, Tuple[str, str]] = {
    "strokes": ("Strokes", "{:.0f}"),
    "to_par": ("Strokes compared with par", "{:+.0f}"),
    "differential": ("Score differential", "{:.1f}"),
    "fir_pct": ("Fairways hit (%)", "{:.0f}"),
    "gir_pct": ("Greens in regulation (%)", "{:.0f}"),
    "putts_per_hole": ("Putts per hole", "{:.2f}"),
    "putts_18": ("Putts per round (all 18 holes recorded)", "{:.0f}"),
    "three_putt_pct": ("Three putts or more (% of holes)", "{:.0f}"),
    "scrambling_pct": ("Scrambling (%)", "{:.0f}"),
    "penalty_strokes": ("Penalty strokes", "{:.0f}"),
}


def _holes_with_par(holes: pd.DataFrame) -> pd.DataFrame:
    """Holes plus the facts every statistic needs."""
    h = holes.copy()
    h["penalties"] = h["penalties"].fillna(0)
    h["has_putts"] = h["putts"].notna()
    h["fairway_shot"] = h["fairway"].notna() & ~(h["par"] <= 3)           # par 4 and 5 (and holes of unknown par that have an outcome)
    h["gir_known"] = h["has_putts"] & h["par"].notna()
    h["gir"] = h["gir_known"] & ((h["strokes"] - h["putts"]) <= (h["par"] - 2))
    h["missed_green"] = h["gir_known"] & ~h["gir"]
    h["scrambled"] = h["missed_green"] & (h["strokes"] <= h["par"])
    h["three_putt"] = h["has_putts"] & (h["putts"] >= 3)
    h["to_par"] = h["strokes"] - h["par"]
    h["fairway_hit"] = h["fairway_shot"] & (h["fairway"] == "HIT")
    h["putts_known"] = h["putts"].where(h["has_putts"], 0.0)
    h["birdie_or_better"] = h["to_par"] < 0
    h["par_score"] = h["to_par"] == 0
    h["bogey"] = h["to_par"] == 1
    h["double_or_worse"] = h["to_par"] >= 2
    return h


def _pct(part: float, whole: float, minimum: int) -> float:
    return 100.0 * part / whole if whole >= minimum else np.nan


def round_stats(rounds: pd.DataFrame, holes: pd.DataFrame) -> pd.DataFrame:
    """One row per round with its score and statistics (NaN where the round has too little data)."""
    h = _holes_with_par(holes)
    by = h.groupby("round_id")
    agg = pd.DataFrame({
        "fw_holes": by["fairway_shot"].sum(),
        "fw_hit": by["fairway_hit"].sum(),
        "putt_holes": by["has_putts"].sum(),
        "putts": by["putts_known"].sum(),
        "three_putts": by["three_putt"].sum(),
        "gir_holes": by["gir_known"].sum(),
        "gir": by["gir"].sum(),
        "missed_green": by["missed_green"].sum(),
        "scrambled": by["scrambled"].sum(),
        "penalty_strokes": by["penalties"].sum(),
        "birdies_or_better": by["birdie_or_better"].sum(),
        "pars": by["par_score"].sum(),
        "bogeys": by["bogey"].sum(),
        "doubles_or_worse": by["double_or_worse"].sum(),
    })
    stats = rounds.set_index("round_id").join(agg)
    stats["to_par"] = stats["strokes"] - stats["par"]
    stats["differential"] = (stats["strokes"] - stats["rating"]) * 113.0 / stats["slope"]
    stats["fir_pct"] = [_pct(a, b, MIN_FAIRWAY_HOLES) for a, b in zip(stats["fw_hit"], stats["fw_holes"])]
    stats["gir_pct"] = [_pct(a, b, MIN_GREEN_HOLES) for a, b in zip(stats["gir"], stats["gir_holes"])]
    stats["putts_per_hole"] = [p / n if n >= MIN_GREEN_HOLES else np.nan for p, n in zip(stats["putts"], stats["putt_holes"])]
    stats["putts_18"] = [p if n == 18 else np.nan for p, n in zip(stats["putts"], stats["putt_holes"])]
    stats["three_putt_pct"] = [_pct(a, b, MIN_GREEN_HOLES) for a, b in zip(stats["three_putts"], stats["putt_holes"])]
    stats["scrambling_pct"] = [_pct(a, b, MIN_SCRAMBLE_CHANCES) for a, b in zip(stats["scrambled"], stats["missed_green"])]
    stats = stats.reset_index()
    return stats.sort_values("start_utc").reset_index(drop=True)


# --- the overview table: the same statistics for a set of rounds ----------------------------------------------

SUMMARY_ROWS: List[Tuple[str, str, str]] = [
    ("rounds", "Rounds", "{:.0f}"),
    ("strokes", "Strokes per round", "{:.1f}"),
    ("to_par", "Strokes compared with par", "{:+.1f}"),
    ("differential", "Score differential", "{:.1f}"),
    ("fir_pct", "Fairways hit (%)", "{:.0f}"),
    ("fir_left", "Fairways missed left (%)", "{:.0f}"),
    ("fir_right", "Fairways missed right (%)", "{:.0f}"),
    ("gir_pct", "Greens in regulation (%)", "{:.0f}"),
    ("scrambling_pct", "Scrambling (%)", "{:.0f}"),
    ("putts_per_hole", "Putts per hole", "{:.2f}"),
    ("putts_18", "Putts per 18 holes", "{:.1f}"),
    ("three_putt_pct", "Three putts or more (% of holes)", "{:.1f}"),
    ("penalty_strokes", "Penalty strokes per round", "{:.2f}"),
    ("birdies_or_better", "Birdies or better per round", "{:.1f}"),
    ("pars", "Pars per round", "{:.1f}"),
    ("bogeys", "Bogeys per round", "{:.1f}"),
    ("doubles_or_worse", "Double bogeys or worse per round", "{:.1f}"),
    ("par3", "Par 3 holes, strokes compared with par", "{:+.2f}"),
    ("par4", "Par 4 holes, strokes compared with par", "{:+.2f}"),
    ("par5", "Par 5 holes, strokes compared with par", "{:+.2f}"),
]


def summarise(rounds: pd.DataFrame, holes: pd.DataFrame, round_ids) -> Dict[str, Optional[float]]:
    """The statistics of a set of rounds, each calculated over all the holes (not as the mean of per-round values)."""
    ids = list(round_ids)
    out: Dict[str, Optional[float]] = {key: None for key, _, _ in SUMMARY_ROWS}
    out["rounds"] = len(ids)
    if not ids:
        return out
    chosen = rounds[rounds["round_id"].isin(ids)]
    h = _holes_with_par(holes[holes["round_id"].isin(ids)])
    n = len(chosen)
    out["strokes"] = float(chosen["strokes"].mean())
    out["to_par"] = float((chosen["strokes"] - chosen["par"]).mean()) if chosen["par"].notna().any() else None
    out["differential"] = float(((chosen["strokes"] - chosen["rating"]) * 113.0 / chosen["slope"]).mean())

    fw = h[h["fairway_shot"]]
    if len(fw):
        out["fir_pct"] = 100.0 * (fw["fairway"] == "HIT").mean()
        out["fir_left"] = 100.0 * (fw["fairway"] == "LEFT").mean()
        out["fir_right"] = 100.0 * (fw["fairway"] == "RIGHT").mean()
    if h["gir_known"].sum():
        out["gir_pct"] = 100.0 * h["gir"].sum() / h["gir_known"].sum()
    if h["missed_green"].sum():
        out["scrambling_pct"] = 100.0 * h["scrambled"].sum() / h["missed_green"].sum()
    if h["has_putts"].sum():
        putts = h.loc[h["has_putts"], "putts"]
        out["putts_per_hole"] = float(putts.mean())
        out["putts_18"] = 18.0 * float(putts.mean())
        out["three_putt_pct"] = 100.0 * h["three_putt"].sum() / h["has_putts"].sum()
    out["penalty_strokes"] = float(h["penalties"].sum() / n)
    out["birdies_or_better"] = float(h["birdie_or_better"].sum() / n)
    out["pars"] = float(h["par_score"].sum() / n)
    out["bogeys"] = float(h["bogey"].sum() / n)
    out["doubles_or_worse"] = float(h["double_or_worse"].sum() / n)
    for par in (3, 4, 5):
        on_par = h[h["par"] == par]
        if len(on_par):
            out[f"par{par}"] = float(on_par["to_par"].mean())
    return out


def rolling_by_round(values: pd.Series, windows=(5, 10), minimum=(3, 5)) -> pd.DataFrame:
    """Averages of the last `windows[0]` and `windows[1]` rounds that have a value, one row per round (in the order given).

    With one window only the short average is calculated (the long one stays empty), for sources with few rounds.
    A round without a value has no average of its own; the average of the rounds before it is not carried over.
    """
    present = values.dropna()
    out = pd.DataFrame(index=values.index, columns=["short", "long"], dtype=float)
    out.loc[present.index, "short"] = present.rolling(windows[0], min_periods=minimum[0]).mean()
    if len(windows) > 1:
        out.loc[present.index, "long"] = present.rolling(windows[1], min_periods=minimum[1]).mean()
    return out
