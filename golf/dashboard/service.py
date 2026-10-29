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
from golf.data.withings import WithingsData, describe_withings, find_weight_file, load_withings
from golf.data.golfrounds import GolfRounds, describe_golf_rounds, load_golf_rounds
from golf.data.competition import RECORD_NAME, load_record, update_record, with_round_keys
from golf.data import drill as drill_store
from golf.stats import drill as drill_stats
from golf.data.stack import stack_files
from golf.data.labels import FULL_SWING
from golf.report.build import generate_card
from golf.sessions import include_sessions, session_table
from golf.stats import (
    COVERAGE_1S, COVERAGE_2S, compare_normal, describe, fit_bivariate, fit_univariate,
    session_summary,
)
from golf.stats.context import ALL_PREDICTORS, available_predictors, session_context
from golf.stats.correlation import correlate
from golf.stats.daily import DAILY_MEASURES, available_measures, daily_table, rolling_means, windows_for
from golf.stats.difference import mean_difference
from golf.targets import Targets, load_targets
from golf.stats.driver import analyse_driver
from golf.stats.intervals import wilson_interval
from golf.stats.levers import GROUPS as LEVER_GROUPS, MIN_SESSIONS as LEVER_MIN_SESSIONS, MIN_SHOTS as LEVER_MIN_SHOTS, Levers, distance_levers
from golf.stats.outcomes import round_result, stack_speed, swing_spread, swing_speed
from golf.stats.rounds import ROUND_MEASURES, SUMMARY_ROWS, round_stats, rolling_by_round, summarise

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
        self.withings: Optional[WithingsData] = None
        self.golf: Optional[GolfRounds] = None                  # full rounds of the Garmin export
        self.golf_stats: Optional[pd.DataFrame] = None          # one row per round with its statistics
        self.competition: Optional[pd.DataFrame] = None         # the record of competition rounds
        self.competition_notes: List[str] = []                  # things to check after reading the certificates
        self.targets: Targets = Targets()                       # the target files (ranges, the driver chart)
        self.driver_models: Dict = {}                           # fitted driver flight models, by the shots they were fitted to
        self.errors: Dict[str, str] = {}
        self.reload_data()

    def reload_config(self) -> None:
        self.config = load_config(self.config_path)

    def reload_data(self, modes=MODES) -> None:
        self.reload_garmin()
        self.reload_withings()
        self.reload_golf()
        self.reload_competition()
        self.targets = load_targets(self.config.targets_dir)
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

    def reload_golf(self) -> None:
        """The full rounds in the Garmin export. An export without golf data is not an error."""
        folder = self.config.garmin_dir
        self.golf, self.golf_stats = None, None
        self.errors.pop("golf", None)
        if folder is None:
            return
        try:
            golf = load_golf_rounds(folder, self.config.timezone)
        except FileNotFoundError:
            return
        except (ValueError, OSError, KeyError) as error:
            self.errors["golf"] = str(error)
            return
        if len(golf.rounds):
            stats = round_stats(golf.rounds, golf.holes)
            stats["round_key"] = stats["round_id"].astype(str)
            self.golf, self.golf_stats = golf, stats

    def reload_competition(self) -> None:
        """Copy the rounds of the certificates (PDF) into the record, then read the record.

        If a PDF cannot be read (for example pypdf is not installed) the record made so far is still used.
        """
        folder = self.config.competition_dir
        self.competition, self.competition_notes = None, []
        self.errors.pop("competition", None)
        if folder is None:
            return
        try:
            report = update_record(folder)
            self.competition_notes = [f"check: {t}" for t in report.warnings] + [f"not in the record, could not be read: {t}" for t in report.unread]
        except Exception as error:                              # a bad PDF or a missing package must not stop the dashboard
            self.errors["competition"] = str(error)
        try:
            record = load_record(folder)
        except (ValueError, OSError) as error:
            self.errors["competition"] = str(error)
            return
        if len(record):
            self.competition = with_round_keys(record.sort_values(["date", "same_day"]).reset_index(drop=True))

    def reload_withings(self) -> None:
        folder = self.config.withings_dir
        if folder is None:                                  # no folder chosen: the Withings data is not used
            self.withings = None
            self.errors.pop("withings", None)
            return
        try:
            self.withings = load_withings(folder)
            self.errors.pop("withings", None)
        except (FileNotFoundError, ValueError, OSError, pd.errors.ParserError) as error:
            self.withings = None
            self.errors["withings"] = str(error)

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
    competition_folder = state.config.competition_dir
    if competition_folder is None:
        info["competition"] = {"folder": "", "enabled": False, "loaded": False, "error": ""}
    elif state.competition is None:
        info["competition"] = {"folder": str(competition_folder), "enabled": True, "loaded": False, "error": state.errors.get("competition", "")}
    else:
        record = state.competition
        info["competition"] = {
            "folder": str(competition_folder), "enabled": True, "loaded": True, "rounds": int(len(record)),
            "first": str(record["date"].min()), "last": str(record["date"].max()),
            "notes": state.competition_notes, "error": state.errors.get("competition", ""),
        }
    targets_folder = state.config.targets_dir
    if targets_folder is None:
        info["targets"] = {"folder": "", "enabled": False, "loaded": False, "notes": [], "error": ""}
    else:
        info["targets"] = {"folder": str(targets_folder), "enabled": True, "loaded": state.targets.chart is not None or bool(state.targets.attack_angle),
                           "notes": list(state.targets.notes), "error": ""}
    drill_folder = state.config.drill_dir
    if drill_folder is None:
        info["drill"] = {"folder": "", "enabled": False, "loaded": False, "sessions": 0, "error": ""}
    else:
        sessions = drill_store.load_all(drill_folder)
        info["drill"] = {"folder": str(drill_folder), "enabled": True, "loaded": drill_folder.is_dir(),
                         "sessions": int(sessions["session"].nunique()) if len(sessions) else 0, "error": ""}
    info["golf"] = {"enabled": state.config.garmin_dir is not None, "loaded": state.golf is not None, "error": state.errors.get("golf", ""),
                    **(describe_golf_rounds(state.golf) if state.golf is not None else {})}
    withings_folder = state.config.withings_dir
    if withings_folder is None:
        info["withings"] = {"folder": "", "enabled": False, "loaded": False, "error": ""}
    elif state.withings is None:
        info["withings"] = {"folder": str(withings_folder), "enabled": True, "loaded": False, "error": state.errors.get("withings", "")}
    else:
        info["withings"] = {"folder": str(withings_folder), "enabled": True, "loaded": True, **describe_withings(state.withings)}
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
        if mode == "drill":
            folder.mkdir(parents=True, exist_ok=True)                 # the drill folder may be new
        if not folder.is_dir():
            raise ValueError(f"{value} is not a folder")
        if mode == "garmin":
            find_export_folders(folder)                       # raises if this is not a Garmin export
        elif mode == "withings":
            find_weight_file(folder)                          # raises if this is not a Withings export
        elif mode == "competition":
            if not (any(folder.glob("*.pdf")) or (folder / RECORD_NAME).is_file()):
                raise ValueError(f"No handicap certificate (PDF) or {RECORD_NAME} found in {value}")
        elif mode == "drill":
            pass                                                      # any folder: the sessions are written into it
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
        "measures": series_menu("swing"),
    })


# --- distance levers: which factors go with carry, per club ------------------------------------------------

_LEVER_DECIMALS = {"smash": 3, "club_speed_mph": 1, "launch_v_deg": 1, "spin_rpm": 0, "aoa_deg": 1, "dynamic_loft_deg": 1,
                   "club_path_deg": 1, "ftp_deg": 1}


def _lever_cells(levers: Levers) -> List[Dict]:
    return [{"key": f.key, "title": f.title, "unit": f.unit, "lever": f.lever, "mean": f.mean, "sd": f.sd,
             "effect": f.effect, "low": f.low, "high": f.high, "clear": f.clear} for f in levers.factors]


def _lever_verdict(label: str, levers: Levers) -> str:
    """The levers of one view in words: the largest clear one first."""
    clear = sorted((f for f in levers.factors if f.lever and f.clear), key=lambda f: -abs(f.effect))
    if not clear:
        return f"For the {label} no factor has a clear effect on carry in your shots (they matter little, or already sit near their best value)."

    def part(f) -> str:
        sd = f"{f.sd:.{_LEVER_DECIMALS[f.key]}f}" + (f" {f.unit}" if f.unit else "")
        return f"{f.title.split(' (')[0].lower()} (+{abs(f.effect):.1f} m for {sd} {'more' if f.effect > 0 else 'less'})"

    first = clear[0]
    low, high = sorted((abs(first.low), abs(first.high)))
    text = f"Largest lever for the {label}: {part(first)}, 95% interval {low:.1f} to {high:.1f} m."
    if len(clear) > 1:
        text += " Then " + ", ".join(part(f) for f in clear[1:]) + "."
    return text


def _lever_groups(state: AppState, shots: pd.DataFrame, label: str) -> Dict:
    return distance_levers(shots, level=state.config.stats.ci_level)


def swing_levers(state: AppState, label: str) -> Dict:
    """The levers of carry for one club of the selected sessions, in both views."""
    df = state.selected("swing")
    labels = list(dict.fromkeys(df["label"])) if not df.empty else []
    if label not in labels:
        raise ValueError(f"Unknown club: {label}")
    found = _lever_groups(state, df[df["label"] == label], label)
    groups = []
    for key, title, _ in LEVER_GROUPS:
        result = found[key]
        if result is None:
            groups.append({"key": key, "title": title, "ok": False,
                           "reason": f"Needs at least {LEVER_MIN_SHOTS} shots from {LEVER_MIN_SESSIONS} sessions that have all of these factors recorded."})
            continue
        groups.append({"key": key, "title": title, "ok": True, "n": result.n, "sessions": result.sessions, "carry_mean": result.carry_mean,
                       "carry_sd": result.carry_sd, "r2": result.r2, "factors": _lever_cells(result), "verdict": _lever_verdict(label, result)})
    return clean({"label": label, "ok": any(g["ok"] for g in groups), "groups": groups, "level": state.config.stats.ci_level})


def swing_levers_bag(state: AppState) -> Dict:
    """The levers of every club of the selected sessions, for the overview tables."""
    df = state.selected("swing")
    labels = list(dict.fromkeys(df["label"])) if not df.empty else []
    rows = []
    for label in labels:
        found = _lever_groups(state, df[df["label"] == label], label)
        groups = {}
        for key, _, _ in LEVER_GROUPS:
            result = found[key]
            if result is None:
                groups[key] = {"ok": False}
                continue
            biggest = result.biggest()
            groups[key] = {"ok": True, "n": result.n, "sessions": result.sessions, "r2": result.r2,
                           "factors": _lever_cells(result), "biggest": biggest.key if biggest else None}
        rows.append({"label": label, "shots": int((df["label"] == label).sum()), "groups": groups})
    return clean({"rows": rows, "level": state.config.stats.ci_level,
                  "groups": [{"key": key, "title": title, "factors": [{"key": c, "title": ti, "unit": u, "lever": lv} for c, ti, u, lv in factors]}
                             for key, title, factors in LEVER_GROUPS]})


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
    "face_to_path": ("ftp_deg", "mean", "Face to path (deg, negative = left)", "Club"),
    "dynamic_loft": ("dynamic_loft_deg", "mean", "Dynamic loft (deg)", "Club"),
    "spin_loft": ("spin_loft_deg", "mean", "Spin loft (deg)", "Club"),
}


# The delivery measures that have a target range (see golf/targets.py): measure -> kind of range, and the "within the range" share of each.
BAND_MEASURE = {"aoa": "attack_angle", "club_path": "club_path", "face_to_path": "face_to_path", "dynamic_loft": "dynamic_loft"}
IN_RANGE = {
    "aoa_in_range": ("aoa_deg", "attack_angle", "Angle of attack within the target range (% of shots)"),
    "club_path_in_range": ("club_path_deg", "club_path", "Club path within the target range (% of shots)"),
    "face_to_path_in_range": ("ftp_deg", "face_to_path", "Face to path within the target range (% of shots)"),
    "dynamic_loft_in_range": ("dynamic_loft_deg", "dynamic_loft", "Dynamic loft within the target range (% of shots)"),
}


def series_menu(mode: str = "pitching") -> List[Dict]:
    """The measures offered in the pull-down menu of the third progress chart (full swings also get the target ranges)."""
    menu = [{"key": key, "title": title, "group": group} for key, (_, _, title, group) in SERIES.items() if group]
    if mode == "swing":
        menu += [{"key": key, "title": title, "group": "Target ranges"} for key, (_, _, title) in IN_RANGE.items()]
    return menu


def _share(values: pd.Series, band) -> float:
    return float(100.0 * ((values >= band[0]) & (values <= band[1])).mean())


def series(state: AppState, mode: str, label: str, measure: str) -> Dict:
    """One measure per session for one club, with 95% intervals (mean or spread, see SERIES).

    `dates` lists every selected session, so the charts show the same sessions for every club;
    `sessions` only holds the sessions in which this club was hit.
    """
    if measure in IN_RANGE and mode == "swing":
        return _in_range_series(state, label, measure)
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
    band = state.targets.band(BAND_MEASURE[measure], label) if mode == "swing" and measure in BAND_MEASURE else None
    summary = session_summary(group, column, by=["label"], level=state.config.stats.ci_level)
    sessions = [{
        "date": row["session_date"], "n": row["n"],
        "y": row[kind], "lo": row[f"{kind}_lo"], "hi": row[f"{kind}_hi"],
    } for _, row in summary.iterrows()]
    out = {"label": label, "title": title, "dates": dates, "sessions": sessions}
    if band is not None:
        values = group[column].dropna()
        latest = group.dropna(subset=[column])
        last = latest[latest["session_date"] == latest["session_date"].max()][column] if len(latest) else values
        out["target"] = {"low": band[0], "high": band[1], "in_range": _share(values, band) if len(values) else None,
                         "in_range_last": _share(last, band) if len(last) else None, "shots": int(len(values)),
                         "last_session": str(latest["session_date"].max()) if len(latest) else ""}
    return clean(out)


def _in_range_series(state: AppState, label: str, measure: str) -> Dict:
    """Per session, the share of shots of a club inside its target range."""
    column, kind, title = IN_RANGE[measure]
    df = state.selected("swing")
    included = state.included("swing")
    dates = sorted({str(d) for d in included["session_date"]}) if included is not None else []
    band = state.targets.band(kind, label)
    if df.empty or band is None:
        reason = "" if band is not None else f"No target range for {label} in the target files."
        return {"label": label, "title": title, "dates": dates, "sessions": [], "note": reason}
    group = df[df["label"] == label].dropna(subset=[column])
    sessions = []
    for day, shots in group.groupby("session_date"):
        hits = int(((shots[column] >= band[0]) & (shots[column] <= band[1])).sum())
        lo, hi = wilson_interval(hits, len(shots), state.config.stats.ci_level)
        sessions.append({"date": day, "n": len(shots), "y": 100.0 * hits / len(shots), "lo": lo, "hi": hi})
    return clean({"label": label, "title": title, "dates": dates, "sessions": sessions, "percent": True,
                  "target": {"low": band[0], "high": band[1], "in_range": None}})


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
    out["window"] = _dispersion_window(state, pd.concat([now, before]))
    return clean(out)


def _dispersion_window(state: AppState, shots: pd.DataFrame) -> Optional[Dict]:
    """The part of the plane the dispersion plot shows: a fixed span around the average of the shots shown (None without shots).

    The span is the same for every club (`dispersion_carry_m` and `dispersion_lateral_m`), so clubs can be compared by eye.
    `outside` counts the shots that fall outside it.
    """
    if shots.empty:
        return None
    s = state.config.stats
    carry_c, lateral_c = float(shots["carry_m"].mean()), float(shots["lateral_m"].mean())
    carry = [carry_c - s.dispersion_carry_m / 2.0, carry_c + s.dispersion_carry_m / 2.0]
    lateral = [lateral_c - s.dispersion_lateral_m / 2.0, lateral_c + s.dispersion_lateral_m / 2.0]
    inside = shots["carry_m"].between(*carry) & shots["lateral_m"].between(*lateral)
    return {"carry": carry, "lateral": lateral, "span_carry": s.dispersion_carry_m, "span_lateral": s.dispersion_lateral_m,
            "center": {"carry": carry_c, "lateral": lateral_c}, "outside": int((~inside).sum()), "shots": int(len(shots))}


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
    Each point is the average speed of all swings with that weight in the session, with its 95% interval,
    and `max` is the fastest swing with that weight in the session.
    """
    shots = state.included("stack")
    if shots is None:
        return {"dates": [], "series": []}
    usable = shots.dropna(subset=["weight_g", "club_speed_mph"])
    dates = sorted({str(d) for d in usable["session_date"]})
    summary = session_summary(usable, "club_speed_mph", by=["weight_g"], level=state.config.stats.ci_level)
    fastest = {(str(s), float(w)): float(v) for (s, w), v in usable.groupby(["session_date", "weight_g"])["club_speed_mph"].max().items()}
    series = []
    for weight, group in summary.groupby("weight_g"):
        points = {str(row["session_date"]): row for _, row in group.iterrows()}
        series.append({
            "weight": float(weight), "name": f"{weight:g} g",
            "y": [points[d]["mean"] if d in points else None for d in dates],
            "max": [fastest[(d, float(weight))] if d in points else None for d in dates],
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
    "comp_differential": ("Competition rounds: score differential", "competition"),
    "round_differential": ("Garmin rounds: score differential", "rounds"),
    "round_fir": ("Garmin rounds: fairways hit (%)", "rounds"),
    "round_gir": ("Garmin rounds: greens in regulation (%)", "rounds"),
    "round_putts": ("Garmin rounds: putts per hole", "rounds"),
}
ROUND_OUTCOME_COLUMN = {"comp_differential": "differential", "round_differential": "differential",
                        "round_fir": "fir_pct", "round_gir": "gir_pct", "round_putts": "putts_per_hole"}
COMPETITION_START_HOUR = 9      # the certificate has no start time: a round is taken to start at 9:00


def _garmin_ready(state: AppState, outcome: str) -> None:
    if state.garmin is None and state.withings is None:
        raise ValueError("No Garmin or Withings data is loaded")
    if outcome not in OUTCOMES:
        raise ValueError(f"Unknown result: {outcome}")
    needed = OUTCOMES[outcome][1]
    if not _has_results(state, needed):
        raise ValueError(f"No {'Garmin round' if needed == 'rounds' else needed} data is loaded")


def _has_results(state: AppState, kind: str) -> bool:
    """Whether the data that a result needs is loaded: practice data, the record of competition rounds, or Garmin rounds."""
    if kind == "competition":
        return state.competition is not None
    if kind == "rounds":
        return state.golf_stats is not None
    return state.included(kind) is not None


def garmin_overview(state: AppState) -> Dict:
    """What the correlation tab can offer: the results, the Garmin measures and the clubs."""
    measures = available_measures(state.garmin, state.withings)
    if not measures:
        return {"loaded": False, "outcomes": [], "predictors": [], "clubs": [], "daily": []}
    swing = state.selected("swing")
    garmin = state.garmin is not None                       # the sleep comparison needs the watch
    available = {kind: _has_results(state, kind) for kind in ("swing", "stack", "competition", "rounds")}
    table = _health_table(state)
    return clean({
        "loaded": True,
        "outcomes": [{"key": key, "title": title, "source": source} for key, (title, source) in OUTCOMES.items() if available[source]],
        "predictors": [{"key": key, "title": title, "group": group} for key, (title, group) in available_predictors(state.garmin, state.withings).items()],
        "daily": [{"key": key, "title": title, "group": group} for key, (title, group) in measures.items()],
        "days": list(PAIR_DAYS),
        "years": sorted({d.year for d in table.index}, reverse=True),
        "training_sleep": garmin,
        "clubs": list(dict.fromkeys(swing["label"])) if not swing.empty else [],
        "timezone": state.config.timezone,
    })


def _session_results(state: AppState, outcome: str, club: Optional[str], detrend: bool):
    """One result per session (see golf.stats.outcomes), the local time of each session's first swing, and a title."""
    _garmin_ready(state, outcome)
    if outcome in ROUND_OUTCOME_COLUMN:
        return _round_results(state, outcome, detrend)
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


def _round_results(state: AppState, outcome: str, detrend: bool):
    """One result per day played from the rounds, the local time of each day's first round, and a title."""
    column = ROUND_OUTCOME_COLUMN[outcome]
    if outcome == "comp_differential":
        record = included_rounds(state, "competition")
        table = pd.DataFrame({"date": record["date"].astype(str), "value": record["differential"]})
        starts = pd.Series({day: pd.Timestamp(day) + pd.Timedelta(hours=COMPETITION_START_HOUR) for day in dict.fromkeys(table["date"])})
    else:
        stats = included_rounds(state, "garmin")
        table = pd.DataFrame({"date": stats["date"].astype(str), "value": stats[column]})
        local = stats["start_utc"].dt.tz_convert(state.config.timezone).dt.tz_localize(None)
        starts = pd.Series(local.to_numpy(), index=stats["date"].astype(str)).groupby(level=0).first().map(pd.Timestamp)
    results = round_result(table, detrend=detrend)
    what = OUTCOMES[outcome][0].split(": ", 1)[1]
    label = what[0].upper() + what[1:]
    title = f"{label} compared with the trend" if detrend else label
    return results, starts, title


def _joined(state: AppState, outcome: str, club: Optional[str], detrend: bool):
    results, starts, title = _session_results(state, outcome, club, detrend)
    if results.empty:
        return pd.DataFrame(), title
    context = session_context(starts.loc[results["date"]], state.garmin, state.config.timezone, state.withings)
    joined = results.set_index("date").join(context)
    return joined, title


def garmin_table(state: AppState, outcome: str, club: Optional[str] = None, detrend: bool = True) -> Dict:
    """Every Garmin measure against one result: the correlation and how uncertain it is."""
    joined, title = _joined(state, outcome, club, detrend)
    level = state.config.stats.ci_level
    rows = []
    for key, (name, group) in available_predictors(state.garmin, state.withings).items():
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
    if predictor not in ALL_PREDICTORS:
        raise ValueError(f"Unknown measure: {predictor}")
    if state.garmin is None and state.withings is None:
        raise ValueError("No Garmin or Withings data is loaded")
    if predictor not in available_predictors(state.garmin, state.withings):
        raise ValueError(f"{ALL_PREDICTORS[predictor][0]} needs data that is not loaded")
    joined, title = _joined(state, outcome, club, detrend)
    points = []
    if not joined.empty:
        used = joined.dropna(subset=[predictor])
        points = [{"date": str(day), "x": row[predictor], "y": row["value"]} for day, row in used.iterrows()]
    c = correlate([p["x"] for p in points], [p["y"] for p in points], level=state.config.stats.ci_level)
    fit = None if c is None else {"n": c.n, "r": c.r, "low": c.low, "high": c.high, "slope": c.slope, "intercept": c.intercept}
    return clean({
        "x_title": ALL_PREDICTORS[predictor][0], "y_title": title, "points": points, "fit": fit,
        "sessions": int(len(joined)), "level": state.config.stats.ci_level,
    })


PAIR_DAYS = (90, 365)           # the "last N days" choices of the nightly plot; a calendar year is chosen as "year:2024"


def _in_period(table: pd.DataFrame, period: str) -> pd.DataFrame:
    """The nights of `table` (indexed by date) in a period: "all", "days:N" (counted back from the latest night) or "year:YYYY"."""
    kind, _, value = period.partition(":")
    if period == "all":
        return table
    if kind == "days" and value.isdigit() and int(value) in PAIR_DAYS:
        dates = pd.to_datetime(table.index)
        return table[dates > dates.max() - pd.Timedelta(days=int(value))] if len(table) else table
    if kind == "year" and value.isdigit():
        return table[pd.to_datetime(table.index).year == int(value)] if len(table) else table
    raise ValueError(f"Unknown period: {period}")


def _health_ready(state: AppState, measures) -> None:
    """Raise if no health data is loaded or one of the measures is unknown or not available from the loaded data."""
    available = available_measures(state.garmin, state.withings)
    if not available:
        raise ValueError("No Garmin or Withings data is loaded")
    for key in measures:
        if key not in DAILY_MEASURES:
            raise ValueError(f"Unknown measure: {key}")
        if key not in available:
            raise ValueError(f"{DAILY_MEASURES[key][0]} needs data that is not loaded")


def _health_table(state: AppState) -> pd.DataFrame:
    return daily_table(state.garmin, state.config.timezone, state.withings)


def health_trend(state: AppState, measure: str, period: str = "all") -> Dict:
    """One measure over time with its short and long average (every night or weighing of the exports)."""
    _health_ready(state, (measure,))
    table = _in_period(_health_table(state), period)
    windows, minimum = windows_for(measure)
    series = table[measure].dropna() if len(table) else pd.Series(dtype=float)
    means = rolling_means(series, windows, minimum)
    points = [{"date": str(day), "value": value, "short": means.loc[day, "short"], "long": means.loc[day, "long"]} for day, value in series.items()]
    latest = {"short": means["short"].iloc[-1], "long": means["long"].iloc[-1], "all": series.mean()} if len(series) else None
    return clean({"title": DAILY_MEASURES[measure][0], "points": points, "latest": latest, "days": int(len(table)), "windows": list(windows)})


def garmin_pair(state: AppState, x: str, y: str, period: str = "all") -> Dict:
    """Two health measures against each other, one dot per day (every day of the exports, not only practice days)."""
    _health_ready(state, (x, y))
    table = _in_period(_health_table(state), period)
    used = table.dropna(subset=[x, y]) if not table.empty else table
    points = [{"date": str(day), "x": row[x], "y": row[y]} for day, row in used.iterrows()]
    c = correlate([p["x"] for p in points], [p["y"] for p in points], level=state.config.stats.ci_level)
    fit = None if c is None else {"n": c.n, "r": c.r, "low": c.low, "high": c.high, "slope": c.slope, "intercept": c.intercept}
    return clean({
        "x_title": DAILY_MEASURES[x][0], "y_title": DAILY_MEASURES[y][0], "points": points, "fit": fit,
        "days": int(len(table)), "level": state.config.stats.ci_level,
        "first": points[0]["date"] if points else "", "last": points[-1]["date"] if points else "",
    })


# How the night after a strength session shortly before bed differs from other nights.
TRAINING_GROUPS = (
    ("none", "No strength training in the 12 h before bed"),
    ("earlier", "Strength training 4 to 12 h before bed"),
    ("late", "Strength training within 4 h before bed"),
)
TRAINING_OUTCOMES = ("sleep_h", "sleep_score", "deep_min", "rem_min", "awake_min", "bedtime_h", "hrv_ms", "night_hr")


def health_training_sleep(state: AppState, period: str = "all") -> Dict:
    """Sleep and recovery on nights after a strength session within 12 h or 4 h before sleep, against nights without."""
    if state.garmin is None:
        raise ValueError("No Garmin data is loaded")
    table = _in_period(_health_table(state), period)
    nights = table.dropna(subset=["sleep_h"]) if len(table) else table
    level = state.config.stats.ci_level
    if nights.empty:
        masks = {key: pd.Series(dtype=bool) for key, _ in TRAINING_GROUPS}
    else:
        within12, within4 = nights["strength_min_12h"] > 0, nights["strength_min_4h"] > 0
        masks = {"none": ~within12, "earlier": within12 & ~within4, "late": within4}
    rows = []
    for key in TRAINING_OUTCOMES:
        row = {"key": key, "title": DAILY_MEASURES[key][0]}
        base = nights.loc[masks["none"], key] if len(nights) else pd.Series(dtype=float)
        row["none"] = {"n": int(base.notna().sum()), "mean": base.mean() if base.notna().any() else None}
        for group in ("earlier", "late"):
            values = nights.loc[masks[group], key] if len(nights) else pd.Series(dtype=float)
            cell = {"n": int(values.notna().sum()), "mean": values.mean() if values.notna().any() else None, "diff": None, "low": None, "high": None}
            d = mean_difference(values, base, level=level)
            if d is not None:
                cell.update(diff=d.diff, low=d.low, high=d.high)
            row[group] = cell
        rows.append(row)
    return clean({
        "groups": [{"key": key, "title": title, "nights": int(masks[key].sum())} for key, title in TRAINING_GROUPS],
        "rows": rows, "nights": int(len(nights)), "level": level,
    })


# --- rounds: competition scores (certificates) and the full rounds of the Garmin app ------------------------

# key -> (title, column of the record)
COMPETITION_MEASURES = {
    "gross": ("Strokes", "gross"),
    "stableford": ("Stableford points", "stableford"),
    "differential": ("Score differential", "differential"),
    "hcp_new": ("Handicap index after the round", "hcp_new"),
}
SUMMARY_LAST_ROUNDS = 10
SUMMARY_LAST_DAYS = 365
# source -> (the averages' windows in rounds, the rounds each needs). The competition record is too short for a long average.
TREND_WINDOWS = {"competition": ((5,), (3,)), "garmin": ((5, 10), (3, 5))}


def all_rounds(state: AppState, source: str) -> Optional[pd.DataFrame]:
    """Every round of a source, oldest first, with a `round_key` that names it (None if the source is not loaded)."""
    if source == "competition":
        return state.competition
    if source == "garmin":
        return state.golf_stats
    raise ValueError(f"Unknown source: {source}")


def included_rounds(state: AppState, source: str) -> Optional[pd.DataFrame]:
    """The rounds of a source that take part: all but those unticked in the Rounds tab."""
    rounds = all_rounds(state, source)
    if rounds is None:
        return None
    return rounds[~rounds["round_key"].isin(state.config.excluded_rounds.get(source, frozenset()))].reset_index(drop=True)


def rounds_overview(state: AppState) -> Dict:
    """What the Rounds tab can show: the competition record and the Garmin rounds, with their measures and years."""
    competition, golf = included_rounds(state, "competition"), included_rounds(state, "garmin")
    every = {source: all_rounds(state, source) for source in ("competition", "garmin")}
    return clean({
        "competition": {
            "loaded": every["competition"] is not None,
            "rounds": int(len(every["competition"])) if every["competition"] is not None else 0,
            "selected": int(len(competition)) if competition is not None else 0,
            "derived": int(competition["gross_derived"].sum()) if competition is not None else 0,
            "measures": [{"key": key, "title": title} for key, (title, _) in COMPETITION_MEASURES.items()],
            "years": sorted({int(d[:4]) for d in competition["date"]}, reverse=True) if competition is not None else [],
            "notes": state.competition_notes, "error": state.errors.get("competition", ""),
        },
        "garmin": {
            "loaded": every["garmin"] is not None,
            "rounds": int(len(every["garmin"])) if every["garmin"] is not None else 0,
            "selected": int(len(golf)) if golf is not None else 0,
            "measures": [{"key": key, "title": title} for key, (title, _) in ROUND_MEASURES.items()],
            "years": sorted({d.year for d in golf["date"]}, reverse=True) if golf is not None else [],
        },
        "days": list(PAIR_DAYS),
    })


def _round_series(state: AppState, source: str, measure: str):
    """Date, value and 'derived' flag of the rounds of one source that take part, oldest first."""
    if source == "competition":
        if state.competition is None:
            raise ValueError("No competition rounds are loaded")
        if measure not in COMPETITION_MEASURES:
            raise ValueError(f"Unknown measure: {measure}")
        title, column = COMPETITION_MEASURES[measure]
        frame = included_rounds(state, "competition")
        derived = frame["gross_derived"] if measure == "gross" else pd.Series(False, index=frame.index)
        return title, frame["date"].astype(str), pd.to_numeric(frame[column], errors="coerce"), derived
    if source == "garmin":
        if state.golf_stats is None:
            raise ValueError("No Garmin rounds are loaded")
        if measure not in ROUND_MEASURES:
            raise ValueError(f"Unknown measure: {measure}")
        stats = included_rounds(state, "garmin")
        return ROUND_MEASURES[measure][0], stats["date"].astype(str), pd.to_numeric(stats[measure], errors="coerce"), pd.Series(False, index=stats.index)
    raise ValueError(f"Unknown source: {source}")


def rounds_trend(state: AppState, source: str, measure: str, period: str = "all") -> Dict:
    """One measure round by round (the rounds that take part) with the average of the last rounds."""
    title, dates, values, derived = _round_series(state, source, measure)
    windows, minimum = TREND_WINDOWS[source]
    means = rolling_by_round(values, windows, minimum)
    table = pd.DataFrame({"value": values.to_numpy(), "short": means["short"].to_numpy(), "long": means["long"].to_numpy(),
                          "derived": derived.to_numpy(), "date": dates.to_numpy()}, index=pd.to_datetime(dates).dt.date)
    table = _in_period(table, period)
    shown = table.dropna(subset=["value"])
    points = [{"date": row["date"], "value": row["value"], "short": row["short"], "long": row["long"], "derived": bool(row["derived"])}
              for _, row in shown.iterrows()]
    latest = {"short": shown["short"].iloc[-1], "long": shown["long"].iloc[-1], "all": shown["value"].mean()} if len(shown) else None
    return clean({"title": title, "points": points, "latest": latest, "rounds": int(len(table)), "windows": list(windows),
                  "derived": int(shown["derived"].sum())})


def rounds_competition_table(state: AppState) -> Dict:
    """Every round of the record, newest first, with whether it takes part and the Garmin statistics of the same day."""
    if state.competition is None:
        raise ValueError("No competition rounds are loaded")
    excluded = state.config.excluded_rounds.get("competition", frozenset())
    garmin = {}
    if state.golf_stats is not None:
        for _, g in state.golf_stats.iterrows():
            garmin.setdefault(str(g["date"]), g)
    rows = []
    for _, r in state.competition.iloc[::-1].iterrows():
        g = garmin.get(r["date"])
        rows.append({
            "key": r["round_key"], "selected": r["round_key"] not in excluded,
            "date": r["date"], "club": r["club"], "par": r["par"], "slope": r["slope"], "rating": r["course_rating"],
            "gross": r["gross"], "gross_derived": bool(r["gross_derived"]), "stableford": r["stableford"],
            "differential": r["differential"], "hcp_new": r["hcp_new"], "pcc": r["pcc"],
            "garmin": None if g is None else {"strokes": g["strokes"], "fir_pct": g["fir_pct"], "gir_pct": g["gir_pct"],
                                              "putts_per_hole": g["putts_per_hole"], "penalty_strokes": g["penalty_strokes"]},
        })
    linked = sum(1 for row in rows if row["garmin"] is not None)
    return clean({"rows": rows, "linked": linked, "garmin_loaded": state.golf_stats is not None,
                  "selected": sum(1 for row in rows if row["selected"]), "last_days": SUMMARY_LAST_DAYS, "last_rounds": SUMMARY_LAST_ROUNDS})


def rounds_garmin_table(state: AppState) -> Dict:
    """Every Garmin round, newest first, with whether it takes part."""
    if state.golf_stats is None:
        raise ValueError("No Garmin rounds are loaded")
    excluded = state.config.excluded_rounds.get("garmin", frozenset())
    rows = []
    for _, r in state.golf_stats.iloc[::-1].iterrows():
        rows.append({
            "key": r["round_key"], "selected": r["round_key"] not in excluded,
            "date": str(r["date"]), "course": r["course"], "tee": r["tee"], "strokes": r["strokes"], "to_par": r["to_par"],
            "differential": r["differential"], "fir_pct": r["fir_pct"], "gir_pct": r["gir_pct"],
            "putts_per_hole": r["putts_per_hole"], "putts_18": r["putts_18"], "penalty_strokes": r["penalty_strokes"],
        })
    return clean({"rows": rows, "selected": sum(1 for row in rows if row["selected"]), "last_days": SUMMARY_LAST_DAYS, "last_rounds": SUMMARY_LAST_ROUNDS})


def rounds_select(state: AppState, source: str, selected: List[str]) -> Dict:
    """Choose the rounds of a source that take part; rounds that come later take part automatically."""
    rounds = all_rounds(state, source)
    if rounds is None:
        raise ValueError(f"No {'competition' if source == 'competition' else 'Garmin'} rounds are loaded")
    every = set(rounds["round_key"])
    unknown = sorted(set(selected) - every)
    if unknown:
        raise ValueError(f"Not a round of the data: {', '.join(unknown[:3])}")
    if not selected:
        raise ValueError("Select at least one round")
    with state.lock:
        update_local_settings(state.config, {"rounds": {source: {"excluded": sorted(every - set(selected))}}})
        state.reload_config()
    return rounds_competition_table(state) if source == "competition" else rounds_garmin_table(state)


def rounds_garmin_summary(state: AppState) -> Dict:
    """The statistics of the Garmin rounds that take part: all, the last 12 months and the last 10 rounds."""
    if state.golf is None or state.golf_stats is None:
        raise ValueError("No Garmin rounds are loaded")
    stats = included_rounds(state, "garmin")
    rounds, holes = state.golf.rounds, state.golf.holes
    ids_all = list(stats["round_id"])
    last_day = max(stats["date"]) if len(stats) else None
    since = pd.Timestamp(last_day) - pd.Timedelta(days=SUMMARY_LAST_DAYS) if last_day else None
    ids_year = [i for i, d in zip(stats["round_id"], stats["date"]) if pd.Timestamp(d) > since] if last_day else []
    ids_last = ids_all[-SUMMARY_LAST_ROUNDS:]
    columns = [("all", "Selected rounds", ids_all), ("year", "Last 12 months", ids_year), ("last", f"Last {SUMMARY_LAST_ROUNDS} rounds", ids_last)]
    results = {key: summarise(rounds, holes, ids) for key, _, ids in columns}
    rows = [{"key": key, "title": title, "values": {c: (fmt.format(results[c][key]) if results[c][key] is not None and not pd.isna(results[c][key]) else None) for c, _, _ in columns}}
            for key, title, fmt in SUMMARY_ROWS]
    return clean({"columns": [{"key": key, "title": title, "rounds": len(ids)} for key, title, ids in columns], "rows": rows,
                  "first": str(stats["date"].min()) if len(stats) else "", "last": str(last_day) if last_day else ""})


# --- wedge distance drill ---------------------------------------------------------------------------------

def _drill_folder(state: AppState):
    folder = state.config.drill_dir
    if folder is None:
        raise ValueError("No folder for the drill sessions is chosen")
    return folder


def _pitching_fits(state: AppState) -> Dict:
    """The speed-to-carry line of each wedge from the swing lengths the drill uses (10 o'clock and above)."""
    pitching = state.included("pitching")
    if pitching is None:
        return drill_stats.wedge_fits(pd.DataFrame())
    return drill_stats.wedge_fits(pitching[pitching["intent"] >= drill_stats.MIN_INTENT])


def _drill_rows(frame: pd.DataFrame) -> List[Dict]:
    """The shots of a session table for the page, with the miss of those already entered."""
    errors = drill_stats.shot_errors(frame).set_index("n")
    rows = []
    for _, row in frame.iterrows():
        entry = {"n": int(row["n"]), "wedge": row["wedge"], "target_m": row["target_m"], "target_mph": row["target_mph"], "slope": row["slope"],
                 "tolerance_mph": row["tolerance_mph"], "speed_mph": row["speed_mph"], "carry_m": row["carry_m"], "done": bool(pd.notna(row["speed_mph"]))}
        if entry["done"]:
            e = errors.loc[int(row["n"])]
            entry.update(err_mph=e["err_mph"], err_m=e["err_m"], hit=bool(e["hit"]), carry_err_m=e["carry_err_m"])
        rows.append(entry)
    return rows


def drill_setup(state: AppState) -> Dict:
    """What the drill can offer: the wedges with their target ladders, the defaults and the unfinished sessions."""
    found = _pitching_fits(state)
    wedges = [{"wedge": f.wedge, "n": f.n, "slope": f.slope, "r2": f.r2, "resid_sd": f.resid_sd,
               "speed_range": [f.speed_min, f.speed_max], "ladder": drill_stats.ladder(f)} for f in found["fits"]]
    unfinished = []
    sessions = drill_store.load_all(state.config.drill_dir)
    for session, group in sessions.groupby("session") if len(sessions) else []:
        left = int(group["speed_mph"].isna().sum())
        if left and len(group) > left:                                    # started and not finished
            unfinished.append({"session": session, "started": group["started"].iloc[0], "done": int(len(group) - left), "shots": int(len(group))})
    return clean({
        "enabled": state.config.drill_dir is not None, "wedges": wedges,
        "unavailable": [{"wedge": w, "reason": r} for w, r in found["unavailable"]],
        "defaults": {"shots": drill_stats.DEFAULT_SHOTS, "tolerance_mph": drill_stats.DEFAULT_TOLERANCE_MPH},
        "unfinished": unfinished[-5:],
    })


def drill_start(state: AppState, wedges: List[str], shots: int, tolerance_mph: float, seed: Optional[int] = None) -> Dict:
    """Plan a session, write its file and return the planned shots."""
    folder = _drill_folder(state)
    if not 1 <= shots <= 200:
        raise ValueError("A session has 1 to 200 shots")
    if not 0.2 <= tolerance_mph <= 20:
        raise ValueError("The tolerance is 0.2 to 20 mph")
    fits = {f.wedge: f for f in _pitching_fits(state)["fits"]}
    unknown = [w for w in wedges if w not in fits]
    if unknown:
        raise ValueError(f"No target distances for: {', '.join(unknown)}")
    chosen = [fits[w] for w in dict.fromkeys(wedges)]
    plan = drill_stats.plan_session(chosen, int(shots), np.random.default_rng(seed))
    session = drill_store.start_session(folder, plan, float(tolerance_mph))
    return drill_session(state, session)


def drill_session(state: AppState, session: str) -> Dict:
    """One session: its shots with the results entered so far (to continue it)."""
    frame = drill_store.load_session(_drill_folder(state), session)
    shots = _drill_rows(frame)
    return clean({"session": session, "started": frame["started"].iloc[0], "tolerance_mph": float(frame["tolerance_mph"].iloc[0]),
                  "shots": shots, "next": next((s["n"] for s in shots if not s["done"]), None)})


def drill_record(state: AppState, session: str, n: int, speed_mph: float, carry_m: Optional[float] = None) -> Dict:
    """Enter (or correct) the result of one shot of a session and give its miss."""
    folder = _drill_folder(state)
    frame = drill_store.record_shot(folder, session, int(n), float(speed_mph), None if carry_m is None else float(carry_m))
    shots = _drill_rows(frame)
    this = next(s for s in shots if s["n"] == int(n))
    done = [s for s in shots if s["done"]]
    return clean({"session": session, "shot": this, "entered": len(done), "shots": len(shots), "next": next((s["n"] for s in shots if not s["done"]), None),
                  "summary": drill_stats.summarise(drill_stats.shot_errors(frame), state.config.stats.ci_level)})


def drill_progress(state: AppState, wedge: Optional[str] = None) -> Dict:
    """How close you got to the targets, session by session, and by target distance (all sessions)."""
    level = state.config.stats.ci_level
    data = drill_store.load_all(state.config.drill_dir)
    errors = drill_stats.shot_errors(data) if len(data) else data
    wedges = sorted(errors["wedge"].unique()) if len(errors) else []
    if wedge:
        if wedge not in wedges:
            raise ValueError(f"No drill shots with the {wedge}")
        errors = errors[errors["wedge"] == wedge]
    sessions = []
    for session, group in errors.groupby("session") if len(errors) else []:
        if len(group) < drill_stats.MIN_SHOTS_FOR_SESSION:
            continue
        sessions.append({"session": session, "date": str(group["started"].iloc[0])[:10], "started": group["started"].iloc[0],
                         "tolerance_mph": float(group["tolerance_mph"].iloc[0]), **drill_stats.summarise(group, level)})
    sessions.sort(key=lambda s: s["started"])
    targets = []
    for (name, distance), group in errors.groupby(["wedge", "target_m"]) if len(errors) else []:
        s = drill_stats.summarise(group, level)
        targets.append({"wedge": name, "target_m": float(distance), "target_mph": float(group["target_mph"].median()), **s})
    targets.sort(key=lambda t: (t["target_m"], t["wedge"]))
    return clean({"wedges": wedges, "wedge": wedge or "", "sessions": sessions, "targets": targets, "level": level,
                  "total_shots": int(len(errors))})


# --- driver: launch and spin against the chart --------------------------------------------------------------

def _driver_verdict(label: str, r: Dict) -> str:
    t, g = r["typical"], r["gains"]
    gap = t["launch"] - t["opt_launch"]
    spin_gap = t["spin"] - t["opt_spin"]
    launch = (f"Your {label} launches {abs(gap):.1f} deg {'below' if gap < 0 else 'above'} the chart value" if abs(gap) >= 0.5
              else f"Your {label} launches within {abs(gap):.1f} deg of the chart value")
    spin = (f"and its spin is {abs(spin_gap):.0f} rpm {'below' if spin_gap < 0 else 'above'} it" if abs(spin_gap) >= 100 else "and its spin is close to it")
    text = (f"{launch} for your usual ball speed ({t['ball_mph']:.0f} mph) and angle of attack ({t['aoa_deg']:+.1f} deg: {t['opt_launch']:.1f} deg and {t['opt_spin']:.0f} rpm), {spin}.")
    both = g["both"]
    if both["mean"] is not None:
        text += f" Hitting the chart's launch angle and spin on every shot would add about {both['mean']:.1f} m of carry"
        if both["lo"] is not None:
            text += f" (95% interval {both['lo']:.1f} to {both['hi']:.1f} m)"
        text += "."
    return text


def swing_driver(state: AppState, label: Optional[str] = None) -> Dict:
    """The driver's launch angle and spin against the optimal chart, and what the gap is worth in carry."""
    chart = state.targets.chart
    if chart is None:
        return {"ok": False, "reason": "The chart of optimal launch and spin is not available.", "notes": list(state.targets.notes)}
    df = state.selected("swing")
    drivers = df[df["club"] == "driver"] if not df.empty else df
    labels = list(dict.fromkeys(drivers["label"])) if len(drivers) else []
    if not labels:
        return {"ok": False, "reason": "No driver shots in the selected sessions and clubs.", "notes": list(state.targets.notes), "labels": []}
    if label:
        if label not in labels:
            raise ValueError(f"Unknown club: {label}")
        drivers = drivers[drivers["label"] == label]
    key = (label or "", len(drivers), round(float(drivers["carry_m"].sum()), 3), round(float(drivers["spin_rpm"].sum()), 3))
    result = analyse_driver(drivers, chart, level=state.config.stats.ci_level, model=state.driver_models.get(key))
    if result is None:
        return {"ok": False, "labels": labels, "notes": list(state.targets.notes),
                "reason": "Needs at least 30 driver shots from 3 sessions with ball speed, launch angle, spin, spin axis, attack angle, peak height and carry."}
    state.driver_models[key] = result.pop("_model")
    grid = {"speeds": [float(v) for v in chart.speeds[::-1]], "aoas": [float(v) for v in chart.aoas],
            "launch": chart.launch[::-1].tolist(), "spin": chart.spin[::-1].tolist()}
    return clean({"ok": True, "label": label or "", "labels": labels, "verdict": _driver_verdict(label or labels[0], result), "chart": grid,
                  "folder": str(state.targets.folder) if state.targets.folder else "", "notes": list(state.targets.notes), **result})


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
