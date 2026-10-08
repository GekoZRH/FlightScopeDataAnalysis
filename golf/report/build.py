"""Build and save the printed distance cards."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from golf.bag import select_bag
from golf.config import Config
from golf.report.cards import draw_distance_card
from golf.stats import card_table

# Mode -> (file name of the card, measurements described in addition to carry and lateral)
CARDS = {
    "swing": ("swing_distance_card.png", {}),
    "pitching": ("wedge_distance_card.png", {"roll": "roll_m"}),
}


def generate_card(
    mode: str, shots: pd.DataFrame, config: Config, as_of: Optional[date] = None
) -> Tuple[List[Path], pd.DataFrame]:
    """Draw the card of `mode` from the selected clubs and save it.

    Two files are written into the cards folder of the data set: the card under
    its fixed name (the one to print) and a copy named after the last session in
    `archive/`. Returns the paths (print copy first) and the table behind the card.
    """
    filename, extra = CARDS[mode]
    selected = select_bag(shots, config.bag[mode], full_swing_first=True)
    metrics = {"carry": "carry_m", "lateral": "lateral_m", **extra}
    card = card_table(selected, config.stats, as_of=as_of, metrics=metrics)
    if card.empty:
        raise ValueError("No shots for the selected clubs, so there is no card to draw")

    fig = draw_distance_card(card, config.cards[mode], config.stats)
    folder = config.cards_dir(mode)
    (folder / "archive").mkdir(parents=True, exist_ok=True)
    stamp = card["as_of"].iloc[0]
    paths = [folder / filename, folder / "archive" / f"{stamp}_{filename}"]
    for path in paths:
        fig.savefig(path, dpi=300)
    return paths, card
