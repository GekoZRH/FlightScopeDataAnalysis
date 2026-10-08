"""Project configuration, read from golf.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from golf.data.labels import FULL_SWING, LabelParser

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "golf.toml"

MODES = ("swing", "pitching")


@dataclass(frozen=True)
class BagSpec:
    """Clubs (in display order) and swing intents that one analysis covers."""

    clubs: Tuple[str, ...]
    intents: Tuple[int, ...] = (FULL_SWING,)


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

    def data_dir(self, mode: str) -> Path:
        if mode == "swing":
            return self.swing_dir
        if mode == "pitching":
            return self.pitching_dir
        raise ValueError(f"Unknown mode {mode!r}, expected one of {MODES}")

    def label_parser(self) -> LabelParser:
        return LabelParser(self.label_aliases, self.variant_aliases)


def load_config(path: Optional[Path] = None) -> Config:
    """Read golf.toml. Relative paths in it are resolved against the file's folder."""
    path = Path(path) if path else DEFAULT_CONFIG
    with open(path, "rb") as handle:
        raw = tomllib.load(handle)

    root = path.resolve().parent
    paths = raw["paths"]
    aliases = raw.get("aliases", {})

    bag: Dict[str, BagSpec] = {}
    for mode, spec in raw.get("bag", {}).items():
        if mode not in MODES:
            raise ValueError(f"[bag.{mode}] is not a known mode, expected one of {MODES}")
        bag[mode] = BagSpec(
            clubs=tuple(c.strip().lower() for c in spec["clubs"]),
            intents=tuple(int(i) for i in spec.get("intents", [FULL_SWING])),
        )

    return Config(
        root=root,
        swing_dir=root / paths["swing_dir"],
        pitching_dir=root / paths["pitching_dir"],
        output_dir=root / paths["output_dir"],
        label_aliases=dict(aliases.get("label", {})),
        variant_aliases=dict(aliases.get("variant", {})),
        bag=bag,
        stats=StatsSettings(**raw.get("stats", {})),
    )
