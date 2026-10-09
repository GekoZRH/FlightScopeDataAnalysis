"""Everything the dashboard shows, as plain data.

Each function takes the application state and returns JSON-friendly data, so
the numbers can be tested without a browser or a web server.
"""

from __future__ import annotations

import math
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from golf.bag import available_clubs, club_variant, intent_grid, select_bag, unlisted_clubs
from golf.config import FOLDER_KINDS, MODES, BagSpec, Config, load_config, update_local_settings
from golf.data import load_shots, unparsed_labels, unreadable_weights
from golf.data.garmin import GarminData, describe_garmin, find_export_folders, load_garmin
from golf.data.stack import stack_files
from golf.data.labels import FULL_SWING
from golf.report.build import generate_card
from golf.sessions import include_sessions, session_table
from golf.stats import (
    COVERAGE_1S, COVERAGE_2S, compare_normal, describe, fit_bivariate, fit_univariate,
    session_summary,
)
from golf.stats.context import PREDICTORS, session_context
from golf.stats.correlation import correlate
from golf.stats.outcomes import stack_speed, swing_spread, swing_speed

# What a session is compared with ("historic"):
#   last4     the 4 sessions before it, among all loaded sessions (selected or not)
#   all       all earlier sessions, among all loaded sessions (selected or not)
#   selected  all other selected sessions, earlier or later (the session itself is left out)
BASELINE_CHOICES = {"last4": 4, "all": None, "selected": None}


# --- state ---------------------------------------------------------------------------

class AppState:
    """The loaded data and settings of one running dashboard."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path
        self.lock = threading.RLock()
        self.config: Config = load_config(config_path)
        self.shots: Dict[str, Optional[pd.DataFrame]] = {mode: None for mode in MODES}
        self.garmin: Optional[GarminData] = None
        self.errors: Dict[str, str] = {}
        self.reload_data()

    def reload_config(self) -> None:
        self.config = load_config(self.config_path)

    def reload_data(self, modes=MODES) -> None:
        self.reload_garmin()
        for mode in modes:
            if self.config.data_dir(mode) is None:        # no folder chosen: this kind of data is not used
                self.shots[mode] = None
                self.errors.pop(mode, None)
                continue
            try:
                self.shots[mode] = load_shots(mode, self.config)
                self.errors.pop(mode, None)
            except (FileNotFoundError, ValueError, OSError) as error:
                self.shots[mode] = None
                self.errors[mode] = str(error)

    def reload_garmin(self) -> None:
        folder = self.config.garmin_dir
        if folder is None:                                  # no folder chosen: the Garmin data is not used
            self.garmin = None
            self.errors.pop("garmin", None)
            return
        try:
            self.garmin = load_garmin(folder)
            self.errors.pop("garmin", None)
        except (FileNotFoundError, ValueError, OSError) as error:
            self.garmin = None
            self.errors["garmin"] = str(error)

    def included(self, mode: str) -> Optional[pd.DataFrame]:
        """All shots of the sessions chosen on the Sessions tab (None if no data is loaded)."""
        shots = self.shots[mode]
        if shots is None:
            return None
        return include_sessions(shots, self.config.excluded_sessions.get(mode, ()))

    def in_bag(self, mode: str) -> pd.DataFrame:
        """Shots of the chosen clubs and intents in every loaded session, selected or not."""
        shots = self.shots[mode]
        if shots is None:
            return pd.DataFrame()
        return select_bag(shots, self.config.bag[mode], full_swing_first=True)

    def selected(self, mode: str) -> pd.DataFrame:
        """Shots of the chosen sessions, limited to the clubs and intents chosen for `mode`, in card order."""
        shots = self.included(mode)
        if shots is None:
            return pd.DataFrame()
        return select_bag(shots, self.config.bag[mode], full_swing_first=True)


def clean(value):
    """Make a value JSON-safe: NaN becomes None, numpy and date types become plain Python."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if not math.isfinite(value) else round(float(value), 4)
    if isinstance(value, (date, pd.Timestamp)):
        return str(value)[:10]
    if value is pd.NA or value is pd.NaT:
        return None
    return value


# --- loading data ---------------------------------------------------------------------

def dataset_info(state: AppState) -> Dict:
    info = {}
    for mode in MODES:
        shots = state.shots[mode]
        folder = state.config.data_dir(mode)
        if folder is None:
            info[mode] = {"folder": "", "enabled": False, "loaded": False, "error": ""}
            continue
        if shots is None:
            info[mode] = {"folder": str(folder), "enabled": True, "loaded": False, "error": state.errors.get(mode, "")}
            continue
        if mode == "stack":
            problems, extra = unreadable_weights(shots), pd.DataFrame()
        else:
            problems, extra = unparsed_labels(shots), unlisted_clubs(shots, state.config.bag[mode])
        info[mode] = {
            "folder": str(folder), "enabled": True, "loaded": True,
            "files": int(shots["source_file"].nunique()), "shots": int(len(shots)),
            "sessions": int(shots["session_date"].nunique()),
            "sessions_selected": int(state.included(mode)["session_date"].nunique()),
            "last_session": str(shots["session_date"].max()),
            "unreadable": problems.to_dict("records"),
            "not_in_bag": extra.to_dict("records"),
        }
    garmin_folder = state.config.garmin_dir
    if garmin_folder is None:
        info["garmin"] = {"folder": "", "enabled": False, "loaded": False, "error": ""}
    elif state.garmin is None:
        info["garmin"] = {"folder": str(garmin_folder), "enabled": True, "loaded": False, "error": state.errors.get("garmin", "")}
    else:
        info["garmin"] = {"folder": str(garmin_folder), "enabled": True, "loaded": True, **describe_garmin(state.garmin)}
    return clean(info)


def set_folders(state: AppState, folders: Dict[str, Optional[str]]) -> Dict:
    """Choose the data folders. `folders` maps a kind of data to its folder.

    An empty value means: no data of this kind (the folder is left empty on purpose).
    A kind that is not in `folders` keeps its folder.
    """
    patch = {}
    for mode in FOLDER_KINDS:
        if mode not in folders or folders[mode] is None:
            continue
        value = str(folders[mode]).strip()
        if value == "":
            patch[f"{mode}_dir"] = ""
            continue
        folder = Path(value).expanduser()
        if not folder.is_dir():
            raise ValueError(f"{value} is not a folder")
        if mode == "garmin":
            find_export_folders(folder)                       # raises if this is not a Garmin export
        elif not (bool(stack_files(folder)) if mode == "stack" else any(folder.glob("*.csv"))):
            raise ValueError(f"No CSV files found in {value}")
        patch[f"{mode}_dir"] = str(folder)
    with state.lock:
        if patch:
            update_local_settings(state.config, patch)
        state.reload_config()
        state.reload_data()
    return dataset_info(state)


def browse_folder(initial: str = "") -> Optional[str]:
    """Show the Windows folder dialog (in its own process) and return the chosen folder."""
    code = (
        "import sys, tkinter\n"
        "from tkinter import filedialog\n"
        "root = tkinter.Tk(); root.withdraw(); root.attributes('-topmost', True)\n"
        "print(filedialog.askdirectory(initialdir=sys.argv[1] or None, title='Select the data folder'))\n"
    )
    result = subprocess.run([sys.executable, "-c", code, initial], capture_output=True, text=True, timeout=300)
    chosen = result.stdout.strip()
    return chosen or None


# --- shared pieces ----------------------------------------------------------------------

def sessions_of(df: pd.DataFrame) -> List[str]:
    """Session dates of a table, newest first."""
    if df.empty:
        return []
    return [str(d) for d in sorted(df["session_date"].unique(), reverse=True)]


def _history(state: AppState, mode: str, label: str, session: date, how: str) -> pd.DataFrame:
    """The shots of one club that the session `session` is compared with, see BASELINE_CHOICES."""
    if how == "selected":
        pool = state.selected(mode)
        pool = pool[pool["label"] == label]
        return pool[pool["session_date"] != session]
    pool = state.in_bag(mode)
    return _baseline(pool[pool["label"] == label], session, how)


def _baseline(df_label: pd.DataFrame, session: date, how: str) -> pd.DataFrame:
    earlier = df_label[df_label["session_date"] < session]
    dates = sorted(earlier["session_date"].unique())
    count = BASELINE_CHOICES.get(how, 4)
    if count is not None:
        dates = dates[-count:]
    return earlier[earlier["session_date"].isin(dates)]


def _parse_day(text: str) -> date:
    return date.fromisoformat(text)


def _change(current, before, what: str, state: AppState) -> Dict:
    """Session minus earlier sessions: estimate, 95% interval and verdict (exact small-sample tests)."""
    s = state.config.stats
    result = compare_normal(current, before, what, level=s.ci_level, min_n=s.min_shots_session)
    return {"est": result.estimate, "lo": result.low, "hi": result.high, "dir": result.direction}


def _measure(values: pd.Series) -> Dict:
    v = values.dropna().to_numpy(dtype=float)
    return {
        "n": len(v),
        "mean": float(np.mean(v)) if len(v) else float("nan"),
        "sd": float(np.std(v, ddof=1)) if len(v) > 1 else float("nan"),
    }


def review(state: AppState, mode: str, session: str, baseline: str, measures: Dict[str, str], key: str) -> Dict:
    """One row per club (and intent): the session against the sessions before it.

    `measures` maps a name to a column. `key` is the measure whose spread decides
    the verdict ('tighter' / 'similar' / 'broader' / too few shots).
    """
    df = state.selected(mode)
    day = _parse_day(session)
    rows = []
    for label, group in (df.groupby("label", sort=False) if not df.empty else []):
        now = group[group["session_date"] == day]
        if now.empty:
            continue
        before = _history(state, mode, label, day, baseline)
        first = now.iloc[0]
        row = {
            "label": label, "club": f"{first['club']} {first['variant'] or ''}".strip(), "intent": int(first["intent"]),
            "n": int(len(now)), "n_before": int(len(before)), "measures": {},
        }
        for name, column in measures.items():
            cur, prev = now[column].dropna(), before[column].dropna()
            entry = _measure(now[column])
            entry["before"] = _measure(before[column])
            entry["d_mean"] = _change(cur, prev, "mean", state)
            entry["d_sd"] = _change(cur, prev, "sd", state)
            row["measures"][name] = entry
        row["verdict"] = row["measures"][key]["d_sd"]["dir"]
        rows.append(row)

    verdicts = [r["verdict"] for r in rows]
    return clean({
        "session": session, "baseline": baseline, "rows": rows,
        "kpi": {
            "shots": int(sum(r["n"] for r in rows)), "clubs": len(rows),
            "tighter": verdicts.count(-1), "broader": verdicts.count(1),
        },
    })


# --- full swing ---------------------------------------------------------------------------

def swing_overview(state: AppState) -> Dict:
    df = state.selected("swing")
    labels = list(dict.fromkeys(df["label"])) if not df.empty else []
    return clean({
        "sessions": sessions_of(df), "labels": labels, "loaded": state.shots["swing"] is not None,
        "measures": series_menu(),
    })


def swing_review(state: AppState, session: str, baseline: str = "last4") -> Dict:
    return review(
        state, "swing", session, baseline,
        {"carry": "carry_m", "lateral": "lateral_m"}, key="carry",
    )


# What the progress charts can show: key -> (column, statistic, title, group in the menu).
# The first two are the fixed charts; the rest fill the pull-down menu of the third chart.
SERIES = {
    "carry_mean": ("carry_m", "mean", "Mean carry (m)", None),
    "club_speed": ("club_speed_mph", "mean", "Club head speed (mph)", None),
    "carry_sd": ("carry_m", "sd", "Carry spread, sd (m)", "Distribution"),
    "lat_sd": ("lateral_m", "sd", "Lateral spread, sd (m)", "Distribution"),
    "lat_mean": ("lateral_m", "mean", "Lateral mean (m, negative = left)", "Distribution"),
    "ball_speed": ("ball_speed_mph", "mean", "Ball speed (mph)", "Ball flight"),
    "smash": ("smash", "mean", "Smash factor", "Ball flight"),
    "spin": ("spin_rpm", "mean", "Spin (rpm)", "Ball flight"),
    "launch_v": ("launch_v_deg", "mean", "Launch angle (deg)", "Ball flight"),
    "descent": ("descent_v_deg", "mean", "Descent angle (deg)", "Ball flight"),
    "height": ("height_m", "mean", "Peak height (m)", "Ball flight"),
    "flight_time": ("flight_time_s", "mean", "Flight time (s)", "Ball flight"),
    "spin_axis": ("spin_axis_deg", "mean", "Spin axis (deg, negative = left)", "Ball flight"),
    "club_speed_sd": ("club_speed_mph", "sd", "Club head speed spread, sd (mph)", "Club"),
    "aoa": ("aoa_deg", "mean", "Angle of attack (deg)", "Club"),
    "club_path": ("club_path_deg", "mean", "Club path (deg, negative = left)", "Club"),
    "dynamic_loft": ("dynamic_loft_deg", "mean", "Dynamic loft (deg)", "Club"),
    "spin_loft": ("spin_loft_deg", "mean", "Spin loft (deg)", "Club"),
}


def series_menu() -> List[Dict]:
    """The measures offered in the pull-down menu of the third progress chart."""
    return [{"key": key, "title": title, "group": group} for key, (_, _, title, group) in SERIES.items() if group]


def series(state: AppState, mode: str, label: str, measure: str) -> Dict:
    """One measure per session for one club, with 95% intervals (mean or spread, see SERIES).

    `dates` lists every selected session, so the charts show the same sessions for every club;
    `sessions` only holds the sessions in which this club was hit.
    """
    if measure not in SERIES:
        raise ValueError(f"Unknown measure: {measure}")
    column, kind, title, _ = SERIES[measure]
    if mode == "pitching" and column == "carry_m":
        title = title.replace("(m)", "(m, simulated)")      # indoor carry is only a simulation
    df = state.selected(mode)
    included = state.included(mode)
    dates = sorted({str(d) for d in included["session_date"]}) if included is not None else []
    if df.empty:
        return {"label": label, "title": title, "dates": dates, "sessions": []}
    group = df[df["label"] == label]
    summary = session_summary(group, column, by=["label"], level=state.config.stats.ci_level)
    sessions = [{
        "date": row["session_date"], "n": row["n"],
        "y": row[kind], "lo": row[f"{kind}_lo"], "hi": row[f"{kind}_hi"],
    } for _, row in summary.iterrows()]
    return clean({"label": label, "title": title, "dates": dates, "sessions": sessions})


def _ring(x: np.ndarray, y: np.ndarray, coverage: float, state: AppState, grid: int = 90) -> List[List[float]]:
    """Outline of the region holding `coverage` of the shots, as [[lateral, carry], ...]."""
    import contourpy

    s = state.config.stats
    try:
        model = fit_bivariate(x, y, min_n_skew=s.min_shots_skew, alpha=s.skew_alpha)
        level = model.density_level(coverage, n=40_000, seed=s.seed)
        xs = np.linspace(model.x.ppf(0.0005), model.x.ppf(0.9995), grid)
        ys = np.linspace(model.y.ppf(0.0005), model.y.ppf(0.9995), grid)
        xx, yy = np.meshgrid(xs, ys)
        lines = contourpy.contour_generator(xs, ys, model.pdf(xx, yy)).lines(level)
    except (ValueError, FloatingPointError, np.linalg.LinAlgError):
        return []
    if len(lines) == 0:
        return []
    longest = max(lines, key=len)
    return np.round(longest, 2).tolist()


def dispersion(state: AppState, mode: str, label: str, session: str, compare: str = "last4") -> Dict:
    """This session's shots against the shots before, with the 68% and 95% regions."""
    df = state.selected(mode)
    if df.empty:
        raise ValueError(f"No {mode} data is loaded")
    group = df[(df["label"] == label)].dropna(subset=["carry_m", "lateral_m"])
    day = _parse_day(session)
    now = group[group["session_date"] == day]

    before = _history(state, mode, label, day, compare).dropna(subset=["carry_m", "lateral_m"])

    def points(frame):
        return {"lateral": frame["lateral_m"].round(2).tolist(), "carry": frame["carry_m"].round(2).tolist()}

    def stats_of(frame):
        return {
            "n": len(frame),
            "carry_mean": frame["carry_m"].mean(), "carry_sd": frame["carry_m"].std(ddof=1),
            "lat_mean": frame["lateral_m"].mean(), "lat_sd": frame["lateral_m"].std(ddof=1),
        }

    min_ring = state.config.stats.min_shots_session
    out = {"label": label, "session": session, "now": points(now), "before": points(before),
           "now_stats": stats_of(now), "before_stats": stats_of(before), "rings": {}, "sessions": []}
    for name, frame in (("now", now), ("before", before)):
        if len(frame) >= min_ring:
            x, y = frame["lateral_m"].to_numpy(), frame["carry_m"].to_numpy()
            out["rings"][name] = {"68": _ring(x, y, COVERAGE_1S, state), "95": _ring(x, y, COVERAGE_2S, state)}

    s = state.config.stats
    for earlier_day, frame in before.groupby("session_date"):
        if len(frame) >= min_ring:
            ring = _ring(frame["lateral_m"].to_numpy(), frame["carry_m"].to_numpy(), COVERAGE_1S, state, grid=60)
            if ring:
                out["sessions"].append({"date": str(earlier_day), "ring": ring})

    carry = _change(now["carry_m"], before["carry_m"], "sd", state)
    lateral = _change(now["lateral_m"], before["lateral_m"], "sd", state)
    out["verdict"] = {"carry": carry["dir"], "lateral": lateral["dir"]}
    return clean(out)


# --- pitching ------------------------------------------------------------------------------

def pitching_overview(state: AppState) -> Dict:
    df = state.selected("pitching")
    labels = list(dict.fromkeys(df["label"])) if not df.empty else []
    choices = []
    if not df.empty:
        base = club_variant(df)
        for club in dict.fromkeys(base):
            intents = sorted(df[base == club]["intent"].unique(), reverse=True)
            choices.append({"club": club, "intents": [int(i) for i in intents]})
    return clean({
        "sessions": sessions_of(df), "labels": labels, "choices": choices,
        "loaded": state.shots["pitching"] is not None, "measures": series_menu(),
        "shot_measures": shot_measure_menu(),
    })


def pitching_review(state: AppState, session: str, baseline: str = "last4") -> Dict:
    return review(
        state, "pitching", session, baseline,
        {"speed": "club_speed_mph", "carry": "carry_m", "lateral": "lateral_m"}, key="speed",
    )


def _selection_shots(state: AppState, mode: str) -> pd.DataFrame:
    """Shots with a carry and a lateral value from the selected sessions, clubs and intents."""
    df = state.selected(mode)
    if df.empty:
        return pd.DataFrame(columns=["label", "carry_m", "lateral_m"])
    return df.dropna(subset=["carry_m", "lateral_m"])


def straightness(state: AppState) -> Dict:
    """Lateral miss of each selected wedge and intent over the selected sessions."""
    window = _selection_shots(state, "pitching")
    s = state.config.stats
    rows = []
    for label, group in window.groupby("label", sort=False):
        info = describe(group["lateral_m"], s)
        rows.append({
            "label": label, "n": info["n"], "short": info["n"] < s.min_shots,
            "mean": info["mean"], "sd": info["sd"], "lo68": info["lo68"], "hi68": info["hi68"],
            "lo95": info["lo95"], "hi95": info["hi95"],
            "rms": math.sqrt(info["mean"] ** 2 + info["sd"] ** 2) if info["n"] > 1 else float("nan"),
        })
    return clean({"rows": rows})


def ladder(state: AppState, target: float, tolerance: float) -> Dict:
    """Which wedge and intent is most likely to finish within `tolerance` of `target` (carry)."""
    window = _selection_shots(state, "pitching")
    s = state.config.stats
    rows = []
    for label, group in window.groupby("label", sort=False):
        carry = group["carry_m"].to_numpy(dtype=float)
        if len(carry) < 3:
            continue
        fit = fit_univariate(carry, min_n_skew=s.min_shots_skew, alpha=s.skew_alpha)
        lateral = describe(group["lateral_m"], s)
        rows.append({
            "label": label, "n": len(carry), "short": len(carry) < s.min_shots,
            "mean": fit.mean, "sd": fit.sd, "lat_sd": lateral["sd"],
            "chance": fit.prob_between(target - tolerance, target + tolerance),
        })
    rows.sort(key=lambda r: -r["chance"])
    return clean({"target": target, "tolerance": tolerance, "rows": rows[:8]})


# --- two measures against each other -----------------------------------------------------------------

# Per-shot measures for the scatter plot: key -> (column, title, group in the menus).
SHOT_MEASURES = {
    "carry": ("carry_m", "Carry (m, simulated)", "Distance"),
    "lateral": ("lateral_m", "Lateral (m, negative = left)", "Distance"),
    "roll": ("roll_m", "Roll (m)", "Distance"),
    "total": ("total_m", "Total distance (m)", "Distance"),
    "club_speed": ("club_speed_mph", "Club head speed (mph)", "Club"),
    "aoa": ("aoa_deg", "Angle of attack (deg)", "Club"),
    "club_path": ("club_path_deg", "Club path (deg, negative = left)", "Club"),
    "dynamic_loft": ("dynamic_loft_deg", "Dynamic loft (deg)", "Club"),
    "spin_loft": ("spin_loft_deg", "Spin loft (deg)", "Club"),
    "low_point": ("low_point_cm", "Low point (cm)", "Club"),
    "impact_lateral": ("lateral_impact_mm", "Impact, lateral (mm)", "Club"),
    "impact_vertical": ("vertical_impact_mm", "Impact, vertical (mm)", "Club"),
    "ball_speed": ("ball_speed_mph", "Ball speed (mph)", "Ball flight"),
    "smash": ("smash", "Smash factor", "Ball flight"),
    "spin": ("spin_rpm", "Spin (rpm)", "Ball flight"),
    "spin_axis": ("spin_axis_deg", "Spin axis (deg, negative = left)", "Ball flight"),
    "launch_v": ("launch_v_deg", "Launch angle (deg)", "Ball flight"),
    "descent": ("descent_v_deg", "Descent angle (deg)", "Ball flight"),
    "height": ("height_m", "Peak height (m)", "Ball flight"),
    "flight_time": ("flight_time_s", "Flight time (s)", "Ball flight"),
}


def shot_measure_menu() -> List[Dict]:
    return [{"key": key, "title": title, "group": group} for key, (_, title, group) in SHOT_MEASURES.items()]


def scatter(state: AppState, club: str, x: str, y: str) -> Dict:
    """Every shot of one wedge (all its selected intents, all selected sessions): measure `x` against `y`.

    The shots come back grouped by intent so the page can colour them. `fit` is one straight line
    through all the plotted shots (least squares) with its correlation, or None if there is no line to draw.
    """
    for key in (x, y):
        if key not in SHOT_MEASURES:
            raise ValueError(f"Unknown measure: {key}")
    (x_col, x_title, _), (y_col, y_title, _) = SHOT_MEASURES[x], SHOT_MEASURES[y]
    df = state.selected("pitching")
    groups = []
    xs, ys = [], []
    if not df.empty:
        frame = df[club_variant(df) == club].dropna(subset=[x_col, y_col])
        for intent in sorted(frame["intent"].unique(), reverse=True):
            part = frame[frame["intent"] == intent]
            groups.append({
                "intent": int(intent), "name": "full" if int(intent) == FULL_SWING else str(int(intent)),
                "x": part[x_col].round(3).tolist(), "y": part[y_col].round(3).tolist(),
                "dates": [str(d) for d in part["session_date"]],
            })
            xs += part[x_col].tolist()
            ys += part[y_col].tolist()
    return clean({
        "club": club, "x": {"key": x, "title": x_title}, "y": {"key": y, "title": y_title},
        "groups": groups, "fit": _line_fit(np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)),
    })


def _line_fit(x: np.ndarray, y: np.ndarray) -> Optional[Dict]:
    """Least-squares line y = slope * x + intercept and the correlation r (None if it is undefined)."""
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    return {"slope": float(slope), "intercept": float(intercept), "r": float(np.corrcoef(x, y)[0, 1]), "n": int(len(x))}


# --- stack training -------------------------------------------------------------------------

def stack_overview(state: AppState) -> Dict:
    """The selected stack sessions and the weights used in them (heaviest first)."""
    shots = state.included("stack")
    if shots is None:
        return {"loaded": False, "sessions": [], "weights": []}
    usable = shots.dropna(subset=["weight_g", "club_speed_mph"])
    return clean({
        "loaded": True, "sessions": sessions_of(usable),
        "weights": sorted(usable["weight_g"].unique(), reverse=True),
    })


def stack_progress(state: AppState) -> Dict:
    """Club head speed per session, one series per weight.

    `dates` lists every selected session; a weight has a point only in the sessions in which it was used.
    Each point is the average speed of all swings with that weight in the session, with its 95% interval.
    """
    shots = state.included("stack")
    if shots is None:
        return {"dates": [], "series": []}
    usable = shots.dropna(subset=["weight_g", "club_speed_mph"])
    dates = sorted({str(d) for d in usable["session_date"]})
    summary = session_summary(usable, "club_speed_mph", by=["weight_g"], level=state.config.stats.ci_level)
    series = []
    for weight, group in summary.groupby("weight_g"):
        points = {str(row["session_date"]): row for _, row in group.iterrows()}
        series.append({
            "weight": float(weight), "name": f"{weight:g} g",
            "y": [points[d]["mean"] if d in points else None for d in dates],
            "lo": [points[d]["mean_lo"] if d in points else None for d in dates],
            "hi": [points[d]["mean_hi"] if d in points else None for d in dates],
            "n": [int(points[d]["n"]) if d in points else None for d in dates],
        })
    series.sort(key=lambda item: -item["weight"])
    return clean({"dates": dates, "series": series})


# --- Garmin: what goes with a good session -----------------------------------------------------

# result key -> (menu title, kind of practice data it needs)
OUTCOMES = {
    "stack_speed": ("Stack training: speed", "stack"),
    "swing_speed": ("Full swing: club head speed", "swing"),
    "swing_spread": ("Full swing: carry spread", "swing"),
}


def _garmin_ready(state: AppState, outcome: str) -> None:
    if state.garmin is None:
        raise ValueError("No Garmin data is loaded")
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown result: {outcome}")
    needed = OUTCOMES[outcome][1]
    if state.included(needed) is None:
        raise ValueError(f"No {needed} data is loaded")


def garmin_overview(state: AppState) -> Dict:
    """What the correlation tab can offer: the results, the Garmin measures and the clubs."""
    if state.garmin is None:
        return {"loaded": False, "outcomes": [], "predictors": [], "clubs": []}
    available = {kind: state.included(kind) is not None for kind in ("swing", "stack")}
    swing = state.selected("swing")
    return clean({
        "loaded": True,
        "outcomes": [{"key": key, "title": title, "source": source} for key, (title, source) in OUTCOMES.items() if available[source]],
        "predictors": [{"key": key, "title": title, "group": group} for key, (title, group) in PREDICTORS.items()],
        "clubs": list(dict.fromkeys(swing["label"])) if not swing.empty else [],
        "timezone": state.config.timezone,
    })


def _session_results(state: AppState, outcome: str, club: Optional[str], detrend: bool):
    """One result per session (see golf.stats.outcomes), the local time of each session's first swing, and a title."""
    _garmin_ready(state, outcome)
    if outcome == "stack_speed":
        shots = state.included("stack").dropna(subset=["weight_g", "club_speed_mph"])
        results = stack_speed(shots, detrend=detrend)
        reference = f"{results['weight'].iloc[0]:g} g" if not results.empty else "one weight"
        title = (f"Stack speed compared with the trend, at {reference} (mph)" if detrend else f"Stack speed at {reference} (mph)")
    else:
        shots = state.selected("swing")
        if club and club not in set(shots["label"]):
            raise ValueError(f"Unknown club: {club}")
        what, function = ("Club head speed", swing_speed) if outcome == "swing_speed" else ("Carry spread", swing_spread)
        results = function(shots, detrend=detrend, club=club or None)
        title = f"{what} compared with the {'trend' if detrend else 'usual'} (%)" + (f", {club}" if club else "")
    starts = shots.groupby("session_date")["timestamp"].min()
    return results, starts, title


def _joined(state: AppState, outcome: str, club: Optional[str], detrend: bool):
    results, starts, title = _session_results(state, outcome, club, detrend)
    if results.empty:
        return pd.DataFrame(), title
    context = session_context(starts.loc[results["date"]], state.garmin, state.config.timezone)
    joined = results.set_index("date").join(context)
    return joined, title


def garmin_table(state: AppState, outcome: str, club: Optional[str] = None, detrend: bool = True) -> Dict:
    """Every Garmin measure against one result: the correlation and how uncertain it is."""
    joined, title = _joined(state, outcome, club, detrend)
    level = state.config.stats.ci_level
    rows = []
    for key, (name, group) in PREDICTORS.items():
        c = correlate(joined[key], joined["value"], level=level) if not joined.empty else None
        valid = int(joined[key].notna().sum()) if not joined.empty else 0
        rows.append({
            "key": key, "title": name, "group": group, "n": c.n if c else valid,
            "r": c.r if c else None, "low": c.low if c else None, "high": c.high if c else None,
        })
    rows.sort(key=lambda row: (row["r"] is None, -abs(row["r"] or 0.0)))
    tested = [row for row in rows if row["r"] is not None]
    return clean({
        "title": title, "sessions": int(len(joined)), "rows": rows, "level": level,
        "tested": len(tested), "clear": sum(1 for row in tested if row["low"] > 0 or row["high"] < 0),
    })


def garmin_scatter(state: AppState, outcome: str, predictor: str, club: Optional[str] = None, detrend: bool = True) -> Dict:
    """One Garmin measure against one result, one dot per session."""
    if predictor not in PREDICTORS:
        raise ValueError(f"Unknown Garmin measure: {predictor}")
    joined, title = _joined(state, outcome, club, detrend)
    points = []
    if not joined.empty:
        used = joined.dropna(subset=[predictor])
        points = [{"date": str(day), "x": row[predictor], "y": row["value"]} for day, row in used.iterrows()]
    c = correlate([p["x"] for p in points], [p["y"] for p in points], level=state.config.stats.ci_level)
    fit = None if c is None else {"n": c.n, "r": c.r, "low": c.low, "high": c.high, "slope": c.slope, "intercept": c.intercept}
    return clean({
        "x_title": PREDICTORS[predictor][0], "y_title": title, "points": points, "fit": fit,
        "sessions": int(len(joined)), "level": state.config.stats.ci_level,
    })


# --- sessions -------------------------------------------------------------------------------------

def get_sessions(state: AppState, mode: str) -> Dict:
    """Every session of the loaded data with its shot count and whether it takes part."""
    shots = state.shots[mode]
    if shots is None:
        return {"loaded": False, "sessions": []}
    excluded = state.config.excluded_sessions.get(mode, frozenset())
    sessions = [dict(row, selected=row["date"] not in excluded) for row in session_table(shots)]
    stats = state.config.stats
    return clean({
        "loaded": True, "sessions": sessions,
        "window_weeks": stats.window_weeks, "fallback_weeks": stats.fallback_weeks,
    })


def set_sessions(state: AppState, mode: str, selected: List[str]) -> Dict:
    """Choose the sessions that take part; sessions added to the folder later take part automatically."""
    shots = state.shots[mode]
    if shots is None:
        raise ValueError(f"No {mode} data is loaded")
    every = {row["date"] for row in session_table(shots)}
    unknown = sorted(set(selected) - every)
    if unknown:
        raise ValueError(f"Not a session in the data: {', '.join(unknown)}")
    if not selected:
        raise ValueError("Select at least one session")
    excluded = sorted(every - set(selected))
    folder = str(state.config.data_dir(mode))
    with state.lock:
        update_local_settings(state.config, {"sessions": {mode: {folder: {"excluded": excluded}}}})
        state.reload_config()
    return get_sessions(state, mode)


# --- bag and wedge selection -------------------------------------------------------------------

def get_bag(state: AppState) -> Dict:
    shots = state.shots["swing"]
    if shots is None:
        return {"clubs": [], "loaded": False}
    selected = set(state.config.bag["swing"].clubs)
    preferred = state.config.default_bag.get("swing", BagSpec(clubs=())).clubs
    clubs = [dict(row, selected=row["club"] in selected) for row in available_clubs(shots, preferred)]
    return clean({"clubs": clubs, "loaded": True})


def set_bag(state: AppState, clubs: List[str]) -> Dict:
    shots = state.shots["swing"]
    known = {row["club"] for row in available_clubs(shots)} if shots is not None else set()
    chosen = [c.strip().lower() for c in clubs]
    unknown = [c for c in chosen if c not in known]
    if unknown:
        raise ValueError(f"Not found in the swing data: {', '.join(unknown)}")
    if not chosen:
        raise ValueError("Select at least one club")
    with state.lock:
        update_local_settings(state.config, {"bag": {"swing": {"clubs": chosen}}})
        state.reload_config()
    return get_bag(state)


def get_wedges(state: AppState) -> Dict:
    shots = state.shots["pitching"]
    if shots is None:
        return {"rows": [], "loaded": False}
    spec = state.config.bag["pitching"]
    preferred = state.config.default_bag.get("pitching", BagSpec(clubs=())).clubs
    selected = set(spec.pairs) if spec.pairs else {(c, i) for c in spec.clubs for i in spec.intents}
    rows = []
    for row in intent_grid(shots, preferred):
        rows.append({
            "club": row["club"], "counts": row["counts"],
            "selected": [i for i in row["counts"] if (row["club"], i) in selected],
        })
    return clean({"rows": rows, "loaded": True})


def set_wedges(state: AppState, pairs: List[List]) -> Dict:
    grid = {row["club"]: row["counts"] for row in intent_grid(state.shots["pitching"])} if state.shots["pitching"] is not None else {}
    clean_pairs = []
    for club, intent in pairs:
        club, intent = club.strip().lower(), int(intent)
        if grid.get(club, {}).get(intent, 0) == 0:
            raise ValueError(f"No shots recorded for {club} at intent {intent}")
        clean_pairs.append([club, intent])
    if not clean_pairs:
        raise ValueError("Select at least one wedge and intent")
    with state.lock:
        update_local_settings(state.config, {"bag": {"pitching": {"pairs": clean_pairs}}})
        state.reload_config()
    return get_wedges(state)


# --- cards ------------------------------------------------------------------------------------------

def make_card(state: AppState, mode: str) -> Dict:
    shots = state.included(mode)
    if shots is None:
        raise ValueError(f"No {mode} data is loaded")
    with state.lock:
        paths, card = generate_card(mode, shots, state.config)
    relative = paths[0].relative_to(state.config.output_dir).as_posix()
    flagged = card[card["status"] != "ok"][["label", "n"]].to_dict("records")
    first = card.iloc[0]
    return clean({
        "file": str(paths[0]), "archive": str(paths[1]), "url": f"/files/{relative}",
        "rows": len(card), "sessions": first["sessions"], "from": first["from"], "as_of": first["as_of"],
        "flagged": flagged,
    })
