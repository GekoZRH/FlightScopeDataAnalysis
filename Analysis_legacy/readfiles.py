"""CSV readers and parsing utilities for indoor and Foresight golf data.

This module handles the slightly messy text formatting in the source files,
including club-name normalization, lateral-direction parsing and unit
conversion.
"""

import pandas as pd
from pathlib import Path
import re


YARDS_TO_METERS = 0.9144
FEET_TO_METERS = 0.3048


def parse_lateral(value):
    """Parse lateral values such as '4.5R' or '3.0L' into signed meters.

    Right values become positive and left values become negative.
    Invalid or empty values are returned as pandas missing values.
    """
    if pd.isna(value):
        return pd.NA

    s = str(value).strip()
    if s == "":
        return pd.NA

    m = re.match(r"^\s*([+-]?\d+(?:\.\d+)?)\s*([RrLl]?)\s*$", s)
    if not m:
        return pd.NA

    number = float(m.group(1))
    direction = m.group(2).lower()
    return -number if direction == "l" else number


def _extract_model_from_tokens(original, club):
    """Best-effort extraction of the club model from a raw club string.

    The parsing logic is intentionally simple and based on the naming patterns
    in the source data files.
    """
    tokens = original.split()
    if not tokens:
        return None

    if club == "driver" and len(tokens) >= 2:
        return tokens[-1]
    if club in {"pw", "aw", "gw", "sw", "lw"}:
        wedge_words = {
            "pitching", "gap", "approach", "sand", "lob", "wedge",
            "pw", "aw", "gw", "sw", "lw"
        }
        remainder = [t for t in tokens if t.lower() not in wedge_words]
        return remainder[-1] if remainder else None
    if club and len(tokens) >= 2:
        return tokens[-1]
    return None


def normalize_club(club_string):
    """Normalize many raw club name variants into a compact internal format.

    Examples:
    - '7 Iron 245' -> ('7i', '245')
    - '3 Wood' -> ('3w', None)
    - 'Gap Wedge SC' -> ('gw', 'SC')
    """
    if pd.isna(club_string):
        return None, None

    original = str(club_string).strip()
    if original == "":
        return None, None

    s = re.sub(r"\s+", " ", original.lower()).strip()

    compact_match = re.match(r"^(\d+)\s*([iwh])\b(?:\s+(.*))?$", s)
    if compact_match:
        number = compact_match.group(1)
        kind = compact_match.group(2)
        remainder = compact_match.group(3)
        club = f"{number}{kind}"
        model = remainder.strip() if remainder and remainder.strip() else None
        return club, model

    iron_match = re.search(r"(\d+)\s*iron\b", s)
    wood_match = re.search(r"(\d+)\s*wood\b", s)
    hybrid_match = re.search(r"(\d+)\s*hybrid\b", s)

    if iron_match:
        club = f"{iron_match.group(1)}i"
        return club, _extract_model_from_tokens(original, club)
    if wood_match:
        club = f"{wood_match.group(1)}w"
        return club, _extract_model_from_tokens(original, club)
    if hybrid_match:
        club = f"{hybrid_match.group(1)}h"
        return club, _extract_model_from_tokens(original, club)

    if "driver" in s:
        return "driver", _extract_model_from_tokens(original, "driver")

    for phrase, club in [
        ("pitching wedge", "pw"),
        ("approach wedge", "aw"),
        ("gap wedge", "gw"),
        ("sand wedge", "sw"),
        ("lob wedge", "lw"),
    ]:
        if phrase in s:
            return club, _extract_model_from_tokens(original, club)

    short_match = re.match(r"^(pw|aw|gw|sw|lw)\b(?:\s+(.*))?$", s)
    if short_match:
        club = short_match.group(1)
        remainder = short_match.group(2)
        model = remainder.strip() if remainder and remainder.strip() else None
        return club, model

    return None, None


def read_shot_file(filepath):
    """Read one indoor shot CSV file and convert it into analysis-ready columns."""
    filepath = Path(filepath)
    df = pd.read_csv(filepath, encoding="windows-1252")

    if "Time" not in df.columns:
        raise ValueError("CSV file does not contain 'Time' column")

    # The time column stores date and time in one semicolon-separated field.
    # It is split so the session date can be used for grouping plots by day.
    time_split = df["Time"].astype(str).str.split(";", expand=True)
    df["Date"] = time_split[0].str.strip()
    df["Clock"] = time_split[1].str.strip().str.replace("-", ":", regex=False)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["session_date"] = df["Date"].dt.date

    # Convert raw club strings into normalized club and model columns.
    if "Club" in df.columns:
        clubs = df["Club"].apply(normalize_club)
        df["Club"] = clubs.apply(lambda x: x[0])
        df["Model"] = clubs.apply(lambda x: x[1])
    else:
        df["Club"] = None
        df["Model"] = None

    # Convert lateral strings with L/R direction suffixes into signed numbers.
    if "Lateral [m]" in df.columns:
        df["Lateral [m]"] = df["Lateral [m]"].apply(parse_lateral)

    # Convert relevant measurement columns to numeric values.
    numeric_cols = [
        "Carry [m]", "Lateral [m]", "Club Speed [mph]", "Ball Speed [mph]",
        "Descent V [deg]", "Height [m]", "Spin [rpm]",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def read_multiple_files(file_list):
    """Read several indoor CSV files and concatenate them into one DataFrame."""
    frames = []
    for f in file_list:
        print(f"Loading swing file: {f}")
        frames.append(read_shot_file(f))
    return pd.concat(frames, ignore_index=True)


def _convert_distance_series(series, unit):
    """Convert a pandas Series of distances into meters."""
    unit = str(unit).strip().lower()
    numeric = pd.to_numeric(series, errors="coerce")
    if unit in {"m", "meter", "meters", "metre", "metres"}:
        return numeric
    if unit in {"yd", "yard", "yards"}:
        return numeric * YARDS_TO_METERS
    if unit in {"ft", "foot", "feet"}:
        return numeric * FEET_TO_METERS
    raise ValueError(f"Unsupported distance unit: {unit}")


def read_foresight_file(filepath, distance_unit="m"):
    """Read one Foresight export file and map its columns to the indoor format."""
    filepath = Path(filepath)
    df = pd.read_csv(filepath, encoding="windows-1252", skipinitialspace=True)

    if "Club" not in df.columns:
        raise ValueError("Foresight CSV does not contain 'Club' column")

    clubs = df["Club"].apply(normalize_club)
    df["Club"] = clubs.apply(lambda x: x[0])
    df["Model"] = clubs.apply(lambda x: x[1])

    # Harmonize key columns so the same downstream plotting code can be used for
    # both indoor data and Foresight reference data.
    df = df.rename(columns={"Ball Speed": "Ball Speed [mph]", "Backspin": "Spin [rpm]"})
    df["Carry [m]"] = _convert_distance_series(df["Carry"], distance_unit) if "Carry" in df.columns else pd.NA

    for col in ["Ball Speed [mph]", "Spin [rpm]"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["source"] = "foresight_reference"
    return df
