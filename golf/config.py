"""Project configuration.

golf.toml holds the defaults. Choices made in the dashboard (data folders, the
clubs in the bag, the wedge intents on the wedge card) are saved next to it in
golf.local.json, which takes precedence and is not meant to be committed.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from golf.data.labels import FULL_SWING, LabelParser
from golf.ordering import sort_entries

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "golf.toml"
LOCAL_SETTINGS_NAME = "golf.local.json"

MODES = ("swing", "pitching")


@dataclass(frozen=True)
class BagSpec:
    """Clubs (in display order) and swing intents that one analysis covers.

    `pairs` is optional. When set, only those (club variant, intent) combinations
    are used, e.g. ('gw 50', 11); `clubs` and `intents` then describe the same set.
    """

    clubs: Tuple[str, ...]
    intents: Tuple[int, ...] = (FULL_SWING,)
    pairs: Tuple[Tuple[str, int], ...] = ()

    @classmethod
    def from_pairs(cls, pairs: Iterable[Tuple[str, int]], preferred: Tuple[str, ...] = ()) -> "BagSpec":
        unique = {(club.strip().lower(), int(intent)) for club, intent in pairs}
        clubs = tuple(sort_entries((club for club, _ in unique), preferred))
        intents = tuple(sorted({intent for _, intent in unique}, reverse=True))
        ordered = tuple(sorted(unique, key=lambda p: (clubs.index(p[0]), -p[1])))
        return cls(clubs=clubs, intents=intents, pairs=ordered)


@dataclass(frozen=True)
class CardSpec:
    """Look of one printed distance card."""

    title: str
    notes: Tuple[str, ...] = ()     # free text blocks (e.g. wind rules of thumb) in the empty upper left
    xtick_step: int = 10
    minor_step: int = 0             # 0 = no minor grid
    show_roll: bool = False         # print the mean roll at the end of each bar


@dataclass(frozen=True)
class StatsSettings:
    """Thresholds for the statistics. Defaults match golf.toml."""

    window_weeks: int = 4          # recent window used for the printed card
    fallback_weeks: int = 12       # wider window when the recent one has too few shots
    min_shots: int = 12            # shots a club/intent needs for meaningful statistics
    min_shots_skew: int = 25       # skew-normal is only considered from this many shots
    skew_alpha: float = 0.05       # significance level of the skew-normal vs normal test
    ci_level: float = 0.95
    n_bootstrap: int = 2000
    min_shots_compare: int = 8     # shots per period needed to compare two periods
    min_shots_session: int = 5     # shots of one session needed to compare it with earlier ones
    seed: int = 12345


@dataclass(frozen=True)
class Config:
    root: Path
    swing_dir: Path
    pitching_dir: Path
    output_dir: Path
    label_aliases: Dict[str, str] = field(default_factory=dict)
    variant_aliases: Dict[str, str] = field(default_factory=dict)
    bag: Dict[str, BagSpec] = field(default_factory=dict)
    stats: StatsSettings = field(default_factory=StatsSettings)
    cards: Dict[str, CardSpec] = field(default_factory=dict)
    default_bag: Dict[str, BagSpec] = field(default_factory=dict)   # golf.toml, before local choices
    local_path: Optional[Path] = None

    def data_dir(self, mode: str) -> Path:
        if mode == "swing":
            return self.swing_dir
        if mode == "pitching":
            return self.pitching_dir
        raise ValueError(f"Unknown mode {mode!r}, expected one of {MODES}")

    def cards_dir(self, mode: str) -> Path:
        """Folder for the cards of the data set currently loaded for `mode`.

        One folder per data folder, so switching data sets does not overwrite
        the cards of another one.
        """
        return self.output_dir / "cards" / dataset_slug(self.data_dir(mode))

    def label_parser(self) -> LabelParser:
        return LabelParser(self.label_aliases, self.variant_aliases)


def dataset_slug(folder: Path) -> str:
    """Folder name for a data set, e.g. SwingData/Indoor -> 'SwingData_Indoor'."""
    folder = Path(folder)
    parts = [folder.parent.name, folder.name]
    return re.sub(r"[^A-Za-z0-9._-]+", "_", "_".join(p for p in parts if p)).strip("_") or "data"


def _read_local(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_config(path: Optional[Path] = None, local_path: Optional[Path] = None) -> Config:
    """Read golf.toml, then apply golf.local.json. Relative paths resolve against the toml folder."""
    path = Path(path) if path else DEFAULT_CONFIG
    with open(path, "rb") as handle:
        raw = tomllib.load(handle)

    root = path.resolve().parent
    paths = raw["paths"]
    aliases = raw.get("aliases", {})

    default_bag: Dict[str, BagSpec] = {}
    for mode, spec in raw.get("bag", {}).items():
        if mode not in MODES:
            raise ValueError(f"[bag.{mode}] is not a known mode, expected one of {MODES}")
        default_bag[mode] = BagSpec(
            clubs=tuple(c.strip().lower() for c in spec["clubs"]),
            intents=tuple(int(i) for i in spec.get("intents", [FULL_SWING])),
        )

    cards: Dict[str, CardSpec] = {}
    for mode, spec in raw.get("cards", {}).items():
        if mode not in MODES:
            raise ValueError(f"[cards.{mode}] is not a known mode, expected one of {MODES}")
        values = dict(spec)
        values["notes"] = tuple(values.get("notes", ()))
        cards[mode] = CardSpec(**values)

    local_path = Path(local_path) if local_path else root / LOCAL_SETTINGS_NAME
    local = _read_local(local_path)

    bag = dict(default_bag)
    local_bag = local.get("bag", {})
    if local_bag.get("swing", {}).get("clubs"):
        swing_default = default_bag.get("swing", BagSpec(clubs=()))
        clubs = tuple(sort_entries((c.strip().lower() for c in local_bag["swing"]["clubs"]), swing_default.clubs))
        bag["swing"] = BagSpec(clubs=clubs, intents=swing_default.intents)
    if "pairs" in local_bag.get("pitching", {}):
        pairs = [(club, intent) for club, intent in local_bag["pitching"]["pairs"]]
        preferred = default_bag.get("pitching", BagSpec(clubs=())).clubs
        bag["pitching"] = BagSpec.from_pairs(pairs, preferred)

    return Config(
        root=root,
        swing_dir=root / local.get("swing_dir", paths["swing_dir"]),
        pitching_dir=root / local.get("pitching_dir", paths["pitching_dir"]),
        output_dir=root / paths["output_dir"],
        label_aliases=dict(aliases.get("label", {})),
        variant_aliases=dict(aliases.get("variant", {})),
        bag=bag,
        stats=StatsSettings(**raw.get("stats", {})),
        cards=cards,
        default_bag=default_bag,
        local_path=local_path,
    )


def update_local_settings(config: Config, patch: dict) -> None:
    """Merge `patch` into golf.local.json (nested dictionaries are merged, other values replaced)."""
    current = _read_local(config.local_path)

    def merge(target: dict, source: dict) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                merge(target[key], value)
            else:
                target[key] = value

    merge(current, patch)
    config.local_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
