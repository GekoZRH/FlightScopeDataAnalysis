"""Column handling for FlightScope CSV exports.

The exports are not consistent between sessions:
- some columns appear twice (``Club Speed [mph]`` and ``Club Speed [mph].1``)
- the unit of some columns changes (``Lateral Impact`` in mm or cm)
- direction values are text such as ``4.5 R`` or ``3.0 L``

This module maps the raw headers onto a fixed internal schema with one unit
per column.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

import pandas as pd

# raw header name (without unit) -> (internal name, {accepted unit: factor to the internal unit})
# Headers whose unit is not listed are ignored on purpose, e.g. "Roll [ft/s/ft]"
# next to "Roll [m]".
FIELDS: Dict[str, Tuple[str, Dict[Optional[str], float]]] = {
    "Carry": ("carry_m", {"m": 1.0}),
    "Roll": ("roll_m", {"m": 1.0}),
    "Total": ("total_m", {"m": 1.0}),
    "Lateral": ("lateral_m", {"m": 1.0}),
    "Curve Dist": ("curve_dist_m", {"m": 1.0}),
    "Smash": ("smash", {None: 1.0}),
    "Flight Time": ("flight_time_s", {"sec": 1.0}),
    "Spin": ("spin_rpm", {"rpm": 1.0}),
    "Spin Axis": ("spin_axis_deg", {"deg": 1.0}),
    "Club Path": ("club_path_deg", {"deg": 1.0}),
    "Ball Speed": ("ball_speed_mph", {"mph": 1.0}),
    "V-Plane": ("v_plane_deg", {"deg": 1.0}),
    "H-Plane": ("h_plane_deg", {"deg": 1.0}),
    "Launch V": ("launch_v_deg", {"deg": 1.0}),
    "Launch H": ("launch_h_deg", {"deg": 1.0}),
    "Height": ("height_m", {"m": 1.0}),
    "FTT": ("ftt_deg", {"deg": 1.0}),
    "Dynamic Loft": ("dynamic_loft_deg", {"deg": 1.0}),
    "Spin Loft": ("spin_loft_deg", {"deg": 1.0}),
    "Club Speed": ("club_speed_mph", {"mph": 1.0}),
    "Descent V": ("descent_v_deg", {"deg": 1.0}),
    "AOA": ("aoa_deg", {"deg": 1.0}),
    "Low Point": ("low_point_cm", {"cm": 1.0}),
    "FTP": ("ftp_deg", {"deg": 1.0}),
    "Lateral Impact": ("lateral_impact_mm", {"mm": 1.0, "cm": 10.0}),
    "Vertical Impact": ("vertical_impact_mm", {"mm": 1.0, "cm": 10.0}),
}

# Columns exported as "<number> L" / "<number> R". Right is positive, left negative.
DIRECTIONAL = {
    "lateral_m", "curve_dist_m", "spin_axis_deg", "club_path_deg",
    "h_plane_deg", "launch_h_deg", "ftt_deg", "ftp_deg",
}

METRIC_COLUMNS = [internal for internal, _ in FIELDS.values()]

_HEADER = re.compile(r"^(?P<name>.+?)\s*(?:\[(?P<unit>[^\]]*)\])?$")
_PANDAS_DUPLICATE_SUFFIX = re.compile(r"\.\d+$")
_DIRECTION = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*([RrLl]?)\s*$")


def parse_signed_direction(values: pd.Series) -> pd.Series:
    """Convert '4.5 R' to 4.5 and '3.0 L' to -3.0. Plain numbers keep their sign.

    Anything that is not a number with an optional L/R becomes NaN.
    """
    parts = values.astype("string").str.extract(_DIRECTION)
    number = pd.to_numeric(parts[0], errors="coerce")
    left = parts[1].str.lower() == "l"
    return number.where(~left.fillna(False), -number).astype("float64")


def split_header(header: str) -> Tuple[str, Optional[str]]:
    """Split 'Club Speed [mph]' into ('Club Speed', 'mph')."""
    m = _HEADER.match(header.strip())
    if not m:
        return header.strip(), None
    return m.group("name").strip(), m.group("unit")


def standardise_columns(raw: pd.DataFrame) -> pd.DataFrame:
    """Return the known measurement columns of a raw export under internal names.

    Duplicate headers are merged, taking the first non-missing value, units are
    converted and direction columns are made signed. All values are float.
    """
    out: Dict[str, pd.Series] = {}
    seen = set()
    for column in raw.columns:
        header = column
        base = _PANDAS_DUPLICATE_SUFFIX.sub("", column)
        if base != column and base in seen:
            header = base  # pandas renamed a repeated header; it is the same field
        seen.add(header)

        name, unit = split_header(header)
        spec = FIELDS.get(name)
        if spec is None:
            continue
        internal, units = spec
        if unit not in units:
            continue

        if internal in DIRECTIONAL:
            values = parse_signed_direction(raw[column])
        else:
            values = pd.to_numeric(raw[column], errors="coerce")
        values = values * units[unit]

        out[internal] = out[internal].combine_first(values) if internal in out else values

    frame = pd.DataFrame(out, index=raw.index)
    for internal in METRIC_COLUMNS:
        if internal not in frame:
            frame[internal] = float("nan")
    return frame[METRIC_COLUMNS]
