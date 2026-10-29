from functools import lru_cache

import numpy as np
import pandas as pd
import pytest

from golf.dashboard import api
from golf.stats.driver import MIN_SESSIONS, MIN_SHOTS, analyse_driver
from golf.stats.flightmodel import MPH, FlightModel, fit_flight_model, simulate
from golf.targets import OptimalChart, Targets, load_targets

from test_dashboard import call, state  # noqa: F401  (fixture)
from test_targets import REPO_TARGETS

TRUE = (0.21, 0.07, 1.9, 0.17)           # drag, drag with spin, lift, lift limit: the "simulator" of the tests


def drive(ball_mph, launch, spin, params=TRUE):
    return simulate(np.atleast_1d(ball_mph) * MPH, launch, spin, params)


def shots(n=120, sessions=6, *, launch_shift=0.0, noise=0.0, seed=1):
    """Driver shots whose carry and peak height come from the model above; `launch_shift` moves every launch angle (deg)."""
    rng = np.random.default_rng(seed)
    ball = rng.normal(147, 4, n)
    aoa = rng.normal(2.0, 1.5, n)
    chart = load_targets(REPO_TARGETS).chart
    best_launch, best_spin = chart.lookup(ball, aoa)
    launch = best_launch + launch_shift + rng.normal(0, 0.8, n)
    spin = best_spin + rng.normal(0, 150, n)
    axis = rng.normal(0, 4, n)
    carry, apex, _ = drive(ball, launch, spin * np.cos(np.radians(axis)))
    frame = pd.DataFrame({"ball_speed_mph": ball, "aoa_deg": aoa, "launch_v_deg": launch, "spin_rpm": spin, "spin_axis_deg": axis,
                          "carry_m": carry + rng.normal(0, noise, n), "height_m": apex,
                          "session_date": [f"2026-04-{1 + k % sessions:02d}" for k in range(n)]})
    return frame, chart


@lru_cache(maxsize=None)
def result(launch_shift=0.0, n=120, sessions=6, noise=0.0):
    """The analysis of `shots(...)`, calculated once per set of arguments (fitting the flight model takes a second)."""
    return analyse_driver(*shots(n=n, sessions=sessions, launch_shift=launch_shift, noise=noise))


# --- the flight model -------------------------------------------------------------------------------------

def test_a_drive_flies_a_plausible_distance_and_height():
    carry, apex, flight = drive(147, 13.0, 2500)
    assert 200 < carry[0] < 260 and 20 < apex[0] < 50 and 4 < flight[0] < 9


def test_more_launch_carries_further_in_the_range_of_a_drive_and_no_spin_falls_short():
    carries = [drive(147, a, 2500)[0][0] for a in (6.0, 9.0, 12.0, 14.0)]
    assert carries == sorted(carries) and carries[-1] - carries[0] > 10                # up to about 14 deg, where the data of a drive is
    assert drive(147, 13.0, 0.0)[0][0] < drive(147, 13.0, 2500)[0][0]                 # backspin lifts the ball
    assert drive(147, 13.0, 2500)[0][0] > drive(130, 13.0, 2500)[0][0]


def test_the_model_finds_the_numbers_that_made_the_shots():
    frame, _ = shots(noise=0.0)
    back = frame["spin_rpm"] * np.cos(np.radians(frame["spin_axis_deg"]))
    model = fit_flight_model(frame["ball_speed_mph"], frame["launch_v_deg"], back, frame["carry_m"], frame["height_m"])
    assert model.rmse < 0.5 and model.r2 > 0.99 and model.n == 120
    again = model.carry([147.0], [13.0], [2500.0])[0]
    assert again == pytest.approx(drive(147, 13.0, 2500)[0][0], abs=1.0)


def test_noise_in_the_carries_shows_in_the_fit_quality():
    frame, _ = shots(noise=3.0)
    back = frame["spin_rpm"] * np.cos(np.radians(frame["spin_axis_deg"]))
    model = fit_flight_model(frame["ball_speed_mph"], frame["launch_v_deg"], back, frame["carry_m"], frame["height_m"])
    assert 2.0 < model.rmse < 4.5 and model.r2 < 0.99 and model.carry_sd > 3.0


def test_too_few_or_unusable_shots_give_no_model():
    assert fit_flight_model([140.0] * 10, [12.0] * 10, [2500.0] * 10, [210.0] * 10) is None
    assert fit_flight_model([np.nan] * 60, [12.0] * 60, [2500.0] * 60, [210.0] * 60) is None


# --- the analysis -----------------------------------------------------------------------------------------

def test_shots_on_the_chart_have_nothing_to_gain():
    r = result(launch_shift=0.0)
    assert abs(r["gaps"]["launch"]["mean"]) < 0.3 and abs(r["gaps"]["spin"]["mean"]) < 60
    assert abs(r["gains"]["both"]["mean"]) < 1.0 and r["gains"]["both"]["lo"] < 0.5 < r["gains"]["both"]["hi"] + 1.0


def test_a_launch_angle_below_the_chart_costs_carry_and_the_gain_is_found():
    r = result(launch_shift=-2.5)
    assert r["gaps"]["launch"]["mean"] == pytest.approx(-2.5, abs=0.3) and r["gaps"]["launch"]["hi"] < -2.0
    assert r["gains"]["launch"]["mean"] > 3.0 and r["gains"]["launch"]["lo"] > 2.0              # clearly worth something
    assert abs(r["gains"]["spin"]["mean"]) < 1.0                                                  # the spin was fine
    t = r["typical"]
    assert t["launch"] == pytest.approx(t["opt_launch"] - 2.5, abs=0.3) and t["spin"] == pytest.approx(t["opt_spin"], abs=60)


def test_the_gain_is_what_the_model_says_for_the_shifted_launch():
    frame, _ = shots(launch_shift=-2.0, n=200)
    r = result(launch_shift=-2.0, n=200)
    direct = np.mean([drive(b, l + 2.0, s * np.cos(np.radians(a)))[0][0] - drive(b, l, s * np.cos(np.radians(a)))[0][0]
                      for b, l, s, a in zip(frame["ball_speed_mph"], frame["launch_v_deg"], frame["spin_rpm"], frame["spin_axis_deg"])])
    assert r["gains"]["launch"]["mean"] == pytest.approx(direct, abs=0.6)                         # the chart value is the shift back, up to the 0.8 deg scatter


def test_the_typical_shot_table_lists_the_what_ifs_in_order():
    r = result(launch_shift=-2.0)
    kinds = [s["kind"] for s in r["scenarios"]]
    assert kinds == ["now", "launch", "spin", "both", "aoa", "aoa", "aoa", "speed"]
    now, launch, spin, both, a1, a2, a3, speed = r["scenarios"]
    assert now["gain"] == 0 and launch["launch"] > now["launch"] and launch["spin"] == now["spin"] and spin["launch"] == now["launch"]
    assert both["gain"] == pytest.approx(launch["gain"] + spin["gain"], abs=1.0) and both["launch"] == launch["launch"]
    assert a1["launch"] > both["launch"] and a3["launch"] > a2["launch"] > a1["launch"] and a3["spin"] < a1["spin"]      # a steeper upswing: more launch, less spin
    assert a1["gain_over_chart"] == pytest.approx(a1["carry"] - both["carry"]) and a3["gain_over_chart"] > a1["gain_over_chart"] > 0
    assert speed["gain"] == pytest.approx(2.2, abs=0.8) and speed["launch"] == now["launch"]


def test_every_session_gets_its_gap_and_gain():
    frame, _ = shots(launch_shift=-2.0, sessions=6, n=120)
    r = result(launch_shift=-2.0)
    assert [row["session"] for row in r["session_rows"]] == sorted(set(frame["session_date"])) and sum(row["shots"] for row in r["session_rows"]) == 120
    assert all(row["launch_gap"] < -1.0 and row["gain"] > 1.0 for row in r["session_rows"])


def test_the_share_close_to_the_chart_uses_the_window():
    r = result(launch_shift=0.0, n=200)
    assert r["window"] == {"launch": 1.0, "spin": 250.0} and 55 < r["close"] < 95                  # launch scatter 0.8 deg, spin scatter 150 rpm
    far = result(launch_shift=-4.0, n=200)
    assert far["close"] < 5


def test_the_map_has_the_carry_over_launch_and_spin():
    r = result(launch_shift=0.0)
    m = r["map"]
    assert len(m["carry"]) == len(m["spin"]) and len(m["carry"][0]) == len(m["launch"])
    z = np.array(m["carry"])
    assert np.nanmax(z) > np.nanmin(z) + 20 and np.nanargmax(z.max(axis=0)) > np.nanargmin(z.max(axis=0))     # best at a higher launch than the lowest


def test_the_map_stays_near_your_shots_and_includes_the_chart_value():
    frame, _ = shots(launch_shift=-2.0)
    r = result(launch_shift=-2.0)
    m, t = r["map"], r["typical"]
    assert m["launch"][0] <= frame["launch_v_deg"].min() + 1.0 and m["launch"][-1] >= frame["launch_v_deg"].max() - 1.0
    assert m["launch"][0] > frame["launch_v_deg"].min() - 4.0 and m["launch"][-1] < frame["launch_v_deg"].max() + 4.0      # not out to launch angles you never hit
    assert m["launch"][0] <= t["opt_launch"] <= m["launch"][-1] and m["spin"][0] <= t["opt_spin"] <= m["spin"][-1]


def test_the_points_are_the_shots_and_the_chart_value_of_each():
    r = result(launch_shift=-1.0)
    assert len(r["points"]) == 120 and {"launch", "spin", "carry", "opt_launch", "opt_spin"} <= set(r["points"][0])


def test_too_little_data_gives_nothing():
    frame, chart = shots(n=MIN_SHOTS - 1, sessions=4)
    assert analyse_driver(frame, chart) is None
    frame, chart = shots(n=90, sessions=MIN_SESSIONS - 1)
    assert analyse_driver(frame, chart) is None
    frame, chart = shots()
    assert analyse_driver(frame.drop(columns=["spin_axis_deg"]), chart) is None


def test_shots_with_missing_numbers_are_left_out():
    frame, chart = shots(n=120)
    frame.loc[:19, "height_m"] = np.nan
    assert analyse_driver(frame, chart)["n"] == 100


def test_a_given_model_is_reused():
    frame, chart = shots()
    first = result()
    second = analyse_driver(frame, chart, model=first["_model"])
    assert second["model"] == first["model"] and second["gains"]["both"]["mean"] == first["gains"]["both"]["mean"]
    assert isinstance(first["_model"], FlightModel)


# --- in the dashboard -------------------------------------------------------------------------------------

@pytest.fixture
def driver_state(state):
    """The dashboard state with driver shots that carry the ball flight columns the analysis needs."""
    data = state.shots["swing"].copy()
    is_driver = (data["club"] == "driver").to_numpy()
    n = int(is_driver.sum())
    frame, chart = shots(n=n, sessions=data.loc[is_driver, "session_date"].nunique(), launch_shift=-2.0)
    for column in ("ball_speed_mph", "aoa_deg", "launch_v_deg", "spin_rpm", "spin_axis_deg", "carry_m", "height_m"):
        data.loc[is_driver, column] = frame[column].to_numpy()
    state.shots["swing"] = data
    state.targets = load_targets(REPO_TARGETS)
    return state


def test_the_driver_analysis_reaches_the_page(driver_state):
    d = call(driver_state, "/api/swing/driver")
    assert d["ok"] and d["labels"] == ["driver ping"] and d["chart"]["speeds"][0] == 200.0 and d["chart"]["aoas"][0] == -10.0
    assert d["gains"]["launch"]["mean"] > 2.0 and "below the chart value" in d["verdict"] and "would add about" in d["verdict"]
    assert d["model"]["r2"] > 0.9 and d["folder"].endswith("targets") and len(d["chart"]["launch"]) == 13


def test_the_fitted_model_is_kept_for_the_next_request(driver_state):
    call(driver_state, "/api/swing/driver")
    assert len(driver_state.driver_models) == 1
    call(driver_state, "/api/swing/driver")
    assert len(driver_state.driver_models) == 1


def test_a_driver_can_be_chosen_by_name(driver_state):
    assert call(driver_state, "/api/swing/driver", label="driver ping")["label"] == "driver ping"
    with pytest.raises(api.ApiError, match="Unknown club"):
        call(driver_state, "/api/swing/driver", label="7i 245")


def test_without_the_chart_the_page_is_told_why(state):
    state.targets = Targets(None, notes=["driver_optimal_launch.csv not found in somewhere"])
    d = call(state, "/api/swing/driver")
    assert d["ok"] is False and "not available" in d["reason"] and d["notes"] == ["driver_optimal_launch.csv not found in somewhere"]


def test_without_driver_shots_the_page_is_told_why(state):
    state.targets = load_targets(REPO_TARGETS)
    shots_ = state.shots["swing"]
    state.shots["swing"] = shots_[shots_["club"] != "driver"]
    d = call(state, "/api/swing/driver")
    assert d["ok"] is False and "No driver shots" in d["reason"]


def test_too_few_driver_shots_say_what_is_needed(state):
    state.targets = load_targets(REPO_TARGETS)
    d = call(state, "/api/swing/driver")                       # the test CSVs have no ball flight columns at all
    assert d["ok"] is False and "at least 30 driver shots" in d["reason"]
