"""Select and order shots according to the bag defined in golf.toml."""

from __future__ import annotations

import pandas as pd

from golf.config import BagSpec


def select_bag(shots: pd.DataFrame, spec: BagSpec) -> pd.DataFrame:
    """Keep only the configured clubs and intents, sorted in bag order.

    A bag entry such as '8i 241' matches on club + variant; the swing intent is
    filtered separately through `spec.intents`. Rows without a recorded carry
    are kept, since they still carry information such as club speed.
    """
    order = {club: position for position, club in enumerate(spec.clubs)}
    base = (shots["club"].fillna("") + " " + shots["variant"].fillna("")).str.strip()

    keep = base.isin(order) & shots["intent"].isin(spec.intents)
    out = shots[keep].copy()
    out["bag_order"] = base[keep].map(order).astype(int)
    out = out.sort_values(["bag_order", "intent", "timestamp", "shot_index"], kind="stable")
    return out.reset_index(drop=True)


def bag_labels(spec: BagSpec) -> list[str]:
    """Display labels in bag order: one per club entry and intent."""
    from golf.data.labels import build_label

    labels = []
    for entry in spec.clubs:
        club, _, variant = entry.partition(" ")
        for intent in sorted(spec.intents):
            labels.append(build_label(club, variant or None, intent))
    return labels


def unlisted_clubs(shots: pd.DataFrame, spec: BagSpec) -> pd.DataFrame:
    """Clubs that were recorded but are not in the bag, newest first.

    A club you have just started using shows up here until it is added to
    golf.toml, so it cannot be silently left out of the analysis.
    """
    base = (shots["club"].fillna("") + " " + shots["variant"].fillna("")).str.strip()
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
