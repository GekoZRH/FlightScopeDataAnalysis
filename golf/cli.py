"""Command line.

    python -m golf cards        write the printed distance cards
    python -m golf dashboard    open the dashboard in the browser
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional

from golf.bag import unlisted_clubs
from golf.config import load_config
from golf.data import load_shots, unparsed_labels
from golf.report.build import CARDS, generate_card


def build_cards(as_of: Optional[date] = None, config_path: Optional[Path] = None) -> List[Path]:
    """Write the printed distance cards and report anything that needs attention."""
    config = load_config(config_path)
    written: List[Path] = []
    for mode in CARDS:
        shots = load_shots(mode, config)
        report_problems(mode, shots, config)
        try:
            paths, card = generate_card(mode, shots, config, as_of)
        except ValueError as error:
            print(f"[{mode}] {error}")
            continue
        written.extend(paths)
        print(f"[{mode}] card up to {card['as_of'].iloc[0]}: {len(card)} rows -> {paths[0]}")
        for _, row in card[card["status"] != "ok"].iterrows():
            print(f"    {row['label']}: {row['status']} (n={row['n']}, window {row['window']})")
    return written


def report_problems(mode: str, shots, config) -> None:
    unreadable = unparsed_labels(shots)
    if not unreadable.empty:
        print(f"[{mode}] club labels that could not be read:")
        print(unreadable.to_string(index=False))
    new_clubs = unlisted_clubs(shots, config.bag[mode])
    if not new_clubs.empty:
        print(f"[{mode}] clubs recorded but not in the bag (tick them in the dashboard to include them):")
        print(new_clubs.to_string(index=False))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="golf", description="FlightScope practice analysis")
    sub = parser.add_subparsers(dest="command", required=True)

    cards = sub.add_parser("cards", help="write the printed distance cards")
    cards.add_argument("--as-of", type=date.fromisoformat, help="last day to include (YYYY-MM-DD); default: latest session")
    cards.add_argument("--config", type=Path, help="path to golf.toml")

    dash = sub.add_parser("dashboard", help="open the dashboard in the browser")
    dash.add_argument("--port", type=int, default=8765)
    dash.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    dash.add_argument("--config", type=Path, help="path to golf.toml")

    args = parser.parse_args(argv)
    if args.command == "cards":
        build_cards(args.as_of, args.config)
    elif args.command == "dashboard":
        from golf.dashboard.server import serve

        serve(args.config, args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
