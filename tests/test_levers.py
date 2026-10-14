import numpy as np
import pandas as pd
import pytest

from golf.dashboard import api
from golf.stats.levers import BALL_FLIGHT, CLUB, GROUPS, MIN_SESSIONS, MIN_SHOTS, distance_levers, levers_of

from test_dashboard import call, state  # noqa: F401  (fixture)

COLUMNS = {   # column -> (mean, sd), as for a 7-iron
    "club_speed_mph": (90.0, 1.6), "smash": (1.30, 0.04), "launch_v_deg": (20.0, 1.7), "spin_rpm": (4900.0, 700.0),
    "aoa_deg": (-2.5, 1.2), "dynamic_loft_deg": (28.0, 3.2), "club_path_deg": (-1.8, 2.0), "ftp_deg": (0.6, 2.5),
}


def club_frame(effects, *, sessions=8, per_session=12, noise=1.0, seed=3):
    """Shots of one club. `effects` maps a column to the planted carry change (m) per standard deviation."""
    rng = np.random.default_rng(seed)
    n = sessions * per_session
    z = {column: (v - v.mean()) / v.std(ddof=1) for column, v in ((c, rng.normal(size=n)) for c in COLUMNS)}   # exactly standard: planted effects are exact
    frame = pd.DataFrame({column: mean + sd * z[column] for column, (mean, sd) in COLUMNS.items()})
    frame["carry_m"] = 160.0 + sum(effect * z[column] for column, effect in effects.items()) + rng.normal(0, noise, n)
    frame["session_date"] = [f"2026-03-{1 + k // per_session:02d}" for k in range(n)]
    return frame


def factor(levers, key):
    return next(f for f in levers.factors if f.key == key)


# --- the statistics --------------------------------------------------------------------------------------

def test_planted_effects_are_recovered_with_intervals_that_hold_them():
    frame = club_frame({"club_speed_mph": 3.0, "smash": 6.0, "launch_v_deg": 0.0, "spin_rpm": -3.0})
    levers = distance_levers(frame)["ball"]
    for key, planted in (("club_speed_mph", 3.0), ("smash", 6.0), ("spin_rpm", -3.0)):
        f = factor(levers, key)
        assert f.effect == pytest.approx(planted, abs=0.5) and f.clear and f.low < f.effect < f.high
        assert f.low == pytest.approx(planted, abs=1.5) and f.high == pytest.approx(planted, abs=1.5)    # a narrow interval around the truth
    launch = factor(levers, "launch_v_deg")
    assert abs(launch.effect) < 0.5                                                              # nothing planted: close to zero
    assert levers.r2 > 0.95 and levers.n == 96 and levers.sessions == 8


def test_the_effect_is_per_standard_deviation_whatever_the_unit():
    small_unit = club_frame({"smash": 4.0})
    scaled = small_unit.assign(smash=small_unit["smash"] * 100)                                 # the same factor in other units
    assert factor(distance_levers(scaled)["ball"], "smash").effect == pytest.approx(factor(distance_levers(small_unit)["ball"], "smash").effect)
    assert factor(distance_levers(small_unit)["ball"], "smash").sd == pytest.approx(0.04, abs=0.01)


def test_the_two_views_use_their_own_factors():
    levers = distance_levers(club_frame({"aoa_deg": 2.0, "ftp_deg": -4.0}))
    assert [f.key for f in levers["ball"].factors] == [c for c, *_ in BALL_FLIGHT]
    assert [f.key for f in levers["club"].factors] == [c for c, *_ in CLUB]
    assert factor(levers["club"], "ftp_deg").effect == pytest.approx(-4.0, abs=0.5) and factor(levers["club"], "ftp_deg").clear
    assert levers["club"].r2 > 0.8 and levers["ball"].r2 < 0.2                                  # the planted effects are on the club side only


def test_club_head_speed_is_not_a_lever_and_never_the_biggest():
    levers = distance_levers(club_frame({"club_speed_mph": 9.0, "smash": 3.0}))["ball"]
    assert not factor(levers, "club_speed_mph").lever
    assert levers.biggest().key == "smash"


def test_the_biggest_lever_is_the_largest_clear_one_in_either_direction():
    levers = distance_levers(club_frame({"smash": 2.0, "spin_rpm": -5.0, "launch_v_deg": 0.0}))["ball"]
    assert levers.biggest().key == "spin_rpm"                                                   # 5 m less carry per sd of spin: larger than 2 m
    assert distance_levers(club_frame({"club_speed_mph": 4.0}))["ball"].biggest() is None


def test_the_intervals_allow_for_sessions_so_session_effects_widen_them():
    rng = np.random.default_rng(5)
    frame = club_frame({"smash": 2.0}, sessions=6, per_session=20)
    frame["carry_m"] += np.repeat(rng.normal(0, 8, 6), 20)                                       # whole sessions are longer or shorter
    wide = factor(distance_levers(frame)["ball"], "smash")
    narrow = factor(distance_levers(club_frame({"smash": 2.0}, sessions=6, per_session=20))["ball"], "smash")
    assert wide.high - wide.low > narrow.high - narrow.low


def test_the_result_is_the_same_every_time():
    frame = club_frame({"smash": 5.0})
    a, b = distance_levers(frame)["ball"], distance_levers(frame)["ball"]
    assert factor(a, "smash").low == factor(b, "smash").low and factor(a, "smash").effect == factor(b, "smash").effect


def test_with_few_sessions_the_intervals_are_wide():
    many = factor(distance_levers(club_frame({"smash": 5.0}, sessions=16, per_session=6))["ball"], "smash")
    few = factor(distance_levers(club_frame({"smash": 5.0}, sessions=MIN_SESSIONS, per_session=24))["ball"], "smash")
    assert few.high - few.low > 1.2 * (many.high - many.low)                                    # fewer sessions: a wider interval


def test_an_effect_that_does_not_exist_is_rarely_called_clear():
    false_clear = 0
    runs = 120
    for seed in range(runs):
        levers = distance_levers(club_frame({"smash": 5.0, "club_speed_mph": 3.0}, sessions=6, per_session=12, noise=3.0, seed=100 + seed))["ball"]
        false_clear += factor(levers, "launch_v_deg").clear
    assert false_clear / runs < 0.12                                                            # nominally 5%; the old bootstrap gave about 15% here


def test_a_wider_level_gives_a_wider_interval():
    frame = club_frame({"smash": 5.0})
    narrow = factor(levers_of(frame, BALL_FLIGHT, level=0.5), "smash")
    wide = factor(levers_of(frame, BALL_FLIGHT, level=0.99), "smash")
    assert wide.high - wide.low > narrow.high - narrow.low


def test_too_few_shots_or_sessions_give_nothing():
    assert distance_levers(club_frame({"smash": 5.0}, sessions=8, per_session=3))["ball"] is None            # 24 shots
    assert distance_levers(club_frame({"smash": 5.0}, sessions=MIN_SESSIONS - 1, per_session=20))["ball"] is None
    assert distance_levers(club_frame({"smash": 5.0}, sessions=MIN_SESSIONS, per_session=MIN_SHOTS // MIN_SESSIONS + 1))["ball"] is not None


def test_shots_without_all_factors_are_left_out_and_a_missing_view_is_none():
    frame = club_frame({"smash": 5.0})
    frame.loc[:20, "launch_v_deg"] = np.nan
    assert distance_levers(frame)["ball"].n == 96 - 21
    assert distance_levers(frame.drop(columns=["ftp_deg"]))["club"] is None and distance_levers(frame.drop(columns=["ftp_deg"]))["ball"] is not None


def test_a_factor_that_never_varies_gives_nothing():
    frame = club_frame({"smash": 5.0})
    frame["spin_rpm"] = 4900.0
    assert distance_levers(frame)["ball"] is None and distance_levers(frame)["club"] is not None


# --- in the dashboard -------------------------------------------------------------------------------------

@pytest.fixture
def lever_state(state):
    """The dashboard state with the ball flight columns added to the swing shots (the test CSVs only have a few columns)."""
    shots = state.shots["swing"].copy()
    rng = np.random.default_rng(4)
    for column, (mean, sd) in COLUMNS.items():
        shots[column] = mean + sd * rng.normal(size=len(shots))
    z_smash = (shots["smash"] - 1.30) / 0.04
    z_launch = (shots["launch_v_deg"] - 20.0) / 1.7
    shots["carry_m"] = 150.0 + 5.0 * z_smash + 3.0 * z_launch + rng.normal(0, 1.0, len(shots))
    state.shots["swing"] = shots
    return state


def test_a_club_gets_both_views_with_a_verdict(lever_state):
    d = call(lever_state, "/api/swing/levers", label="driver ping")
    assert d["ok"] and [g["key"] for g in d["groups"]] == ["ball", "club"] and d["level"] == 0.95
    ball = d["groups"][0]
    assert ball["ok"] and ball["n"] == 72 and ball["sessions"] == 6 and 0.8 < ball["r2"] <= 1
    effects = {f["key"]: f for f in ball["factors"]}
    assert effects["smash"]["effect"] == pytest.approx(5.0, abs=1.0) and effects["smash"]["clear"] and effects["launch_v_deg"]["clear"]
    assert not effects["spin_rpm"]["clear"] and effects["smash"]["lever"] and not effects["club_speed_mph"]["lever"]
    assert ball["verdict"].startswith("Largest lever for the driver ping: smash factor (+") and "launch angle" in ball["verdict"]
    assert "spin" not in ball["verdict"]                                                           # no clear effect: not mentioned


def test_a_view_without_a_clear_lever_says_so(lever_state):
    club = call(lever_state, "/api/swing/levers", label="driver ping")["groups"][1]                # nothing planted on the club side
    assert club["ok"] and "no factor has a clear effect" in club["verdict"]


def test_a_club_with_too_few_shots_says_what_is_needed(lever_state):
    d = call(lever_state, "/api/swing/levers", label="gw 50")
    assert d["ok"] is False and all(not g["ok"] and "at least 30 shots" in g["reason"] for g in d["groups"])


def test_an_unknown_club_is_refused(lever_state):
    with pytest.raises(api.ApiError, match="Unknown club"):
        call(lever_state, "/api/swing/levers", label="putter")


def test_the_bag_overview_has_a_row_per_club(lever_state):
    d = call(lever_state, "/api/swing/levers-bag")
    assert [r["label"] for r in d["rows"]] == ["driver ping", "7i 245", "gw 50"] and [g["key"] for g in d["groups"]] == ["ball", "club"]
    driver = d["rows"][0]
    assert driver["shots"] == 72 and driver["groups"]["ball"]["ok"] and driver["groups"]["ball"]["biggest"] == "smash"
    assert driver["groups"]["club"]["biggest"] is None
    assert d["rows"][2]["groups"]["ball"] == {"ok": False}
    # the overview and the single club agree
    single = call(lever_state, "/api/swing/levers", label="driver ping")["groups"][0]["factors"]
    assert [f["effect"] for f in driver["groups"]["ball"]["factors"]] == [f["effect"] for f in single]


def test_only_the_selected_sessions_and_clubs_are_used(lever_state):
    sessions = [s["date"] for s in call(lever_state, "/api/sessions", mode="swing")["sessions"]]
    call(lever_state, "/api/sessions", method="POST", mode="swing", selected=sessions[:4])
    assert call(lever_state, "/api/swing/levers", label="driver ping")["groups"][0]["sessions"] == 4
    call(lever_state, "/api/sessions", method="POST", mode="swing", selected=sessions[:3])
    assert call(lever_state, "/api/swing/levers", label="driver ping")["groups"][0]["ok"] is False   # three sessions are too few


def test_without_swing_data_the_overview_is_empty(tmp_path):
    from test_stack import write_stack  # noqa: F401
    import re
    from golf.config import DEFAULT_CONFIG
    from golf.dashboard.service import AppState
    text = DEFAULT_CONFIG.read_text(encoding="utf-8")
    for key in ("swing_dir", "pitching_dir", "stack_dir", "garmin_dir", "withings_dir", "competition_dir"):
        text = re.sub(rf'{key} = ".*"', f'{key} = ""', text)
    (tmp_path / "golf.toml").write_text(text, encoding="utf-8")
    empty = AppState(tmp_path / "golf.toml")
    assert call(empty, "/api/swing/levers-bag")["rows"] == []
    with pytest.raises(api.ApiError, match="Unknown club"):
        call(empty, "/api/swing/levers", label="driver ping")


def test_the_groups_are_documented_in_one_place():
    assert [key for key, _, _ in GROUPS] == ["ball", "club"]
