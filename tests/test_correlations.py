import json
import re
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from golf.config import DEFAULT_CONFIG
from golf.dashboard import api
from golf.dashboard.service import AppState

from test_dashboard import write_session
from test_garmin import activity, night
from test_stack import write_stack

DAYS = [date(2026, 3, 2) + timedelta(days=4 * k) for k in range(14)]


def build_world(tmp_path, *, sleep_hours, speed_for, garmin=True, stack=False, strength_days=(), weighings=None, deep_for=None, training=None):
    """Practice at 10:00 local on DAYS. The night before each session lasts sleep_hours[k]; speed_for(k) is the 7-iron speed."""
    swing = tmp_path / "swing"
    swing.mkdir()
    rng = np.random.default_rng(5)
    for k, day in enumerate(DAYS):
        rows = [("7 Iron 245", 150.0 + rng.normal(0, 4), rng.normal(0, 3), speed_for(k) + rng.normal(0, 0.3)) for _ in range(8)]
        rows += [("Driver Ping", 210.0 + rng.normal(0, 6), rng.normal(0, 4), 100.0 + 0.2 * k + rng.normal(0, 0.3)) for _ in range(8)]
        write_session(swing, day, rows)

    if stack:
        for k, day in enumerate(DAYS[:8]):
            speed = 92 + 0.2 * k + (1.0 if sleep_hours[k] > 8 else 0.0)
            write_stack(tmp_path / "stack" / f"Stack - {k}" / f"s{k}.csv", day, [("235g", [speed - 3 + 0.05 * i for i in range(8)]),
                                                                                 ("195g", [speed + 0.05 * i for i in range(8)])], start="10-00-00")

    if garmin:
        wellness = tmp_path / "garmindata" / "DI_CONNECT" / "DI-Connect-Wellness"
        fitness = tmp_path / "garmindata" / "DI_CONNECT" / "DI-Connect-Fitness"
        wellness.mkdir(parents=True), fitness.mkdir(parents=True)
        nights, health = [], []
        for k, day in enumerate(DAYS):
            end = datetime(day.year, day.month, day.day, 5, 30)
            start = end - timedelta(hours=sleep_hours[k] + 0.2)
            deep = deep_for(k) if deep_for else 60
            nights.append(night(day.isoformat(), start.strftime("%Y-%m-%dT%H:%M:%S") + ".0", end.strftime("%Y-%m-%dT%H:%M:%S") + ".0",
                                deep=deep, light=int(sleep_hours[k] * 60 - deep - 80), rem=80, awake=12, score=int(40 + 5 * sleep_hours[k])))
            health.append({"calendarDate": day.isoformat(), "metrics": [{"type": "HRV", "value": 40.0 + (k % 5)}, {"type": "HR", "value": 55.0}]})
        (wellness / "2026-01-01_2026-12-31_1_sleepData.json").write_text(json.dumps(nights), encoding="utf-8")
        (wellness / "2026-01-01_2026-12-31_1_healthStatusData.json").write_text(json.dumps(health), encoding="utf-8")
        acts = [activity("strength_training", datetime(d.year, d.month, d.day, 15, 0) - timedelta(days=1), 60, load=15.0) for d in strength_days]
        # training={night index: hours between the end of a one hour session and falling asleep}
        for k, hours in (training or {}).items():
            day = DAYS[k]
            bed = datetime(day.year, day.month, day.day, 5, 30) - timedelta(hours=sleep_hours[k] + 0.2)
            acts.append(activity("strength_training", bed - timedelta(hours=hours + 1), 60, load=15.0))
        (fitness / "x_1_summarizedActivities.json").write_text(json.dumps([{"summarizedActivitiesExport": acts}]), encoding="utf-8")

    if weighings:
        scale = tmp_path / "withingsdata"
        scale.mkdir()
        lines = ['Date,"Weight (kg)","Fat mass (kg)","Bone mass (kg)","Muscle mass (kg)","Hydration (kg)",Comments']
        lines += [f'"{day.isoformat()} 06:30:00",{weight},{fat},3.2,{muscle},44.0,' for day, weight, fat, muscle in weighings]
        (scale / "weight.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (scale / "height.csv").write_text('Date,"Height (m)",Comments\n"2020-05-27 13:11:12",1.80,\n', encoding="utf-8")

    text = DEFAULT_CONFIG.read_text(encoding="utf-8")
    for key, value in (("swing_dir", "swing"), ("pitching_dir", ""), ("stack_dir", "stack" if stack else ""),
                       ("garmin_dir", "garmindata" if garmin else ""), ("withings_dir", "withingsdata" if weighings else ""),
                       ("output_dir", "out")):
        text = re.sub(rf'{key} = ".*"', f'{key} = "{value}"', text)
    (tmp_path / "golf.toml").write_text(text, encoding="utf-8")
    return tmp_path / "golf.toml"


def call(state, path, method="GET", **params):
    body = params if method == "POST" else {}
    query = {} if method == "POST" else {k: str(v) for k, v in params.items()}
    return api.handle(state, method, path, query, body)


@pytest.fixture
def sleepy_world(tmp_path):
    """More sleep the night before means a faster 7-iron, with no improvement over time."""
    rng = np.random.default_rng(11)
    sleep = list(rng.permutation(np.linspace(5.8, 9.2, len(DAYS))))
    config = build_world(tmp_path, sleep_hours=sleep, speed_for=lambda k: 90.0 + 1.5 * (sleep[k] - 7.5), stack=True,
                         strength_days=DAYS[2::4])
    return AppState(config), sleep


def row_of(table, key):
    return next(r for r in table["rows"] if r["key"] == key)


# --- the Garmin folder ------------------------------------------------------------------------------------

def test_garmin_data_is_loaded_and_described(sleepy_world):
    state, _ = sleepy_world
    info = call(state, "/api/state")["datasets"]["garmin"]
    assert info["enabled"] and info["loaded"] and info["nights"] == len(DAYS) and info["mornings_with_hrv"] == len(DAYS)
    assert info["strength"] == len(DAYS[2::4])


def test_the_tab_offers_only_what_can_be_compared(sleepy_world, tmp_path):
    state, _ = sleepy_world
    overview = call(state, "/api/garmin/overview")
    assert [o["key"] for o in overview["outcomes"]] == ["stack_speed", "swing_speed", "swing_spread"]
    assert overview["clubs"] == ["driver ping", "7i 245"] and overview["timezone"] == "Europe/Zurich"
    assert {"sleep_h", "hrv_ms", "strength_24h", "cardio_min_7d"} <= {p["key"] for p in overview["predictors"]}


def test_without_stack_data_the_stack_result_is_not_offered(tmp_path):
    state = AppState(build_world(tmp_path, sleep_hours=[8.0] * len(DAYS), speed_for=lambda k: 90.0))
    assert [o["key"] for o in call(state, "/api/garmin/overview")["outcomes"]] == ["swing_speed", "swing_spread"]
    with pytest.raises(api.ApiError, match="No stack data"):
        call(state, "/api/garmin/table", outcome="stack_speed")


def test_without_garmin_data_everything_is_empty_or_refused(tmp_path):
    state = AppState(build_world(tmp_path, sleep_hours=[8.0] * len(DAYS), speed_for=lambda k: 90.0, garmin=False))
    assert call(state, "/api/state")["datasets"]["garmin"] == {"folder": "", "enabled": False, "loaded": False, "error": ""}
    assert call(state, "/api/garmin/overview") == {"loaded": False, "outcomes": [], "predictors": [], "clubs": [], "daily": []}
    with pytest.raises(api.ApiError, match="No Garmin or Withings data"):
        call(state, "/api/garmin/scatter", outcome="swing_speed", predictor="sleep_h")


def test_the_garmin_folder_can_be_chosen_and_left_empty(sleepy_world, tmp_path):
    state, _ = sleepy_world
    off = call(state, "/api/load", method="POST", garmin_dir="")["datasets"]
    assert off["garmin"]["enabled"] is False and off["swing"]["loaded"]
    with pytest.raises(api.ApiError, match="No Garmin export"):
        call(state, "/api/load", method="POST", garmin_dir=str(tmp_path / "swing"))
    on = call(state, "/api/load", method="POST", garmin_dir=str(tmp_path / "garmindata"))["datasets"]
    assert on["garmin"]["loaded"] and on["garmin"]["nights"] == len(DAYS)
    with pytest.raises(api.ApiError, match="not a folder"):
        call(state, "/api/load", method="POST", garmin_dir=str(tmp_path / "nowhere"))


def test_a_garmin_folder_that_is_missing_is_an_error_not_a_disabled_kind(tmp_path):
    config = build_world(tmp_path, sleep_hours=[8.0] * len(DAYS), speed_for=lambda k: 90.0)
    config.write_text(re.sub(r'garmin_dir = ".*"', 'garmin_dir = "missing"', config.read_text(encoding="utf-8")), encoding="utf-8")
    info = call(AppState(config), "/api/state")["datasets"]["garmin"]
    assert info["enabled"] is True and info["loaded"] is False and "No Garmin export" in info["error"]


# --- finding a real effect and not finding a made-up one -------------------------------------------------------

def test_the_planted_sleep_effect_is_found(sleepy_world):
    state, _ = sleepy_world
    table = call(state, "/api/garmin/table", outcome="swing_speed", club="7i 245", detrend=0)
    sleep = row_of(table, "sleep_h")
    assert sleep["n"] == len(DAYS) and sleep["r"] > 0.9 and sleep["low"] > 0.6
    assert table["rows"][0]["key"] in ("sleep_h", "sleep_score", "rem_min", "deep_min")        # the strongest links are the sleep ones
    assert table["sessions"] == len(DAYS) and table["tested"] <= len(table["rows"])


def test_a_measure_that_does_not_matter_stays_unclear(sleepy_world):
    state, _ = sleepy_world
    table = call(state, "/api/garmin/table", outcome="swing_speed", club="7i 245", detrend=0)
    assert row_of(table, "session_hour")["r"] is None                       # always 10:00: nothing to correlate
    hrv = row_of(table, "hrv_ms")
    assert hrv["low"] < 0 < hrv["high"]
    assert row_of(table, "cardio_min_7d")["r"] is None                      # no cardio in this made-up history


def test_the_table_is_sorted_by_strength_and_unusable_measures_come_last(sleepy_world):
    state, _ = sleepy_world
    rows = call(state, "/api/garmin/table", outcome="swing_speed", club="7i 245")["rows"]
    strengths = [abs(r["r"]) for r in rows if r["r"] is not None]
    assert strengths == sorted(strengths, reverse=True)
    assert all(r["r"] is None for r in rows[len(strengths):])


def test_the_scatter_shows_one_dot_per_session_and_the_same_correlation(sleepy_world):
    state, sleep = sleepy_world
    scatter = call(state, "/api/garmin/scatter", outcome="swing_speed", predictor="sleep_h", club="7i 245", detrend=0)
    assert len(scatter["points"]) == len(DAYS) and scatter["sessions"] == len(DAYS)
    assert sorted(p["x"] for p in scatter["points"]) == pytest.approx(sorted(float(s) for s in sleep), abs=0.02)   # stages are whole minutes
    table = call(state, "/api/garmin/table", outcome="swing_speed", club="7i 245", detrend=0)
    assert scatter["fit"]["r"] == pytest.approx(row_of(table, "sleep_h")["r"], abs=1e-3) and scatter["fit"]["slope"] > 0
    assert scatter["x_title"].startswith("Sleep duration") and "Club head speed" in scatter["y_title"] and "7i 245" in scatter["y_title"]


def test_a_stack_result_is_compared_at_one_weight(sleepy_world):
    state, _ = sleepy_world
    scatter = call(state, "/api/garmin/scatter", outcome="stack_speed", predictor="sleep_h", detrend=0)
    # both weights are used in every session; the heavier one is the reference when two weights tie
    assert len(scatter["points"]) == 8 and "235 g" in scatter["y_title"]
    assert scatter["fit"]["r"] > 0.5                                         # a long night adds a speed bonus in this made-up data


def test_a_steady_improvement_looks_like_an_effect_until_the_trend_is_removed(tmp_path):
    """Sleep and speed both just rise with the weeks: a correlation without any link."""
    sleep = list(np.linspace(6.0, 9.0, len(DAYS)))
    state = AppState(build_world(tmp_path, sleep_hours=sleep, speed_for=lambda k: 88.0 + 0.5 * k))
    raw = row_of(call(state, "/api/garmin/table", outcome="swing_speed", club="7i 245", detrend=0), "sleep_h")
    flat = row_of(call(state, "/api/garmin/table", outcome="swing_speed", club="7i 245", detrend=1), "sleep_h")
    assert raw["r"] > 0.9
    assert abs(flat["r"]) < 0.7 and flat["low"] < 0 < flat["high"]


def test_the_club_choice_and_the_session_selection_are_used(sleepy_world):
    state, _ = sleepy_world
    with pytest.raises(api.ApiError, match="Unknown club"):
        call(state, "/api/garmin/table", outcome="swing_speed", club="9i 100")
    chosen = [s["date"] for s in call(state, "/api/sessions", mode="swing")["sessions"]][:9]
    call(state, "/api/sessions", method="POST", mode="swing", selected=chosen)
    assert call(state, "/api/garmin/table", outcome="swing_speed", club="7i 245")["sessions"] == 9
    both = call(state, "/api/garmin/scatter", outcome="swing_speed", predictor="sleep_h")
    assert len(both["points"]) == 9 and "Club head speed" in both["y_title"]


def test_bad_requests_are_refused(sleepy_world):
    state, _ = sleepy_world
    with pytest.raises(api.ApiError, match="Unknown result"):
        call(state, "/api/garmin/table", outcome="putting")
    with pytest.raises(api.ApiError, match="Unknown measure"):
        call(state, "/api/garmin/scatter", outcome="swing_speed", predictor="mood")


def test_only_what_happened_before_the_session_is_used(tmp_path):
    """A strength session in the evening of the practice day must not count for the 10:00 practice."""
    sleep = [8.0] * len(DAYS)
    config = build_world(tmp_path, sleep_hours=sleep, speed_for=lambda k: 90.0)
    fitness = tmp_path / "garmindata" / "DI_CONNECT" / "DI-Connect-Fitness"
    after = [activity("strength_training", datetime(d.year, d.month, d.day, 18, 0), 60) for d in DAYS]
    (fitness / "later_1_summarizedActivities.json").write_text(json.dumps([{"summarizedActivitiesExport": after}]), encoding="utf-8")
    state = AppState(config)
    scatter = call(state, "/api/garmin/scatter", outcome="swing_speed", predictor="strength_24h", club="7i 245")
    assert {p["x"] for p in scatter["points"]} == {0.0}
