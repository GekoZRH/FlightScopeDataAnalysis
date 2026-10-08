"""Standard order of clubs on the cards and in the dashboard.

Driver first, then woods, hybrids, irons (low to high number) and wedges
(pw, aw, gw, sw, lw). Two variants of the same club keep the order in which they
are listed in `preferred` (normally the default bag in golf.toml), otherwise
they are sorted by name.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Tuple

_KIND_RANK = {"w": 1, "h": 2, "i": 3}
_WEDGES = ["pw", "aw", "gw", "sw", "lw"]
_NUMBERED = re.compile(r"^(\d+)([whi])$")


def club_rank(club: str) -> Tuple[int, int]:
    """Sort key for a club such as 'driver', '5w', '7i' or 'gw'."""
    if club == "driver":
        return (0, 0)
    match = _NUMBERED.match(club)
    if match:
        return (_KIND_RANK[match.group(2)], int(match.group(1)))
    if club in _WEDGES:
        return (4, _WEDGES.index(club))
    return (9, 0)


def entry_key(entry: str, preferred: Sequence[str] = ()) -> Tuple[Tuple[int, int], int, str]:
    club, _, variant = entry.partition(" ")
    position = preferred.index(entry) if entry in preferred else len(preferred)
    return (club_rank(club), position, variant)


def sort_entries(entries: Iterable[str], preferred: Sequence[str] = ()) -> List[str]:
    """Order 'club variant' entries in the standard bag order."""
    return sorted(set(entries), key=lambda entry: entry_key(entry, preferred))
