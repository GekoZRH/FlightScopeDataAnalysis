"""Parse raw FlightScope club labels into club, variant and swing intent.

Examples (raw label -> club, variant, intent):
    "7 Iron 245"      -> 7i,     245,   12 (full swing)
    "Driver Ping"     -> driver, ping,  12
    "GW 50_9"         -> gw,     50,    9
    "8 Iron 241_11"   -> 8i,     241,   11
    "2 iron MP-20 HBM"-> 2i,     mp-20 hbm, 12
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional

# Swing intent is the clock hour chosen in the simulator. A label without an
# intent suffix means no reduced swing was selected, i.e. a full swing.
FULL_SWING = 12

_INTENT_SUFFIX = re.compile(r"^(?P<base>.*\S)_(?P<intent>\d{1,2})$")

_WEDGE_NAMES = {
    "pitching wedge": "pw",
    "approach wedge": "aw",
    "gap wedge": "gw",
    "sand wedge": "sw",
    "lob wedge": "lw",
}
_KIND_LETTER = {"iron": "i", "wood": "w", "hybrid": "h", "i": "i", "w": "w", "h": "h"}

# The club is always the first thing in the label; whatever follows is the variant.
_CLUB_PATTERNS = [
    re.compile(r"^(?P<num>\d+)\s*(?P<kind>i|w|h)\b"),               # 7i, 5w, 4h
    re.compile(r"^(?P<num>\d+)\s*(?P<kind>iron|wood|hybrid)\b"),    # 7 iron, 5 wood
    re.compile(r"^(?P<name>driver)\b"),
    re.compile(r"^(?P<name>pitching wedge|approach wedge|gap wedge|sand wedge|lob wedge)\b"),
    re.compile(r"^(?P<name>pw|aw|gw|sw|lw)\b"),
]


@dataclass(frozen=True)
class ClubLabel:
    """Result of parsing one raw club label. `club` is None if it was not understood."""

    raw: str
    club: Optional[str]
    variant: Optional[str]
    intent: int

    @property
    def label(self) -> Optional[str]:
        """Canonical label such as '8i 245' or 'gw 50_9'. None if not parsed."""
        return build_label(self.club, self.variant, self.intent)


def build_label(club: Optional[str], variant: Optional[str], intent: int = FULL_SWING) -> Optional[str]:
    """Build the canonical label used for selection, grouping and display."""
    if not club:
        return None
    text = f"{club} {variant}" if variant else club
    if intent != FULL_SWING:
        text = f"{text}_{intent}"
    return text


class LabelParser:
    """Parses raw club labels, applying the alias tables from the configuration."""

    def __init__(
        self,
        label_aliases: Optional[Mapping[str, str]] = None,
        variant_aliases: Optional[Mapping[str, str]] = None,
    ):
        self._label_aliases = {_norm(k): _norm(v) for k, v in (label_aliases or {}).items()}
        self._variant_aliases = {_norm(k): _norm(v) for k, v in (variant_aliases or {}).items()}

    def parse(self, raw) -> ClubLabel:
        if raw is None or (isinstance(raw, float) and raw != raw):
            return ClubLabel(raw="", club=None, variant=None, intent=FULL_SWING)

        text = _norm(str(raw))
        intent = FULL_SWING
        match = _INTENT_SUFFIX.match(text)
        if match:
            candidate = int(match.group("intent"))
            if 1 <= candidate <= 12:
                text, intent = match.group("base"), candidate

        text = self._label_aliases.get(text, text)

        for pattern in _CLUB_PATTERNS:
            m = pattern.match(text)
            if not m:
                continue
            groups = m.groupdict()
            if "num" in groups:
                club = f"{groups['num']}{_KIND_LETTER[groups['kind']]}"
            else:
                club = _WEDGE_NAMES.get(groups["name"], groups["name"])
            variant = text[m.end():].strip() or None
            if variant is not None:
                variant = self._variant_aliases.get(variant, variant)
            return ClubLabel(raw=str(raw), club=club, variant=variant, intent=intent)

        return ClubLabel(raw=str(raw), club=None, variant=None, intent=intent)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())
