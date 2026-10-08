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

from golf.bag import available_clubs, intent_grid, select_bag, unlisted_clubs
from golf.config import MODES, BagSpec, Config, load_config, update_local_settings
from golf.data import load_shots, unparsed_labels
from golf.data.labels import FULL_SWING
from golf.report.build import generate_card
from golf.sessions import include_sessions, session_table
from golf.stats import (
    COVERAGE_1S, COVERAGE_2S, compare_normal, describe, fit_bivariate, fit_univariate,
    session_summary,
)

BASELINE_CHOICES = {"last4": 4, "all": None}


# --- state ---------------------------------------------------------------------------

class AppState:
    """The loaded data and settings of one running dashboard."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path
        self.lock = threading.RLock()
        self.config: Config = load_config(config_path)
        self.shots: Dict[str, Optional[pd.DataFrame]] = {mode: None for mode in MODES}
        self.errors: Dict[str, str] = {}
        self.reload_data()

    def reload_config(self) -> None:
        self.config = load_config(self.config_path)

    def reload_data(self, modes=MODES) -> None:
        for mode in modes:
            try:
                self.shots[mode] = load_shots(mode, self.config)
                self.errors.pop(mode, None)
            except (FileNotFoundError, ValueError, OSError) as error:
                self.shots[mode] = None
                self.errors[mode] = str(error)

    def included(self, mode: str) -> Optional[pd.DataFrame]:
        """All shots of the sessions chosen on the Sessions tab (None if no data is loaded)."""
        shots = self.shots[mode]
        if shots is None:
            return None
        return include_sessions(shots, self.config.excluded_sessions.get(mode, ()))

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
        if shots is None:
            info[mode] = {"folder": str(folder), "loaded": False, "error": state.errors.get(mode, "")}
            continue
        problems = unparsed_labels(shots)
        extra = unlisted_clubs(shots, state.config.bag[mode])
        info[mode] = {
            "folder": str(folder), "loaded": True,
            "files": int(shots["source_file"].nunique()), "shots": int(len(shots)),
            "sessions": int(shots["session_date"].nunique()),
            "sessions_selected": int(state.included(mode)["session_date"].nunique()),
            "last_session": str(shots["session_date"].max()),
            "unreadable": problems.to_dict("records"),
            "not_in_bag": extra.to_dict("records"),
        }
    return clean(info)


def set_folders(state: AppState, swing_dir: Optional[str], pitching_dir: Optional[str]) -> Dict:
    patch = {}
    for mode, value in (("swing", swing_dir), ("pitching", pitching_dir)):
        if not value:
            continue
        folder = Path(value).expanduser()
        if not folder.is_dir():
            raise ValueError(f"{value} is not a folder")
        if not any(folder.glob("*.csv")):
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
        before = _baseline(group, day, baseline)
        row = {"label": label, "n": int(len(now)), "n_before": int(len(before)), "measures": {}}
        for name, column in measures.items():
            cur, prev = now[column].dropna(), before[column].dropna()
            entry = _measure(now[column])
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
    return clean({"sessions": sessions_of(df), "labels": labels, "loaded": state.shots["swing"] is not None})


def swing_review(state: AppState, session: str, baseline: str = "last4") -> Dict:
    return review(
        state, "swing", session, baseline,
        {"carry": "carry_m", "lateral": "lateral_m"}, key="carry",
    )


def progress(state: AppState, mode: str, label: str) -> Dict:
    """Per session mean and spread of carry and lateral for one club, with 95% intervals."""
    df = state.selected(mode)
    if df.empty:
        return {"label": label, "sessions": []}
    group = df[df["label"] == label]
    level = state.config.stats.ci_level
    carry = session_summary(group, "carry_m", by=["label"], level=level)
    lateral = session_summary(group, "lateral_m", by=["label"], level=level).set_index("session_date")
    sessions = []
    for _, row in carry.iterrows():
        lat = lateral.loc[row["session_date"]] if row["session_date"] in lateral.index else None
        sessions.append({
            "date": row["session_date"], "n": row["n"],
            "carry_mean": row["mean"], "carry_mean_lo": row["mean_lo"], "carry_mean_hi": row["mean_hi"],
            "carry_sd": row["sd"], "carry_sd_lo": row["sd_lo"], "carry_sd_hi": row["sd_hi"],
            "lat_mean": None if lat is None else lat["mean"],
            "lat_mean_lo": None if lat is None else lat["mean_lo"],
            "lat_mean_hi": None if lat is None else lat["mean_hi"],
            "lat_sd": None if lat is None else lat["sd"],
            "lat_sd_lo": None if lat is None else lat["sd_lo"],
            "lat_sd_hi": None if lat is None else lat["sd_hi"],
        })
    return clean({"label": label, "sessions": sessions})


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

    before = _baseline(group, day, compare)

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
    clubs = list(dict.fromkeys(df["club"] + " " + df["variant"].fillna(""))) if not df.empty else []
    return clean({
        "sessions": sessions_of(df), "labels": labels, "clubs": [c.strip() for c in clubs],
        "loaded": state.shots["pitching"] is not None,
    })


def pitching_review(state: AppState, session: str, baseline: str = "last4") -> Dict:
    return review(
        state, "pitching", session, baseline,
        {"speed": "club_speed_mph", "carry": "carry_m", "lateral": "lateral_m"}, key="speed",
    )


ACCURACY_MEASURES = {
    "speed_mean": ("club_speed_mph", "mean", "Club head speed (mph)"),
    "speed_sd": ("club_speed_mph", "sd", "Club head speed spread, sd (mph)"),
    "lateral_sd": ("lateral_m", "sd", "Lateral spread, sd (m)"),
    "carry_sd": ("carry_m", "sd", "Carry spread, sd (m, simulated)"),
}


def accuracy_over_time(state: AppState, club: str, measure: str) -> Dict:
    """For one wedge: the chosen measure per session, one series per intent."""
    column, kind, title = ACCURACY_MEASURES[measure]
    shots = state.included("pitching")
    if shots is None:
        return {"title": title, "sessions": [], "series": []}
    base = (shots["club"].fillna("") + " " + shots["variant"].fillna("")).str.strip()
    group = shots[base == club]
    level = state.config.stats.ci_level
    sessions = sessions_of(group)[::-1]
    series = []
    for intent in sorted(group["intent"].dropna().unique(), reverse=True):
        frame = group[group["intent"] == intent]
        summary = session_summary(frame, column, by=["label"], level=level)
        points = {str(r["session_date"]): r for _, r in summary.iterrows()}
        name = "full" if int(intent) == FULL_SWING else str(int(intent))
        series.append({
            "intent": int(intent), "name": name,
            "y": [points[d][kind] if d in points else None for d in sessions],
            "lo": [points[d][f"{kind}_lo"] if d in points else None for d in sessions],
            "hi": [points[d][f"{kind}_hi"] if d in points else None for d in sessions],
            "n": [int(points[d]["n"]) if d in points else 0 for d in sessions],
        })
    return clean({"title": title, "sessions": sessions, "series": series})


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
