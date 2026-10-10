import numpy as np
import pytest

from golf.dashboard import api, service
from golf.data.garmin import load_garmin
from golf.stats.daily import BODY_MEASURES, DAILY_MEASURES, GARMIN_MEASURES, daily_table

from test_correlations import call, sleepy_world  # noqa: F401  (fixture)
from test_garmin import ZONE, export  # noqa: F401  (fixture)


@pytest.fixture
def table(export):
    return daily_table(load_garmin(export), ZONE)


def day(table, text):
    return table.loc[[d for d in table.index if str(d) == text][0]]


def test_one_row_per_night_with_every_measure(table):
    assert [str(d) for d in table.index] == ["2026-06-09", "2026-06-10", "2026-06-11"]
    assert list(table.columns) == list(DAILY_MEASURES)
    assert day(table, "2026-06-10")["hrv_ms"] == 52 and day(table, "2026-06-11")["night_hr"] == 60
    assert np.isnan(day(table, "2026-06-09")["hrv_ms"])                       # no vitals that morning: a gap, not zero


def test_bedtime_is_local_and_counts_on_after_midnight(table):
    # summer time: 21:00 UTC is 23:00 in Zurich, 22:00 UTC is midnight, which counts as 24
    assert [day(table, d)["bedtime_h"] for d in ("2026-06-09", "2026-06-10", "2026-06-11")] == pytest.approx([23.0, 23.5, 24.0])


def test_training_counts_only_what_ended_before_bed(table):
    # strength 06-09 16:00-17:00 UTC (load 12), earlier one 06-07 16:00-17:00 UTC (load 20)
    first, second, third = (day(table, d) for d in ("2026-06-09", "2026-06-10", "2026-06-11"))
    assert (first["strength_min_24h"], first["strength_min_72h"]) == (0, 60)            # the second session is 28 h before bed
    assert (second["strength_min_24h"], second["strength_load_24h"], second["strength_min_72h"]) == (60, 12, 120)
    assert (third["strength_min_24h"], third["strength_min_72h"]) == (0, 60)


def test_only_cardio_types_count_as_cardio(table):
    # running ends 06:45 UTC on 10 June; walking and golf are not cardio
    assert [day(table, d)["cardio_min_24h"] for d in ("2026-06-09", "2026-06-10", "2026-06-11")] == [0, 0, 45]
    assert [day(table, d)["cardio_min_72h"] for d in ("2026-06-09", "2026-06-10", "2026-06-11")] == [0, 0, 45]


def test_no_activities_means_zero_training_not_a_gap(export):
    data = load_garmin(export)
    data = type(data)(folder=data.folder, sleep=data.sleep, vitals=data.vitals, activities=data.activities.iloc[0:0])
    empty = daily_table(data, ZONE)
    assert (empty[["strength_min_24h", "strength_load_24h", "cardio_min_72h"]] == 0).all().all()


def test_without_sleep_there_are_no_rows(export):
    data = load_garmin(export)
    nothing = daily_table(type(data)(folder=data.folder, sleep=data.sleep.iloc[0:0], vitals=data.vitals, activities=data.activities), ZONE)
    assert nothing.empty and list(nothing.columns) == list(DAILY_MEASURES)


# --- the page's interface ------------------------------------------------------------------

def test_the_overview_offers_the_nightly_measures(sleepy_world):
    state, _ = sleepy_world
    keys = [m["key"] for m in call(state, "/api/garmin/overview")["daily"]]
    assert keys == list(GARMIN_MEASURES)                                                   # no scale data loaded: no body measures


def test_two_measures_are_plotted_against_each_other(sleepy_world):
    state, sleep = sleepy_world
    d = call(state, "/api/garmin/pair", x="sleep_h", y="sleep_score", period="all")
    assert len(d["points"]) == d["days"] == len(sleep)
    assert d["fit"]["r"] > 0.99 and d["fit"]["n"] == len(sleep)                          # the score was made from the hours
    assert d["x_title"] != d["y_title"]


def test_a_measure_missing_on_some_nights_drops_only_those(sleepy_world):
    state, sleep = sleepy_world
    d = call(state, "/api/garmin/pair", x="hrv_ms", y="night_hr")
    assert d["fit"] is None                                                              # the made-up heart rate never varies
    assert len(d["points"]) == len(sleep)


def test_a_period_keeps_only_the_latest_nights(sleepy_world, monkeypatch):
    state, sleep = sleepy_world
    monkeypatch.setattr(service, "PAIR_DAYS", (20,))
    d = call(state, "/api/garmin/pair", x="sleep_h", y="sleep_score", period="days:20")
    assert d["days"] == 5 and d["points"][-1]["date"] == "2026-04-23"                  # nights 4 days apart, the last one is day 13


def test_bad_pair_requests_are_refused(sleepy_world, tmp_path):
    state, _ = sleepy_world
    with pytest.raises(api.ApiError, match="Unknown measure"):
        call(state, "/api/garmin/pair", x="sleep_h", y="mood")
    with pytest.raises(api.ApiError, match="Unknown period"):
        call(state, "/api/garmin/pair", x="sleep_h", y="deep_min", period="days:7")
    with pytest.raises(api.ApiError, match="Unknown period"):
        call(state, "/api/garmin/pair", x="sleep_h", y="deep_min", period="year:abc")


def test_without_garmin_data_the_pair_is_refused(tmp_path):
    from golf.dashboard.service import AppState
    from test_correlations import build_world
    config = build_world(tmp_path, sleep_hours=[8.0] * 14, speed_for=lambda k: 90.0, garmin=False)
    with pytest.raises(api.ApiError, match="No Garmin or Withings data"):
        call(AppState(config), "/api/garmin/pair", x="sleep_h", y="deep_min")


def test_a_calendar_year_can_be_chosen(sleepy_world):
    state, sleep = sleepy_world
    assert call(state, "/api/garmin/overview")["years"] == [2026]
    assert call(state, "/api/garmin/pair", x="sleep_h", y="sleep_score", period="year:2026")["days"] == len(sleep)
    other = call(state, "/api/garmin/pair", x="sleep_h", y="sleep_score", period="year:2025")
    assert other["days"] == 0 and other["points"] == [] and other["fit"] is None


def test_garmin_data_alone_is_enough(tmp_path):
    import re
    from golf.dashboard.service import AppState
    from test_correlations import build_world
    config = build_world(tmp_path, sleep_hours=[7.0 + 0.1 * k for k in range(14)], speed_for=lambda k: 90.0)
    text = config.read_text(encoding="utf-8")
    for key in ("swing_dir", "stack_dir"):
        text = re.sub(rf'{key} = ".*"', f'{key} = ""', text)
    config.write_text(text, encoding="utf-8")
    state = AppState(config)

    assert call(state, "/api/state")["datasets"]["garmin"]["loaded"]
    overview = call(state, "/api/garmin/overview")
    assert overview["loaded"] and overview["outcomes"] == [] and overview["clubs"] == []        # nothing to compare with
    d = call(state, "/api/garmin/pair", x="sleep_h", y="sleep_score", period="all")
    assert d["fit"]["r"] > 0.99
    with pytest.raises(api.ApiError, match="No stack data|No swing data"):
        call(state, "/api/garmin/table", outcome="stack_speed")


# --- trends over time ------------------------------------------------------------------------------

def test_rolling_means_count_days_and_need_enough_nights():
    from datetime import date, timedelta
    import pandas as pd
    from golf.stats.daily import rolling_means
    days = [date(2026, 1, 1) + timedelta(days=k) for k in range(30)]
    means = rolling_means(pd.Series([float(k) for k in range(30)], index=days))
    assert np.isnan(means["short"].iloc[1]) and means["short"].iloc[2] == pytest.approx(1.0)          # 3 nights are enough for the 7-day mean
    assert means["short"].iloc[29] == pytest.approx(26.0)                                          # days 23 to 29
    assert np.isnan(means["long"].iloc[8]) and means["long"].iloc[29] == pytest.approx(15.5)      # days 2 to 29
    assert rolling_means(pd.Series(dtype=float)).empty


def test_gaps_in_the_nights_are_counted_in_days_not_in_nights():
    from datetime import date
    import pandas as pd
    from golf.stats.daily import rolling_means
    series = pd.Series([10.0, 10.0, 10.0, 40.0], index=[date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 20)])
    means = rolling_means(series)
    assert np.isnan(means["short"].iloc[3])                                                         # a lone night 17 days later is not an average


def test_the_trend_follows_the_planted_change(sleepy_world):
    state, sleep = sleepy_world
    d = call(state, "/api/health/trend", measure="sleep_h", period="all")
    assert len(d["points"]) == d["days"] == len(sleep)
    assert d["points"][0]["value"] == pytest.approx(sleep[0], abs=0.02)
    assert d["latest"]["all"] == pytest.approx(float(np.mean(sleep)), abs=0.02)
    assert d["latest"]["short"] is None and d["latest"]["long"] is None                              # nights 4 days apart: too few per window
    assert d["title"] == DAILY_MEASURES["sleep_h"][0]


def test_a_trend_without_values_is_empty_not_an_error(sleepy_world):
    state, _ = sleepy_world
    d = call(state, "/api/health/trend", measure="sleep_h", period="year:2019")
    assert d["points"] == [] and d["latest"] is None


def test_bad_trend_requests_are_refused(sleepy_world):
    state, _ = sleepy_world
    with pytest.raises(api.ApiError, match="Unknown measure"):
        call(state, "/api/health/trend", measure="mood")
    with pytest.raises(api.ApiError, match="Unknown period"):
        call(state, "/api/health/trend", measure="sleep_h", period="week")
