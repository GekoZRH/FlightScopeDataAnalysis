"""Practice sessions: listing them and leaving some out of the analysis.

A session is one practice day. The dashboard lets you choose which sessions
take part; everything (reviews, progress, cards) then uses only those.
"""

from __future__ import annotations

from typing import Dict, Iterable, List

import pandas as pd


def session_table(shots: pd.DataFrame) -> List[Dict]:
    """One row per session, newest first: date, shots, clubs used and the file(s) it came from."""
    rows = []
    for day, group in shots.groupby("session_date"):
        rows.append({
            "date": str(day),
            "shots": int(len(group)),
            "clubs": int(group["label"].nunique()),
            "files": sorted(group["source_file"].unique().tolist()),
        })
    return sorted(rows, key=lambda row: row["date"], reverse=True)


def include_sessions(shots: pd.DataFrame, excluded: Iterable[str]) -> pd.DataFrame:
    """The shots of all sessions except the excluded dates (given as 'YYYY-MM-DD')."""
    excluded = set(excluded)
    if not excluded:
        return shots
    return shots[~shots["session_date"].astype(str).isin(excluded)]
