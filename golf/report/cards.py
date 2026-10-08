"""Printed carry-distance cards.

One horizontal bar per club (and swing intent). Dot and bold number: mean carry.
Thin bar and the numbers above it: central 68% of shots (about 1 sigma). Wide
bar and the numbers below it: central 95% (about 2 sigma). A '*' after the club
means its numbers come from older shots because the last few weeks did not
contain enough of them.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.ticker import MultipleLocator

from golf.config import CardSpec, StatsSettings

FIGSIZE = (9, 13.5)
DPI = 300
MEAN_FONT = 16
RANGE68_FONT = 16
RANGE95_FONT = 12
ROLL_FONT = 14
CLUB_FONT = 20
TICK_FONT = 20
LABEL_FONT = 16
TITLE_FONT = 13
NOTE_FONT = 18
FOOT_FONT = 11
GRID_WIDTH = 3.0
NUMBER_OFFSET_M = 0.7          # gap between a bar end and its number, in metres of carry
ROLL_GAP_M = 4.0
LIMIT_ROUND = 5               # axis limits are rounded to multiples of this
MARKERS = {"ok": "", "history": "*", "short": "**"}


def _round_down(value: float, step: int) -> float:
    return math.floor(value / step) * step


def _round_up(value: float, step: int) -> float:
    return math.ceil(value / step) * step


def _footnote(card: pd.DataFrame, settings: StatsSettings) -> str:
    parts = ["Dot / bold = mean.  Thin bar = middle 68% of shots, wide bar = middle 95%."]
    if (card["status"] == "history").any():
        parts.append(f"* fewer than {settings.min_shots} shots in the last {settings.fallback_weeks} weeks: all shots on record used.")
    if (card["status"] == "short").any():
        parts.append(f"** fewer than {settings.min_shots} shots on record: unreliable.")
    return "\n".join(parts)


def draw_distance_card(card: pd.DataFrame, spec: CardSpec, settings: StatsSettings) -> Figure:
    """Draw a distance card from `card_table` output, rows top to bottom.

    The `roll` columns (`roll_mean`) are only needed when `spec.show_roll` is set.
    """
    if card.empty:
        raise ValueError("No clubs to draw")
    card = card.reset_index(drop=True)
    rows = np.arange(len(card))

    fig = Figure(figsize=FIGSIZE)
    ax = fig.subplots()

    ax.hlines(rows, card["carry_lo95"], card["carry_hi95"], linewidth=9.0, alpha=0.7, color="C0")
    ax.hlines(rows, card["carry_lo68"], card["carry_hi68"], linewidth=5.0, alpha=0.95, color="C0")
    ax.plot(card["carry_mean"], rows, linestyle="None", marker="o", markersize=10, color="C0")

    for y, row in zip(rows, card.itertuples(index=False)):
        r = row._asdict()
        ax.text(r["carry_mean"] + NUMBER_OFFSET_M, y + 0.35, f"{r['carry_mean']:.0f}",
                ha="center", va="center", fontsize=MEAN_FONT, weight="bold")
        ax.text(r["carry_lo68"] - NUMBER_OFFSET_M, y - 0.3, f"{r['carry_lo68']:.0f}",
                ha="right", va="center", fontsize=RANGE68_FONT)
        ax.text(r["carry_hi68"] + NUMBER_OFFSET_M, y - 0.3, f"{r['carry_hi68']:.0f}",
                ha="left", va="center", fontsize=RANGE68_FONT)
        ax.text(r["carry_lo95"] - 2 * NUMBER_OFFSET_M, y + 0.35, f"{r['carry_lo95']:.0f}",
                ha="right", va="center", fontsize=RANGE95_FONT)
        ax.text(r["carry_hi95"] + 2 * NUMBER_OFFSET_M, y + 0.35, f"{r['carry_hi95']:.0f}",
                ha="left", va="center", fontsize=RANGE95_FONT)
        if spec.show_roll and np.isfinite(r.get("roll_mean", np.nan)):
            ax.text(r["carry_hi95"] + ROLL_GAP_M, y, f"roll {r['roll_mean']:.1f} m",
                    ha="left", va="center", fontsize=ROLL_FONT)

    labels = [f"{label}{MARKERS.get(status, '')}" for label, status in zip(card["label"], card["status"])]
    ax.set_yticks(rows)
    ax.set_yticklabels(labels, fontsize=CLUB_FONT)
    ax.invert_yaxis()

    step = spec.xtick_step
    right_room = 14 if spec.show_roll else 8     # room for the roll text / the 95% number
    x_min = _round_down(card["carry_lo95"].min() - 5, LIMIT_ROUND)
    x_max = _round_up(card["carry_hi95"].max() + right_room, LIMIT_ROUND)
    ax.set_xlim(x_min, x_max)
    ax.xaxis.set_major_locator(MultipleLocator(step))
    ax.tick_params(axis="x", labelsize=TICK_FONT)
    ax.grid(True, axis="both", alpha=1.0, linewidth=GRID_WIDTH)
    if spec.minor_step:
        ax.xaxis.set_minor_locator(MultipleLocator(spec.minor_step))
        ax.grid(True, which="minor", axis="x", alpha=0.6)

    for note, y in zip(spec.notes, (0.80, 0.58, 0.36)):
        ax.text(0.04, y, note, transform=ax.transAxes, ha="left", va="top", fontsize=NOTE_FONT)

    as_of = card["as_of"].iloc[0]
    ax.set_title(f"{spec.title}  (to {as_of})", fontsize=TITLE_FONT)
    ax.set_xlabel("Carry Distance (m)", fontsize=LABEL_FONT)
    ax.set_ylabel("Club", fontsize=LABEL_FONT)

    fig.tight_layout(rect=(0, 0.045, 1, 1))
    fig.text(0.02, 0.012, _footnote(card, settings), ha="left", va="bottom", fontsize=FOOT_FONT)
    return fig
