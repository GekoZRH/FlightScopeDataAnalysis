"""The target files you edit by hand: ranges for the club delivery numbers and the driver's optimal launch and spin.

They live in one folder (`targets_dir` in golf.toml, default `targets`):

- `delivery_ranges.toml`        attack angle per club, club path and face to path (a default and per club)
- `dynamic_loft_ranges.toml`    dynamic loft per club
- `driver_optimal_launch.csv`   optimal launch angle of a driver by ball speed (rows) and angle of attack (columns)
- `driver_optimal_spin.csv`     the same for the spin rate

A file that is missing is not an error: what depends on it is simply not shown, and the problem is listed in `notes`.
A file that cannot be read, or has a wrong value, is reported in `notes` with the file and the entry, and the rest is used.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator

Range = Tuple[float, float]

DELIVERY_FILE = "delivery_ranges.toml"
LOFT_FILE = "dynamic_loft_ranges.toml"
LAUNCH_FILE = "driver_optimal_launch.csv"
SPIN_FILE = "driver_optimal_spin.csv"


@dataclass(frozen=True)
class OptimalChart:
    """Optimal launch angle and spin for a driver, from ball speed and angle of attack (the PING chart)."""

    speeds: np.ndarray          # ball speed, mph, ascending
    aoas: np.ndarray            # angle of attack, deg, ascending
    launch: np.ndarray          # [speed, aoa], deg
    spin: np.ndarray            # [speed, aoa], rpm

    def lookup(self, ball_mph, aoa_deg) -> Tuple[np.ndarray, np.ndarray]:
        """Optimal launch (deg) and spin (rpm) for shots. Values outside the chart are taken at its edge."""
        speed = np.clip(np.asarray(ball_mph, dtype=float), self.speeds[0], self.speeds[-1])
        aoa = np.clip(np.asarray(aoa_deg, dtype=float), self.aoas[0], self.aoas[-1])
        points = np.column_stack([np.atleast_1d(speed), np.atleast_1d(aoa)])
        launch = RegularGridInterpolator((self.speeds, self.aoas), self.launch)(points)
        spin = RegularGridInterpolator((self.speeds, self.aoas), self.spin)(points)
        return launch, spin


@dataclass(frozen=True)
class Targets:
    folder: Optional[Path] = None
    attack_angle: Dict[str, Range] = field(default_factory=dict)
    club_path: Dict[str, Range] = field(default_factory=dict)
    face_to_path: Dict[str, Range] = field(default_factory=dict)
    dynamic_loft: Dict[str, Range] = field(default_factory=dict)
    chart: Optional[OptimalChart] = None
    notes: List[str] = field(default_factory=list)

    def band(self, measure: str, label: str) -> Optional[Range]:
        """The target range of a delivery measure for a club label like '8i 241': the label itself, else its club, else 'default'."""
        table = {"attack_angle": self.attack_angle, "club_path": self.club_path, "face_to_path": self.face_to_path,
                 "dynamic_loft": self.dynamic_loft}[measure]
        club = label.partition(" ")[0]
        for key in (label, club, "default"):
            if key in table:
                return table[key]
        return None


def _ranges(section, file: str, name: str, notes: List[str]) -> Dict[str, Range]:
    out: Dict[str, Range] = {}
    if section is None:
        return out
    if not isinstance(section, dict):
        notes.append(f"{file}: [{name}] must be a table of club = [low, high]")
        return out
    for club, value in section.items():
        ok = (isinstance(value, list) and len(value) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value))
        if not ok:
            notes.append(f"{file}: [{name}] {club}: expected two numbers [low, high]")
        elif value[0] >= value[1]:
            notes.append(f"{file}: [{name}] {club}: the low value {value[0]} must be below the high value {value[1]}")
        else:
            out[str(club).strip().lower()] = (float(value[0]), float(value[1]))
    return out


def _read_toml(path: Path, notes: List[str]) -> Optional[dict]:
    if not path.is_file():
        notes.append(f"{path.name} not found in {path.parent}")
        return None
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except (tomllib.TOMLDecodeError, OSError) as error:
        notes.append(f"{path.name} could not be read: {error}")
        return None


def _read_grid(path: Path, notes: List[str]) -> Optional[pd.DataFrame]:
    if not path.is_file():
        notes.append(f"{path.name} not found in {path.parent}")
        return None
    try:
        grid = pd.read_csv(path, comment="#", index_col=0)
        grid.columns = [float(c) for c in grid.columns]
        grid.index = grid.index.astype(float)
        grid = grid.astype(float)
    except (ValueError, OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
        notes.append(f"{path.name} could not be read: {error}")
        return None
    if grid.shape[0] < 2 or grid.shape[1] < 2:
        notes.append(f"{path.name}: needs at least two ball speeds and two angles of attack")
        return None
    if grid.isna().any().any():
        notes.append(f"{path.name}: the grid has empty cells")
        return None
    if grid.index.duplicated().any() or grid.columns.duplicated().any():
        notes.append(f"{path.name}: a ball speed or an angle of attack appears twice")
        return None
    return grid.sort_index().sort_index(axis=1)


def load_targets(folder: Optional[Path]) -> Targets:
    """Read the target files of a folder (see the module description). Never raises for a bad file: look at `notes`."""
    notes: List[str] = []
    if folder is None:
        return Targets(None, notes=notes)
    folder = Path(folder)
    if not folder.is_dir():
        return Targets(folder, notes=[f"The target folder {folder} does not exist"])

    delivery = _read_toml(folder / DELIVERY_FILE, notes) or {}
    loft = _read_toml(folder / LOFT_FILE, notes) or {}

    launch, spin = _read_grid(folder / LAUNCH_FILE, notes), _read_grid(folder / SPIN_FILE, notes)
    chart = None
    if launch is not None and spin is not None:
        if launch.shape != spin.shape or not (np.array_equal(launch.index, spin.index) and np.array_equal(launch.columns, spin.columns)):
            notes.append(f"{LAUNCH_FILE} and {SPIN_FILE} must have the same ball speeds and angles of attack")
        else:
            chart = OptimalChart(launch.index.to_numpy(float), launch.columns.to_numpy(float), launch.to_numpy(float), spin.to_numpy(float))

    return Targets(
        folder=folder,
        attack_angle=_ranges(delivery.get("attack_angle"), DELIVERY_FILE, "attack_angle", notes),
        club_path=_ranges(delivery.get("club_path"), DELIVERY_FILE, "club_path", notes),
        face_to_path=_ranges(delivery.get("face_to_path"), DELIVERY_FILE, "face_to_path", notes),
        dynamic_loft=_ranges(loft.get("dynamic_loft"), LOFT_FILE, "dynamic_loft", notes),
        chart=chart, notes=notes,
    )
