"""Command line: python -m golf cards"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional

from golf.bag import select_bag, unlisted_clubs
from golf.config import load_config
from golf.data import load_shots, unparsed_labels
from golf.report import draw_distance_card
from golf.stats import card_table

# Mode -> (file name of the card, columns to describe in addition to carry/lateral)
CARDS = {
    "swing": ("swing_distance_card.png", {}),
    "pitching": ("wedge_distance_card.png", {"roll": "roll_m"}),
}


def build_cards(as_of: Optional[date] = None, config_path: Optional[Path] = None) -> List[Path]:
    """Write the printed distance cards and report anything that needs attention."""
    config = load_config(config_path)
    out_dir = config.output_dir / "cards"
    archive = out_dir / "archive"
    archive.mkdir(parents=True, exist_ok=True)

    written: List[Path] = []
    for mode, (filename, extra) in CARDS.items():
        shots = load_shots(mode, config)
        _report_problems(mode, shots, config)

        selected = select_bag(shots, config.bag[mode], full_swing_first=True)
        metrics = {"carry": "carry_m", "lateral": "lateral_m", **extra}
        card = card_table(selected, config.stats, as_of=as_of, metrics=metrics)
        if card.empty:
            print(f"[{mode}] no shots to draw a card from")
            continue

        fig = draw_distance_card(card, config.cards[mode], config.stats)
        stamp = card["as_of"].iloc[0]
        for path in (out_dir / filename, archive / f"{stamp}_{filename}"):
            fig.savefig(path, dpi=300)
            written.append(path)
        print(f"[{mode}] card up to {stamp}: {len(card)} rows -> {out_dir / filename}")
        for _, row in card[card["status"] != "ok"].iterrows():
            print(f"    {row['label']}: {row['status']} (n={row['n']}, window {row['window']})")
    return written


def _report_problems(mode: str, shots, config) -> None:
    unreadable = unparsed_labels(shots)
    if not unreadable.empty:
        print(f"[{mode}] club labels that could not be read:")
        print(unreadable.to_string(index=False))
    new_clubs = unlisted_clubs(shots, config.bag[mode])
    if not new_clubs.empty:
        print(f"[{mode}] clubs recorded but not in the bag (add them to golf.toml to include them):")
        print(new_clubs.to_string(index=False))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="golf", description="FlightScope practice analysis")
    sub = parser.add_subparsers(dest="command", required=True)
    cards = sub.add_parser("cards", help="write the printed distance cards")
    cards.add_argument("--as-of", type=date.fromisoformat, help="last day to include (YYYY-MM-DD); default: latest session")
    cards.add_argument("--config", type=Path, help="path to golf.toml")
    args = parser.parse_args(argv)

    if args.command == "cards":
        build_cards(args.as_of, args.config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
