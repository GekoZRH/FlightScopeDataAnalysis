"""Select and order shots according to the bag (golf.toml and the dashboard choices)."""

from __future__ import annotations

from typing import Dict, List

import pandas as pd

from golf.config import BagSpec
from golf.data.labels import FULL_SWING
from golf.ordering import entry_key


def club_variant(shots: pd.DataFrame) -> pd.Series:
    """'club variant' for every shot, e.g. '8i 245' ('' if the club was not understood)."""
    return (shots["club"].fillna("") + " " + shots["variant"].fillna("")).str.strip()


def select_bag(shots: pd.DataFrame, spec: BagSpec, *, full_swing_first: bool = False) -> pd.DataFrame:
    """Keep only the configured clubs and intents, sorted in bag order.

    A bag entry such as '8i 241' matches on club + variant; the swing intent is
    filtered separately through `spec.intents`, or through `spec.pairs` when the
    selection is per club and intent. Rows without a recorded carry are kept,
    since they still carry information such as club speed. With
    `full_swing_first`, the intents of one club are ordered full swing, 11, 10, 9
    instead of 9, 10, 11, full swing.
    """
    order = {club: position for position, club in enumerate(spec.clubs)}
    base = club_variant(shots)

    keep = base.isin(order) & shots["intent"].isin(spec.intents)
    if spec.pairs:
        wanted = set(spec.pairs)
        in_pairs = [(b, int(i)) in wanted if pd.notna(i) else False for b, i in zip(base, shots["intent"])]
        keep &= pd.Series(in_pairs, index=shots.index)
    out = shots[keep].copy()
    out["bag_order"] = base[keep].map(order).astype(int)
    out["intent_order"] = -out["intent"].astype(int) if full_swing_first else out["intent"].astype(int)
    out = out.sort_values(["bag_order", "intent_order", "timestamp", "shot_index"], kind="stable")
    out = out.drop(columns="intent_order")
    return out.reset_index(drop=True)


def bag_labels(spec: BagSpec) -> list[str]:
    """Display labels in bag order: one per club entry and intent."""
    from golf.data.labels import build_label

    labels = []
    for entry in spec.clubs:
        club, _, variant = entry.partition(" ")
        for intent in sorted(spec.intents):
            if spec.pairs and (entry, intent) not in spec.pairs:
                continue
            labels.append(build_label(club, variant or None, intent))
    return labels


def unlisted_clubs(shots: pd.DataFrame, spec: BagSpec) -> pd.DataFrame:
    """Clubs that were recorded but are not in the bag, newest first.

    A club you have just started using shows up here until it is added to the
    bag, so it cannot be silently left out of the analysis.
    """
    base = club_variant(shots)
    unlisted = (base != "") & ~base.isin(spec.clubs)
    if not unlisted.any():
        return pd.DataFrame(columns=["club_variant", "shots", "last_session"])
    other = shots[unlisted].assign(club_variant=base[unlisted])
    summary = (
        other.groupby("club_variant")
        .agg(shots=("club_variant", "size"), last_session=("session_date", "max"))
        .reset_index()
    )
    return summary.sort_values("last_session", ascending=False).reset_index(drop=True)


def available_clubs(shots: pd.DataFrame, preferred=()) -> List[Dict]:
    """Every club found in the data with its shot count and last session, in standard order."""
    base = club_variant(shots)
    found = shots[base != ""].assign(club_variant=base[base != ""])
    rows = []
    for entry, group in found.groupby("club_variant"):
        rows.append({
            "club": entry, "shots": int(len(group)),
            "last_session": str(group["session_date"].max()),
            "full_swing_shots": int((group["intent"] == FULL_SWING).sum()),
        })
    return sorted(rows, key=lambda row: entry_key(row["club"], preferred))


def intent_grid(shots: pd.DataFrame, preferred=()) -> List[Dict]:
    """Shots per club and intent, one row per club: {'club': 'gw 50', 'counts': {12: 30, 11: 25, ...}}."""
    base = club_variant(shots)
    found = shots[base != ""].assign(club_variant=base[base != ""])
    rows = []
    for entry, group in found.groupby("club_variant"):
        counts = {int(intent): int(n) for intent, n in group["intent"].value_counts().items()}
        rows.append({"club": entry, "counts": counts})
    return sorted(rows, key=lambda row: entry_key(row["club"], preferred))
