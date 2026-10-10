from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from golf.dashboard import api
from golf.dashboard.service import AppState
from golf.data.garmin import load_garmin
from golf.data.withings import describe_withings, find_weight_file, load_withings
from golf.stats.daily import BODY_MEASURES, DAILY_MEASURES, GARMIN_MEASURES, available_measures, daily_table, windows_for
from golf.stats.difference import mean_difference

from test_correlations import DAYS, build_world, call
from test_garmin import ZONE, export  # noqa: F401  (fixture)

HEADER = 'Date,"Weight (kg)","Fat mass (kg)","Bone mass (kg)","Muscle mass (kg)","Hydration (kg)",Comments\n'


@pytest.fixture
def scale(tmp_path):
    """A small Health Mate export: three days (one with two weighings, one without body composition), a height, and an unread file."""
    folder = tmp_path / "scale"
    folder.mkdir()
    (folder / "weight.csv").write_text(
        HEADER
        + '"2026-06-11 07:00:00",80.0,16.0,3.2,62.0,44.0,\n'
        + '"2026-06-10 21:30:00",81.0,17.0,3.2,61.0,43.0,\n'          # the evening weighing of 10 June ...
        + '"2026-06-10 06:30:00",79.5,15.9,3.2,62.4,44.2,\n'          # ... comes second, the morning one is used
        + '"2026-06-09 06:45:00",80.4,,,,,\n',                        # a plain scale reading
        encoding="utf-8")
    (folder / "height.csv").write_text('Date,"Height (m)",Comments\n"2020-05-27 13:11:12",1.80,\n', encoding="utf-8")
    (folder / "other.csv").write_text("type,date,value,unit,position\nFAT_PERCENT,\"2026-06-11 07:00:00\",20,,\n", encoding="utf-8")
    return folder


# --- reading the export ---------------------------------------------------------------------------------

def test_one_row_per_day_morning_weighing_first(scale):
    body = load_withings(scale).body
    assert [str(d) for d in body["date"]] == ["2026-06-09", "2026-06-10", "2026-06-11"]
    june10 = body.iloc[1]
    assert (june10["weight_kg"], june10["fat_kg"], june10["muscle_kg"]) == (79.5, 15.9, 62.4)


def test_a_weighing_without_body_composition_keeps_its_weight(scale):
    first = load_withings(scale).body.iloc[0]
    assert first["weight_kg"] == 80.4 and np.isnan(first["fat_kg"]) and np.isnan(first["muscle_kg"]) and not np.isnan(first["bmi"])


def test_body_mass_index_uses_the_height(scale):
    body = load_withings(scale).body
    assert body["bmi"].iloc[2] == pytest.approx(80.0 / 1.8 ** 2)


def test_without_a_height_there_is_no_body_mass_index(scale):
    (scale / "height.csv").unlink()
    assert load_withings(scale).body["bmi"].isna().all()


def test_the_description_counts_weighings(scale):
    assert describe_withings(load_withings(scale)) == {"weighings": 3, "with_composition": 2, "first": "2026-06-09", "last": "2026-06-11"}


def test_the_weight_file_may_be_one_folder_down(scale, tmp_path):
    assert find_weight_file(tmp_path) == scale / "weight.csv"


def test_a_folder_without_an_export_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match="No Withings export"):
        load_withings(tmp_path)


def test_a_file_that_is_not_a_weight_file_is_refused(tmp_path):
    (tmp_path / "weight.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not look like a Withings weight file"):
        load_withings(tmp_path)


# --- the daily table with body data -----------------------------------------------------------------------

def test_nights_and_weighings_share_one_table(export, scale):
    table = daily_table(load_garmin(export), ZONE, load_withings(scale))
    assert [str(d) for d in table.index] == ["2026-06-09", "2026-06-10", "2026-06-11"]
    assert list(table.columns) == list(DAILY_MEASURES)
    june10 = table.loc[date(2026, 6, 10)]
    assert june10["weight_kg"] == 79.5 and june10["fat_pct"] == pytest.approx(15.9 / 79.5 * 100) and june10["sleep_h"] > 0


def test_body_data_alone_has_no_sleep(scale):
    table = daily_table(None, ZONE, load_withings(scale))
    assert len(table) == 3 and table["sleep_h"].isna().all() and table["weight_kg"].notna().all()


def test_days_without_a_weighing_have_no_body_values(export, tmp_path):
    folder = tmp_path / "scale2"
    folder.mkdir()
    (folder / "weight.csv").write_text(HEADER + '"2026-06-12 07:00:00",80.0,16.0,3.2,62.0,44.0,\n', encoding="utf-8")
    table = daily_table(load_garmin(export), ZONE, load_withings(folder))
    assert len(table) == 4 and table["weight_kg"].notna().sum() == 1                  # the three nights have no weight, not zero
    assert np.isnan(table.loc[date(2026, 6, 12), "sleep_h"])                         # a weighing without a night has no sleep


def test_only_the_loaded_kinds_of_measure_are_available(export, scale):
    garmin, withings = load_garmin(export), load_withings(scale)
    assert list(available_measures(garmin, None)) == list(GARMIN_MEASURES)
    assert list(available_measures(None, withings)) == list(BODY_MEASURES)
    assert list(available_measures(garmin, withings)) == list(DAILY_MEASURES)
    assert available_measures(None, None) == {}


def test_body_measures_are_smoothed_over_longer_windows():
    assert windows_for("weight_kg") == ((30, 90), (2, 3))
    assert windows_for("sleep_h") == ((7, 28), (3, 10))


def test_strength_within_four_and_twelve_hours_of_bed(export):
    # ends 4.5 h before bed on 10 June: inside 12 h, outside 4 h
    table = daily_table(load_garmin(export), ZONE)
    june10 = table.loc[date(2026, 6, 10)]
    assert (june10["strength_min_4h"], june10["strength_min_12h"], june10["strength_min_24h"]) == (0, 60, 60)
    assert table.loc[date(2026, 6, 9), "strength_min_12h"] == 0                        # the session on 7 June is far before


# --- difference between two groups ------------------------------------------------------------------------

def test_the_difference_interval_is_welchs():
    rng = np.random.default_rng(3)
    a, b = rng.normal(5, 2, 12), rng.normal(4, 1, 40)
    d = mean_difference(a, b, level=0.95)
    reference = stats.ttest_ind(a, b, equal_var=False).confidence_interval(0.95)
    assert d.diff == pytest.approx(a.mean() - b.mean())
    assert (d.low, d.high) == pytest.approx((reference.low, reference.high))
    assert (d.n_a, d.n_b) == (12, 40)


def test_too_small_or_constant_groups_have_no_difference():
    assert mean_difference([1.0, 2.0], [1.0, 2.0, 3.0, 4.0]) is None
    assert mean_difference([5.0, 5.0, 5.0], [5.0, 5.0, 5.0]) is None
    assert mean_difference([1.0, np.nan, 3.0, 5.0], [1.0, 2.0, 3.0, 9.0]).n_a == 3          # missing values are dropped


# --- the page's interface ---------------------------------------------------------------------------------

def weighings(count=6, start=date(2026, 3, 2)):
    return [(start + timedelta(days=9 * k), 82.0 - 0.2 * k, 16.0 - 0.1 * k, 62.0 + 0.1 * k) for k in range(count)]


@pytest.fixture
def scale_only(tmp_path):
    config = build_world(tmp_path, sleep_hours=[8.0] * len(DAYS), speed_for=lambda k: 90.0, garmin=False, weighings=weighings())
    text = config.read_text(encoding="utf-8")
    import re
    for key in ("swing_dir", "stack_dir"):
        text = re.sub(rf'{key} = ".*"', f'{key} = ""', text)
    config.write_text(text, encoding="utf-8")
    return AppState(config)


def test_the_scale_folder_is_described_and_can_be_chosen(scale_only, scale):
    info = call(scale_only, "/api/state")["datasets"]["withings"]
    assert info["loaded"] and info["weighings"] == 6 and info["with_composition"] == 6
    assert call(scale_only, "/api/state")["datasets"]["garmin"]["enabled"] is False
    after = call(scale_only, "/api/load", method="POST", withings_dir=str(scale))["datasets"]["withings"]
    assert after["weighings"] == 3
    assert call(scale_only, "/api/load", method="POST", withings_dir="")["datasets"]["withings"]["enabled"] is False


def test_a_folder_that_is_no_scale_export_is_refused(scale_only, tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(api.ApiError, match="No Withings export"):
        call(scale_only, "/api/load", method="POST", withings_dir=str(tmp_path / "empty"))


def test_a_broken_weight_file_is_an_error_not_a_crash(tmp_path):
    config = build_world(tmp_path, sleep_hours=[8.0] * len(DAYS), speed_for=lambda k: 90.0, garmin=False, weighings=weighings())
    (tmp_path / "withingsdata" / "weight.csv").write_text("nothing useful\n", encoding="utf-8")
    state = AppState(config)
    info = call(state, "/api/state")["datasets"]["withings"]
    assert info["enabled"] and not info["loaded"] and "Withings" in info["error"]


def test_the_scale_alone_offers_body_measures_and_no_golf_comparison(scale_only):
    overview = call(scale_only, "/api/garmin/overview")
    assert [m["key"] for m in overview["daily"]] == list(BODY_MEASURES)
    assert overview["outcomes"] == [] and overview["training_sleep"] is False and overview["years"] == [2026]


def test_a_body_trend_uses_long_windows(scale_only):
    d = call(scale_only, "/api/health/trend", measure="weight_kg")
    assert d["windows"] == [30, 90] and len(d["points"]) == 6
    assert d["points"][0]["short"] is None                                               # one weighing is not an average
    assert d["points"][1]["short"] == pytest.approx(81.9) and d["points"][2]["short"] == pytest.approx(81.8)   # 2 and 3 weighings in 30 days
    assert d["points"][2]["long"] == pytest.approx(81.8)                                                      # 3 are enough for the 90-day mean
    assert d["latest"]["all"] == pytest.approx(np.mean([82.0 - 0.2 * k for k in range(6)]), abs=0.01)


def test_garmin_measures_are_not_offered_without_the_watch(scale_only):
    with pytest.raises(api.ApiError, match="needs data that is not loaded"):
        call(scale_only, "/api/health/trend", measure="sleep_h")
    with pytest.raises(api.ApiError, match="needs data that is not loaded"):
        call(scale_only, "/api/garmin/pair", x="weight_kg", y="hrv_ms")
    with pytest.raises(api.ApiError, match="No Garmin data"):
        call(scale_only, "/api/health/training-sleep")


def test_body_and_sleep_can_be_plotted_against_each_other(tmp_path):
    rows = [(DAYS[k], 80.0 + k * 0.5, 16.0, 62.0) for k in range(len(DAYS))]
    state = AppState(build_world(tmp_path, sleep_hours=[6.0 + 0.2 * k for k in range(len(DAYS))], speed_for=lambda k: 90.0, weighings=rows))
    d = call(state, "/api/garmin/pair", x="weight_kg", y="sleep_h")
    assert d["fit"]["n"] == len(DAYS) and d["fit"]["r"] > 0.99                           # both rise in step


# --- strength training before bed and sleep ---------------------------------------------------------------

@pytest.fixture
def training_world(tmp_path):
    """14 nights. Five end a strength session 2 h before bed (less deep sleep), three 8 h before (no change), six none."""
    late, earlier = [1, 3, 5, 7, 9], [2, 4, 6]
    training = {**{k: 2.0 for k in late}, **{k: 8.0 for k in earlier}}
    deep = lambda k: (40 if k in late else 80) + k % 3
    config = build_world(tmp_path, sleep_hours=[7.5] * len(DAYS), speed_for=lambda k: 90.0, training=training, deep_for=deep)
    return AppState(config), late, earlier


def test_nights_are_sorted_by_when_the_training_ended(training_world):
    state, late, earlier = training_world
    d = call(state, "/api/health/training-sleep")
    assert [g["nights"] for g in d["groups"]] == [len(DAYS) - len(late) - len(earlier), len(earlier), len(late)]
    assert d["nights"] == len(DAYS)


def test_less_deep_sleep_after_late_training_is_found(training_world):
    state, _, _ = training_world
    rows = {r["key"]: r for r in call(state, "/api/health/training-sleep")["rows"]}
    deep = rows["deep_min"]
    assert deep["late"]["diff"] == pytest.approx(-40, abs=2) and deep["late"]["high"] < 0           # clear
    assert deep["earlier"]["low"] < 0 < deep["earlier"]["high"]                                    # training 8 h before: no change
    assert deep["none"]["n"] == 6 and deep["late"]["n"] == 5


def test_a_measure_that_does_not_change_stays_unclear(training_world):
    state, _, _ = training_world
    rows = {r["key"]: r for r in call(state, "/api/health/training-sleep")["rows"]}
    assert rows["sleep_h"]["late"]["diff"] is None or rows["sleep_h"]["late"]["low"] <= 0 <= rows["sleep_h"]["late"]["high"]


def test_the_comparison_follows_the_period(training_world):
    state, _, _ = training_world
    assert call(state, "/api/health/training-sleep", period="year:2026")["nights"] == len(DAYS)
    empty = call(state, "/api/health/training-sleep", period="year:2019")
    assert empty["nights"] == 0 and all(r["late"]["diff"] is None for r in empty["rows"])


def test_the_training_comparison_is_offered_with_the_watch(training_world):
    state, _, _ = training_world
    assert call(state, "/api/garmin/overview")["training_sleep"] is True


# --- body measures against the practice results -------------------------------------------------------------

def body_context(scale, day, hour=10):
    from datetime import datetime
    from golf.stats.context import session_context
    starts = pd.Series({day: pd.Timestamp(datetime(day.year, day.month, day.day, hour))})
    return session_context(starts, None, ZONE, load_withings(scale)).iloc[0]


def test_the_latest_weighing_up_to_the_session_day_is_used(scale):
    c = body_context(scale, date(2026, 6, 20))                          # latest weighing 11 June (80.0 kg), 9 days old
    assert c["weight_kg"] == 80.0 and c["fat_pct"] == pytest.approx(20.0) and c["muscle_kg"] == 62.0
    assert body_context(scale, date(2026, 6, 10))["weight_kg"] == 79.5  # the weighing of the session day itself counts


def test_a_weighing_after_the_session_is_not_used(scale):
    assert body_context(scale, date(2026, 6, 8)).drop("session_hour").isna().all()


def test_a_weighing_older_than_two_weeks_is_not_used(scale):
    assert body_context(scale, date(2026, 6, 25))["weight_kg"] == 80.0                       # 14 days old
    assert np.isnan(body_context(scale, date(2026, 6, 26))["weight_kg"])                     # 15 days old


def test_without_the_watch_the_garmin_measures_stay_empty(scale):
    from golf.stats.context import PREDICTORS
    c = body_context(scale, date(2026, 6, 20))
    assert c[[k for k in PREDICTORS if k != "session_hour"]].isna().all()


@pytest.fixture
def heavy_world(tmp_path):
    """The 7-iron is faster when the scale shows more weight; no watch at all."""
    rng = np.random.default_rng(21)
    weight = list(rng.permutation(np.linspace(78.0, 86.0, len(DAYS))))
    rows = [(DAYS[k], weight[k], 16.0, 62.0) for k in range(len(DAYS))]
    config = build_world(tmp_path, sleep_hours=[8.0] * len(DAYS), garmin=False, weighings=rows,
                         speed_for=lambda k: 90.0 + 0.5 * (weight[k] - 82.0))
    return AppState(config)


def test_the_scale_alone_can_be_compared_with_the_swing(heavy_world):
    overview = call(heavy_world, "/api/garmin/overview")
    assert [o["key"] for o in overview["outcomes"]] == ["swing_speed", "swing_spread"]
    assert {p["key"] for p in overview["predictors"]} == set(BODY_MEASURES) - {"bmi"}       # no sleep measures without the watch; BMI is the weight again
    assert overview["training_sleep"] is False


def test_the_planted_weight_effect_is_found(heavy_world):
    table = call(heavy_world, "/api/garmin/table", outcome="swing_speed", club="7i 245")
    row = next(r for r in table["rows"] if r["key"] == "weight_kg")
    assert row["n"] == len(DAYS) and row["r"] > 0.9 and row["low"] > 0                      # clear
    assert {r["key"] for r in table["rows"]} == set(BODY_MEASURES) - {"bmi"}


def test_the_scatter_of_a_body_measure_has_one_dot_per_session(heavy_world):
    d = call(heavy_world, "/api/garmin/scatter", outcome="swing_speed", predictor="weight_kg", club="7i 245")
    assert len(d["points"]) == len(DAYS) and d["fit"]["slope"] > 0 and "Weight" in d["x_title"]


def test_a_measure_of_the_watch_is_refused_without_the_watch(heavy_world):
    with pytest.raises(api.ApiError, match="needs data that is not loaded"):
        call(heavy_world, "/api/garmin/scatter", outcome="swing_speed", predictor="sleep_h")


def test_with_both_the_table_lists_sleep_and_body_measures(tmp_path):
    from golf.stats.context import ALL_PREDICTORS
    rows = [(DAYS[k], 80.0 + (k % 4), 16.0, 62.0) for k in range(len(DAYS))]
    state = AppState(build_world(tmp_path, sleep_hours=[7.0 + 0.1 * k for k in range(len(DAYS))], speed_for=lambda k: 90.0 + k % 3, weighings=rows))
    keys = {r["key"] for r in call(state, "/api/garmin/table", outcome="swing_speed")["rows"]}
    assert keys == set(ALL_PREDICTORS)
