import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from golf.data.garmin import CARDIO_TYPES, describe_garmin, find_export_folders, load_garmin
from golf.stats.context import PREDICTORS, session_context
from golf.stats.correlation import correlate
from golf.stats.outcomes import relative_to_usual, stack_speed, swing_speed, swing_spread

ZONE = "Europe/Zurich"


def ms(moment: datetime) -> float:
    return moment.replace(tzinfo=timezone.utc).timestamp() * 1000.0


def night(day, start, end, deep=90, light=300, rem=80, awake=10, score=80):
    return {
        "calendarDate": day, "sleepStartTimestampGMT": start, "sleepEndTimestampGMT": end,
        "deepSleepSeconds": deep * 60, "lightSleepSeconds": light * 60, "remSleepSeconds": rem * 60,
        "awakeSleepSeconds": awake * 60, "sleepScores": {"overallScore": score},
    }


def activity(kind, start_utc, minutes, load=10.0, **extra):
    return {"activityType": kind, "startTimeGmt": ms(start_utc), "duration": minutes * 60000.0, "avgHr": 95.0,
            "activityTrainingLoad": load, "totalSets": 20, "totalReps": 160, **extra}


@pytest.fixture
def export(tmp_path):
    """A small Garmin export: three nights, two mornings with vitals, some strength and cardio."""
    wellness = tmp_path / "DI_CONNECT" / "DI-Connect-Wellness"
    fitness = tmp_path / "DI_CONNECT" / "DI-Connect-Fitness"
    wellness.mkdir(parents=True), fitness.mkdir(parents=True)
    nights = [
        night("2026-06-09", "2026-06-08T21:00:00.0", "2026-06-09T05:00:00.0", deep=100, score=85),
        night("2026-06-10", "2026-06-09T21:30:00.0", "2026-06-10T05:30:00.0", deep=60, score=70),
        night("2026-06-11", "2026-06-10T22:00:00.0", "2026-06-11T04:00:00.0", deep=30, score=55),
        {"retro": False},                                  # records without data are skipped
    ]
    (wellness / "2026-06-01_2026-06-12_1_sleepData.json").write_text(json.dumps(nights), encoding="utf-8")
    # the next file overlaps by one night: the night must be counted once
    (wellness / "2026-06-11_2026-06-20_1_sleepData.json").write_text(json.dumps([nights[2]]), encoding="utf-8")
    health = [{"calendarDate": "2026-06-10", "metrics": [{"type": "HRV", "value": 52.0}, {"type": "HR", "value": 54.0}, {"type": "SPO2", "value": 95.0}]},
              {"calendarDate": "2026-06-11", "metrics": [{"type": "HRV", "value": 40.0}, {"type": "HR", "value": 60.0}]}]
    (wellness / "2026-06-01_2026-06-20_1_healthStatusData.json").write_text(json.dumps(health), encoding="utf-8")
    acts = [
        activity("strength_training", datetime(2026, 6, 9, 16, 0), 60, load=12.0),      # 18:00-19:00 local on 9 June
        activity("strength_training", datetime(2026, 6, 7, 16, 0), 60, load=20.0),
        activity("running", datetime(2026, 6, 10, 6, 0), 45),
        activity("walking", datetime(2026, 6, 10, 12, 0), 30),
        activity("golf", datetime(2026, 6, 10, 8, 0), 120),
    ]
    (fitness / "me_1_summarizedActivities.json").write_text(json.dumps([{"summarizedActivitiesExport": acts}]), encoding="utf-8")
    return tmp_path


# --- reading the export ---------------------------------------------------------------------

def test_the_export_folder_can_be_given_at_several_levels(export):
    for level in (export, export / "DI_CONNECT"):
        assert set(find_export_folders(level)) == {"wellness", "fitness"}
    assert set(find_export_folders(export / "DI_CONNECT" / "DI-Connect-Wellness" / "..")) == {"wellness", "fitness"}


def test_a_folder_without_an_export_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match="No Garmin export"):
        load_garmin(tmp_path)


def test_sleep_is_one_row_per_night(export):
    sleep = load_garmin(export).sleep
    assert [str(d) for d in sleep["date"]] == ["2026-06-09", "2026-06-10", "2026-06-11"]          # overlap counted once
    first = sleep.iloc[0]
    assert first["asleep_h"] == pytest.approx((100 + 300 + 80) / 60) and first["deep_min"] == 100 and first["score"] == 85
    assert str(first["end_utc"]) == "2026-06-09 05:00:00+00:00"


def test_vitals_and_activities(export):
    data = load_garmin(export)
    assert data.vitals.set_index("date").loc[date(2026, 6, 10), ["hrv_ms", "night_hr"]].tolist() == [52.0, 54.0]
    groups = data.activities.set_index("type")["group"].to_dict()
    assert groups == {"strength_training": "strength", "running": "cardio", "walking": "other", "golf": "other"}
    first = data.activities.iloc[0]
    assert first["end_utc"] - first["start_utc"] == timedelta(minutes=60) and "running" in CARDIO_TYPES


def test_the_summary_counts(export):
    summary = describe_garmin(load_garmin(export))
    assert summary == {"nights": 3, "mornings_with_hrv": 2, "strength": 2, "cardio": 1, "first": "2026-06-09", "last": "2026-06-11"}


# --- what happened before a session ---------------------------------------------------------------

def context(export, local_start):
    starts = pd.Series({local_start.date(): pd.Timestamp(local_start)})
    return session_context(starts, load_garmin(export), ZONE).iloc[0]


def test_the_night_before_and_the_morning_vitals(export):
    c = context(export, datetime(2026, 6, 10, 19, 30))            # the night ended 05:30 UTC = 07:30 local (summer time)
    assert c["sleep_h"] == pytest.approx((60 + 300 + 80) / 60) and c["sleep_score"] == 70 and c["deep_min"] == 60
    assert c["hrv_ms"] == 52.0 and c["night_hr"] == 54.0
    assert c["hours_awake"] == pytest.approx(12.0, abs=0.01)


def test_a_night_that_is_too_old_is_not_used(export):
    c = context(export, datetime(2026, 6, 14, 12, 0))
    assert np.isnan(c["sleep_h"]) and np.isnan(c["hrv_ms"]) and np.isnan(c["hours_awake"])


def test_strength_windows_use_the_end_of_the_session_and_local_time(export):
    c = context(export, datetime(2026, 6, 9, 21, 0))              # strength ended 19:00 local = 17:00 UTC, golf 21:00 local
    assert c["strength_24h"] == 1 and c["strength_72h"] == 2 and c["strength_hours_since"] == pytest.approx(2.0)
    assert c["strength_load_72h"] == pytest.approx(32.0) and c["strength_min_72h"] == pytest.approx(120.0)


def test_a_strength_session_that_has_not_ended_does_not_count(export):
    c = context(export, datetime(2026, 6, 9, 18, 30))             # the session is still going on (18:00-19:00 local)
    assert c["strength_24h"] == 0 and c["strength_72h"] == 1
    assert c["strength_hours_since"] == pytest.approx(47.5, abs=0.01)         # the one on 7 June ended 17:00 UTC


def test_cardio_windows_and_other_activities(export):
    c = context(export, datetime(2026, 6, 10, 19, 0))
    assert c["cardio_min_48h"] == pytest.approx(45.0) and c["cardio_min_7d"] == pytest.approx(45.0)      # walking and golf do not count
    assert context(export, datetime(2026, 6, 20, 19, 0))["cardio_min_7d"] == 0.0


def test_time_of_day_and_all_predictors_are_present(export):
    c = context(export, datetime(2026, 6, 10, 19, 30))
    assert c["session_hour"] == pytest.approx(19.5) and list(c.index) == list(PREDICTORS)


def test_daylight_saving_time_is_handled(export):
    summer = context(export, datetime(2026, 6, 9, 19, 30))        # 17:30 UTC; the strength session ended 17:00 UTC
    assert summer["strength_hours_since"] == pytest.approx(0.5)
    data = load_garmin(export)
    activities = data.activities.copy()
    activities["start_utc"] = pd.Timestamp("2026-01-15 09:00", tz="UTC")
    activities["end_utc"] = pd.Timestamp("2026-01-15 10:00", tz="UTC")
    winter_data = type(data)(folder=data.folder, sleep=data.sleep, vitals=data.vitals, activities=activities)
    starts = pd.Series({date(2026, 1, 15): pd.Timestamp(datetime(2026, 1, 15, 12, 0))})
    winter = session_context(starts, winter_data, ZONE).iloc[0]
    assert winter["strength_hours_since"] == pytest.approx(1.0)   # 12:00 local = 11:00 UTC in winter, strength ended 10:00 UTC


# --- correlation ---------------------------------------------------------------------------------------

def test_correlation_of_a_straight_line_and_of_noise():
    x = np.arange(20.0)
    perfect = correlate(x, 2 * x + 1)
    assert perfect.r == pytest.approx(1.0, abs=1e-4) and perfect.slope == pytest.approx(2.0) and perfect.intercept == pytest.approx(1.0)
    rng = np.random.default_rng(1)
    noisy = correlate(rng.normal(size=40), rng.normal(size=40))
    assert noisy.low < noisy.r < noisy.high and noisy.low < 0 < noisy.high


def test_the_interval_is_wide_with_few_sessions():
    rng = np.random.default_rng(2)
    x = rng.normal(size=8)
    y = 0.5 * x + rng.normal(size=8)
    c = correlate(x, y)
    assert c.n == 8 and c.high - c.low > 0.8


def test_the_interval_covers_the_true_correlation():
    rng = np.random.default_rng(3)
    hits, runs = 0, 400
    for _ in range(runs):
        x = rng.normal(size=25)
        y = 0.4 * x + np.sqrt(1 - 0.4 ** 2) * rng.normal(size=25)
        c = correlate(x, y)
        hits += c.low <= 0.4 <= c.high
    assert 0.92 < hits / runs < 0.98


def test_no_correlation_when_there_is_nothing_to_correlate():
    assert correlate([1, 2, 3, 4], [1, 2, 3, 4]) is None                     # too few pairs
    assert correlate(np.arange(10.0), np.ones(10)) is None                  # one of them is constant
    assert correlate([1, 2, np.nan, 4, 5, 6, 7], [2, 3, 4, np.nan, 6, 7, 9]).n == 5      # missing values are dropped


# --- one result number per session --------------------------------------------------------------------------

def swing_table(dates, speeds_by_club):
    rows = []
    for club, speeds in speeds_by_club.items():
        for day, speed in zip(dates, speeds):
            rows += [{"session_date": day, "label": club, "club_speed_mph": speed + k * 0.01, "carry_m": 100 + 5 * (k % 3)} for k in range(6)]
    return pd.DataFrame(rows)


DAYS = [date(2026, 3, 1) + timedelta(days=7 * k) for k in range(8)]


def test_a_steady_improvement_is_removed_by_the_trend():
    rising = [90 + 0.5 * k for k in range(8)]
    swing = swing_table(DAYS, {"7i": rising})
    raw = swing_speed(swing, detrend=False)
    flat = swing_speed(swing, detrend=True)
    assert raw["value"].iloc[-1] > 1.5 and raw["value"].iloc[0] < -1.5          # percent above and below the average
    assert flat["value"].abs().max() < 0.1                                       # nothing is left once the trend is taken out


def test_a_single_good_session_stands_out_after_removing_the_trend():
    speeds = [90 + 0.5 * k for k in range(8)]
    speeds[5] += 3.0
    flat = swing_speed(swing_table(DAYS, {"7i": speeds}), detrend=True).set_index("date")["value"]
    assert flat.idxmax() == DAYS[5] and flat.max() > 2.0


def test_clubs_are_combined_into_one_number_per_session():
    swing = swing_table(DAYS, {"7i": [90.0] * 8, "pw": [100.0, 100, 100, 110, 100, 100, 100, 100]})
    both = swing_speed(swing, detrend=False).set_index("date")
    assert both["clubs"].tolist() == [2] * 8
    only_pw = swing_speed(swing, detrend=False, club="pw").set_index("date")
    assert only_pw.loc[DAYS[3], "value"] > 8 and both.loc[DAYS[3], "value"] == pytest.approx(only_pw.loc[DAYS[3], "value"] / 2, rel=0.2)


def test_a_club_seen_in_one_session_and_small_samples_are_ignored():
    swing = swing_table(DAYS[:3], {"7i": [90, 91, 92]})
    swing = pd.concat([swing, swing_table(DAYS[:1], {"driver": [100]})])
    assert swing_speed(swing, detrend=False)["clubs"].tolist() == [1, 1, 1]
    assert swing_speed(swing, detrend=False, min_shots=7).empty


def test_carry_spread_is_compared_with_the_usual_spread():
    rows = []
    for k, day in enumerate(DAYS):
        spread = 8.0 if k != 4 else 16.0
        rows += [{"session_date": day, "label": "7i", "club_speed_mph": 90.0, "carry_m": 150 + v} for v in np.linspace(-spread, spread, 8)]
    out = swing_spread(pd.DataFrame(rows), detrend=False).set_index("date")["value"]
    assert out.idxmax() == DAYS[4] and out.max() > 50


def stack_table(weights_by_day, offset_by_day, slope=-0.1):
    rows = []
    for day, weights in weights_by_day.items():
        for weight in weights:
            rows += [{"session_date": day, "weight_g": float(weight), "club_speed_mph": 120 + slope * weight + offset_by_day[day] + 0.01 * k} for k in range(8)]
    return pd.DataFrame(rows)


def test_stack_speed_is_moved_to_one_weight():
    plan = {DAYS[0]: [195, 235], DAYS[1]: [195, 160], DAYS[2]: [195, 95], DAYS[3]: [195, 240]}
    offsets = {DAYS[0]: 0.0, DAYS[1]: 2.0, DAYS[2]: -1.0, DAYS[3]: 1.0}
    out = stack_speed(stack_table(plan, offsets), detrend=False).set_index("date")
    assert set(out["weight"]) == {195.0}
    expected = {day: 120 - 0.1 * 195 + off for day, off in offsets.items()}
    for day, value in expected.items():
        assert out.loc[day, "value"] == pytest.approx(value, abs=0.05)           # the weight mix does not matter any more


def test_stack_speed_without_the_weight_correction_would_be_misleading():
    plan = {DAYS[0]: [195, 235], DAYS[1]: [195, 95]}
    raw_mean = stack_table(plan, {DAYS[0]: 0.0, DAYS[1]: 0.0}).groupby("session_date")["club_speed_mph"].mean()
    assert raw_mean.iloc[1] - raw_mean.iloc[0] > 3                               # looks like a big gain, but it is only lighter clubs
    out = stack_speed(stack_table(plan, {DAYS[0]: 0.0, DAYS[1]: 0.0}), detrend=False)["value"]
    assert abs(out.iloc[1] - out.iloc[0]) < 0.1


def test_stack_speed_trend_removal_and_empty_input():
    plan = {day: [195] for day in DAYS}
    rising = {day: 0.4 * k for k, day in enumerate(DAYS)}
    assert stack_speed(stack_table(plan, rising), detrend=True)["value"].abs().max() < 0.1
    assert stack_speed(stack_table(plan, rising).iloc[0:0], detrend=False).empty


def test_relative_to_usual_needs_two_sessions_per_club():
    table = pd.DataFrame({"date": [DAYS[0]], "club": ["7i"], "value": [90.0]})
    assert relative_to_usual(table, detrend=True).empty
