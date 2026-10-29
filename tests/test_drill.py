from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from golf.dashboard import api
from golf.data import drill as store
from golf.stats import drill as ds

from test_dashboard import call, state  # noqa: F401  (fixture)


def pitching(wedges, *, shots=40, noise=3.0, seed=2):
    """Pitching shots: carry = intercept + slope * speed + noise over speeds from 40 to 85 mph. wedges: name -> (intercept, slope)."""
    rng = np.random.default_rng(seed)
    rows = []
    for name, (intercept, slope) in wedges.items():
        club, _, variant = name.partition(" ")
        for speed in rng.uniform(40, 85, shots):
            rows.append({"club": club, "variant": variant, "club_speed_mph": speed, "carry_m": intercept + slope * speed + rng.normal(0, noise)})
    return pd.DataFrame(rows)


WEDGES = {"gw 50": (-10.0, 1.3), "sw 54": (-15.0, 1.1)}


def fits(**kwargs):
    return ds.wedge_fits(pitching(WEDGES, **kwargs))["fits"]


# --- targets --------------------------------------------------------------------------------------------

def test_the_line_of_carry_against_speed_is_found_per_wedge_in_bag_order():
    found = ds.wedge_fits(pitching({"sw 54": (-15.0, 1.1), "pw 241": (0.0, 1.5), "gw 50": (-10.0, 1.3)}))["fits"]
    assert [f.wedge for f in found] == ["pw 241", "gw 50", "sw 54"]
    gw = found[1]
    assert gw.slope == pytest.approx(1.3, abs=0.1) and gw.intercept == pytest.approx(-10.0, abs=5) and gw.r2 > 0.9 and gw.n == 40
    assert gw.resid_sd == pytest.approx(3.0, abs=1.0) and 40 <= gw.speed_min < gw.speed_max <= 85


def test_a_target_speed_gives_the_target_distance_on_the_line():
    f = fits()[0]
    assert f.carry_at(f.speed_for(63.0)) == pytest.approx(63.0)


def test_wedges_without_enough_shots_a_speed_range_or_a_fit_are_not_offered():
    base = pitching({"gw 50": (-10.0, 1.3)})
    few = pitching({"sw 54": (-15.0, 1.1)}, shots=10)
    narrow = pitching({"lw 58": (-5.0, 1.0)}); narrow["club_speed_mph"] = 70 + (narrow["club_speed_mph"] - 40) / 45 * 8          # 8 mph range
    loose = pitching({"pw 241": (0.0, 1.5)}, noise=60.0)
    result = ds.wedge_fits(pd.concat([base, few, narrow, loose], ignore_index=True))
    assert [f.wedge for f in result["fits"]] == ["gw 50"]
    reasons = dict(result["unavailable"])
    assert "only 10 shots" in reasons["sw 54"] and "too small a range" in reasons["lw 58"] and "explains only" in reasons["pw 241"]


def test_no_pitching_data_gives_nothing():
    assert ds.wedge_fits(pd.DataFrame()) == {"fits": [], "unavailable": []}
    assert ds.wedge_fits(None) == {"fits": [], "unavailable": []}


def test_the_ladder_is_in_steps_of_ten_metres_inside_the_swung_speeds():
    f = fits()[0]
    ladder = ds.ladder(f)
    distances = [step["distance"] for step in ladder]
    assert distances == sorted(distances) and all(d % 10 == 0 for d in distances) and len(distances) >= 4
    assert all(f.speed_min - 1.5 <= step["speed"] <= f.speed_max + 1.5 for step in ladder)             # no extrapolation (speeds are rounded)
    assert all(step["speed"] == round(step["speed"]) for step in ladder)
    assert all(f.carry_min - 1 <= d <= f.carry_max + 1 for d in distances)


# --- planning a session ---------------------------------------------------------------------------------

def test_a_session_has_the_requested_shots_numbered_from_one():
    plan = ds.plan_session(fits(), 24, np.random.default_rng(1))
    assert [row["n"] for row in plan] == list(range(1, 25))
    assert {row["wedge"] for row in plan} == {"gw 50", "sw 54"}


def test_every_wedge_gets_the_same_number_of_shots_or_one_more():
    plan = ds.plan_session(fits() + [ds.WedgeFit("pw 241", 40, 1.5, 0.0, 0.9, 3.0, 40.0, 85.0, 60.0, 127.0)], 25, np.random.default_rng(3))
    counts = pd.Series([row["wedge"] for row in plan]).value_counts()
    assert counts.sum() == 25 and counts.max() - counts.min() <= 1


def test_targets_come_from_the_ladder_of_the_wedge():
    found = {f.wedge: f for f in fits()}
    for row in ds.plan_session(list(found.values()), 30, np.random.default_rng(4)):
        assert {"distance": row["target_m"], "speed": row["target_mph"]} in ds.ladder(found[row["wedge"]])
        assert row["slope"] == found[row["wedge"]].slope


def test_the_same_wedge_is_not_called_twice_in_a_row_and_targets_are_spread():
    plan = ds.plan_session(fits(), 24, np.random.default_rng(5))
    assert all(a["wedge"] != b["wedge"] for a, b in zip(plan, plan[1:]))
    gw = [row["target_m"] for row in plan if row["wedge"] == "gw 50"]
    assert len(set(gw)) >= min(len(gw), len(ds.ladder(fits()[0])))                                    # the ladder is used up before a target repeats


def test_a_plan_is_random_but_repeatable_with_a_seed():
    a = ds.plan_session(fits(), 20, np.random.default_rng(7))
    b = ds.plan_session(fits(), 20, np.random.default_rng(7))
    c = ds.plan_session(fits(), 20, np.random.default_rng(8))
    assert a == b and a != c


def test_one_wedge_alone_is_called_every_time():
    plan = ds.plan_session(fits()[:1], 10, np.random.default_rng(1))
    assert {row["wedge"] for row in plan} == {"gw 50"} and len(plan) == 10


def test_planning_refuses_what_cannot_work():
    with pytest.raises(ValueError, match="at least one wedge"):
        ds.plan_session([], 10, np.random.default_rng(1))
    with pytest.raises(ValueError, match="at least one shot per wedge"):
        ds.plan_session(fits(), 1, np.random.default_rng(1))


# --- the misses ------------------------------------------------------------------------------------------

def table(speeds, targets=None, *, tolerance=2.0, carries=None, slope=1.2, target_m=60.0):
    targets = targets or [60.0] * len(speeds)
    return pd.DataFrame({"n": range(1, len(speeds) + 1), "wedge": "gw 50", "target_m": target_m, "target_mph": targets, "slope": slope,
                         "tolerance_mph": tolerance, "speed_mph": speeds, "carry_m": carries if carries is not None else [None] * len(speeds)})


def test_the_miss_is_actual_minus_target_and_hits_are_within_the_tolerance():
    e = ds.shot_errors(table([62.0, 57.0, 60.0, 61.9, 58.1]))
    assert list(e["err_mph"]) == pytest.approx([2.0, -3.0, 0.0, 1.9, -1.9])
    assert list(e["hit"]) == [True, False, True, True, True]                                           # exactly 2 mph still counts
    assert list(e["err_m"]) == pytest.approx([2.4, -3.6, 0.0, 2.28, -2.28])


def test_shots_not_yet_entered_are_left_out():
    e = ds.shot_errors(table([62.0, None, 58.0]))
    assert list(e["n"]) == [1, 3]


def test_the_summary_of_a_session():
    s = ds.summarise(ds.shot_errors(table([62.0, 57.0, 60.0, 61.0, 59.0, 63.0])))
    assert s["shots"] == 6 and s["mae_mph"] == pytest.approx(10 / 6) and s["bias_mph"] == pytest.approx(1 / 3)
    assert s["hit_rate"] == pytest.approx(100 * 4 / 6) and s["sd_mph"] > 0 and s["mae_m"] == pytest.approx(10 / 6 * 1.2)
    assert s["mae_lo"] < s["mae_mph"] < s["mae_hi"] and s["hit_lo"] < s["hit_rate"] < s["hit_hi"]
    assert s["carry_mae_m"] is None and s["carry_shots"] == 0


def test_a_small_session_has_no_interval_for_the_average():
    s = ds.summarise(ds.shot_errors(table([62.0, 57.0, 60.0])))
    assert s["mae_lo"] is None and s["hit_lo"] is not None and s["shots"] == 3


def test_the_carry_miss_needs_the_carry_on_most_shots():
    some = ds.summarise(ds.shot_errors(table([60.0] * 6, carries=[58.0, None, None, None, None, None])))
    assert some["carry_shots"] == 1 and some["carry_mae_m"] is None
    most = ds.summarise(ds.shot_errors(table([60.0] * 6, carries=[58.0, 63.0, 61.0, None, None, 60.0])))
    assert most["carry_shots"] == 4 and most["carry_mae_m"] == pytest.approx((2 + 3 + 1 + 0) / 4) and most["carry_bias_m"] == pytest.approx(0.5)


def test_the_summary_of_nothing_is_empty():
    s = ds.summarise(ds.shot_errors(table([None, None])))
    assert s["shots"] == 0 and s["mae_mph"] is None and s["hit_rate"] is None


def test_the_hit_rate_interval_is_wilson():
    lo, hi = ds._wilson(5, 10, 0.95)
    assert lo == pytest.approx(23.7, abs=0.2) and hi == pytest.approx(76.3, abs=0.2)
    assert ds._wilson(0, 0, 0.95) == (None, None)


# --- the files --------------------------------------------------------------------------------------------

PLAN = [{"n": 1, "wedge": "gw 50", "target_m": 60.0, "target_mph": 58.0, "slope": 1.2855}, {"n": 2, "wedge": "sw 54", "target_m": 50.0, "target_mph": 54.0, "slope": 1.0924}]


def test_a_session_file_holds_every_planned_shot_with_empty_results(tmp_path):
    session = store.start_session(tmp_path / "drills", PLAN, 2.0, now=datetime(2026, 10, 17, 18, 30, 5))
    assert session == "drill_2026-10-17_183005" and (tmp_path / "drills" / f"{session}.csv").is_file()        # the folder is created
    frame = store.load_session(tmp_path / "drills", session)
    assert list(frame.columns) == store.COLUMNS and list(frame["wedge"]) == ["gw 50", "sw 54"] and frame["speed_mph"].isna().all()
    assert frame["tolerance_mph"].tolist() == [2.0, 2.0] and frame["started"].iloc[0] == "2026-10-17T18:30:05"


def test_two_sessions_in_the_same_second_get_different_files(tmp_path):
    now = datetime(2026, 10, 17, 18, 30, 5)
    a, b = store.start_session(tmp_path, PLAN, 2.0, now=now), store.start_session(tmp_path, PLAN, 2.0, now=now)
    assert a != b and store.SESSION_ID.match(b)


def test_a_shot_is_written_into_its_row_and_can_be_corrected(tmp_path):
    session = store.start_session(tmp_path, PLAN, 2.0)
    store.record_shot(tmp_path, session, 2, 55.5, 49.0, now=datetime(2026, 10, 17, 18, 31))
    frame = store.load_session(tmp_path, session).set_index("n")
    assert frame.loc[2, "speed_mph"] == 55.5 and frame.loc[2, "carry_m"] == 49.0 and frame.loc[2, "entered"] == "2026-10-17T18:31:00" and pd.isna(frame.loc[1, "speed_mph"])
    store.record_shot(tmp_path, session, 2, 54.0)                                                       # a correction, without the carry
    frame = store.load_session(tmp_path, session).set_index("n")
    assert frame.loc[2, "speed_mph"] == 54.0 and pd.isna(frame.loc[2, "carry_m"])


def test_implausible_entries_and_unknown_shots_are_refused(tmp_path):
    session = store.start_session(tmp_path, PLAN, 2.0)
    with pytest.raises(ValueError, match="not plausible"):
        store.record_shot(tmp_path, session, 1, 5.0)
    with pytest.raises(ValueError, match="not plausible"):
        store.record_shot(tmp_path, session, 1, 60.0, 400.0)
    with pytest.raises(ValueError, match="Shot 9 is not part"):
        store.record_shot(tmp_path, session, 9, 60.0)
    assert store.load_session(tmp_path, session)["speed_mph"].isna().all()                            # nothing was written


def test_a_session_name_cannot_point_elsewhere(tmp_path):
    for bad in ("../secret", "drill_2026-10-17_183005/../x", "notes", "drill_x"):
        with pytest.raises(ValueError, match="Not a drill session"):
            store.load_session(tmp_path, bad)
    with pytest.raises(ValueError, match="No such drill session"):
        store.load_session(tmp_path, "drill_2026-10-17_183005")


def test_no_temporary_file_is_left_behind(tmp_path):
    session = store.start_session(tmp_path, PLAN, 2.0)
    store.record_shot(tmp_path, session, 1, 60.0)
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".csv"]


def test_all_sessions_are_read_and_foreign_files_are_skipped(tmp_path):
    a = store.start_session(tmp_path, PLAN, 2.0, now=datetime(2026, 10, 1, 18, 0, 0))
    b = store.start_session(tmp_path, PLAN, 3.0, now=datetime(2026, 10, 8, 18, 0, 0))
    store.record_shot(tmp_path, b, 1, 57.0)
    (tmp_path / "notes.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "drill_2026-10-09_100000.csv").write_text("not,a,drill\n1,2,3\n", encoding="utf-8")
    everything = store.load_all(tmp_path)
    assert len(everything) == 4 and set(everything["session"]) == {a, b} and everything["speed_mph"].notna().sum() == 1
    assert store.load_all(tmp_path / "missing").empty and store.load_all(None).empty


# --- in the dashboard ------------------------------------------------------------------------------------

def test_the_setup_offers_the_wedges_with_their_ladders(state):
    d = call(state, "/api/drill/setup")
    assert d["enabled"] and d["defaults"] == {"shots": 24, "tolerance_mph": 2.0}
    gw = next(w for w in d["wedges"] if w["wedge"] == "gw 50")
    assert gw["r2"] > 0.6 and gw["slope"] > 0 and len(gw["ladder"]) >= 3 and d["unfinished"] == []
    assert all(step["distance"] % 10 == 0 for step in gw["ladder"])


def test_starting_a_session_writes_the_file_and_returns_the_plan(state):
    d = call(state, "/api/drill/start", method="POST", wedges=["gw 50"], shots=6, tolerance_mph=2.5, seed=1)
    assert d["tolerance_mph"] == 2.5 and len(d["shots"]) == 6 and d["next"] == 1 and all(not s["done"] for s in d["shots"])
    assert {s["wedge"] for s in d["shots"]} == {"gw 50"} and (state.config.drill_dir / f"{d['session']}.csv").is_file()


def test_the_same_seed_gives_the_same_plan(state):
    a = call(state, "/api/drill/start", method="POST", wedges=["gw 50"], shots=8, tolerance_mph=2, seed=5)["shots"]
    b = call(state, "/api/drill/start", method="POST", wedges=["gw 50"], shots=8, tolerance_mph=2, seed=5)["shots"]
    assert [(s["target_m"], s["target_mph"]) for s in a] == [(s["target_m"], s["target_mph"]) for s in b]


def test_bad_starts_are_refused(state):
    for body, message in (({"wedges": ["gw 50"], "shots": 0}, "1 to 200"), ({"wedges": ["gw 50"], "shots": 5, "tolerance_mph": 50}, "tolerance"),
                          ({"wedges": ["putter"], "shots": 5}, "No target distances"), ({"wedges": [], "shots": 5}, "at least one wedge")):
        with pytest.raises(api.ApiError, match=message):
            call(state, "/api/drill/start", method="POST", **body)


def test_entering_a_shot_gives_the_miss_and_the_next_shot(state):
    d = call(state, "/api/drill/start", method="POST", wedges=["gw 50"], shots=4, tolerance_mph=2, seed=2)
    first = d["shots"][0]
    r = call(state, "/api/drill/record", method="POST", session=d["session"], n=1, speed_mph=first["target_mph"] + 3.0)
    assert r["shot"]["err_mph"] == pytest.approx(3.0) and r["shot"]["hit"] is False and r["shot"]["err_m"] == pytest.approx(3.0 * first["slope"])
    assert r["entered"] == 1 and r["shots"] == 4 and r["next"] == 2 and r["summary"]["shots"] == 1 and r["summary"]["hit_rate"] == 0


def test_the_carry_is_optional_and_gives_a_distance_miss(state):
    d = call(state, "/api/drill/start", method="POST", wedges=["gw 50"], shots=3, tolerance_mph=2, seed=2)
    shot = d["shots"][0]
    r = call(state, "/api/drill/record", method="POST", session=d["session"], n=1, speed_mph=shot["target_mph"], carry_m=shot["target_m"] - 4.0)
    assert r["shot"]["hit"] is True and r["shot"]["carry_err_m"] == pytest.approx(-4.0)
    r = call(state, "/api/drill/record", method="POST", session=d["session"], n=2, speed_mph=60.0, carry_m="")
    assert r["shot"]["carry_err_m"] is None


def test_a_finished_session_has_no_next_shot_and_an_unfinished_one_can_be_continued(state):
    d = call(state, "/api/drill/start", method="POST", wedges=["gw 50"], shots=3, tolerance_mph=2, seed=3)
    call(state, "/api/drill/record", method="POST", session=d["session"], n=1, speed_mph=60.0)
    assert call(state, "/api/drill/setup")["unfinished"] == [{"session": d["session"], "started": d["started"], "done": 1, "shots": 3}]
    again = call(state, "/api/drill/session", id=d["session"])
    assert again["next"] == 2 and again["shots"][0]["done"] and again["shots"][0]["speed_mph"] == 60.0
    call(state, "/api/drill/record", method="POST", session=d["session"], n=2, speed_mph=60.0)
    last = call(state, "/api/drill/record", method="POST", session=d["session"], n=3, speed_mph=60.0)
    assert last["next"] is None and last["entered"] == 3 and call(state, "/api/drill/setup")["unfinished"] == []


def test_entries_are_checked(state):
    d = call(state, "/api/drill/start", method="POST", wedges=["gw 50"], shots=3, tolerance_mph=2, seed=3)
    with pytest.raises(api.ApiError, match="not plausible"):
        call(state, "/api/drill/record", method="POST", session=d["session"], n=1, speed_mph=3.0)
    with pytest.raises(api.ApiError, match="Not a drill session"):
        call(state, "/api/drill/record", method="POST", session="../x", n=1, speed_mph=60.0)
    with pytest.raises(api.ApiError):
        call(state, "/api/drill/record", method="POST", session=d["session"], n=1)                       # no speed


def play(state, targets_off, **start):
    """A whole session in which every shot misses its target by the given amounts (cycled)."""
    d = call(state, "/api/drill/start", method="POST", tolerance_mph=2, **start)
    for shot in d["shots"]:
        miss = targets_off[(shot["n"] - 1) % len(targets_off)]
        call(state, "/api/drill/record", method="POST", session=d["session"], n=shot["n"], speed_mph=shot["target_mph"] + miss)
    return d["session"]


def test_progress_follows_the_sessions_in_order(state):
    import time
    play(state, [4.0, -4.0], wedges=["gw 50"], shots=6, seed=1)
    time.sleep(1.1)                                                                                    # session files are named by the second
    play(state, [1.0, -1.0], wedges=["gw 50"], shots=6, seed=2)
    p = call(state, "/api/drill/progress")
    assert [s["mae_mph"] for s in p["sessions"]] == pytest.approx([4.0, 1.0]) and p["wedges"] == ["gw 50"] and p["total_shots"] == 12
    assert [s["hit_rate"] for s in p["sessions"]] == [0, 100] and p["sessions"][0]["started"] < p["sessions"][1]["started"]
    assert p["sessions"][0]["bias_mph"] == pytest.approx(0.0) and p["level"] == 0.95


def test_progress_by_target_and_by_wedge(state):
    play(state, [2.0], wedges=["gw 50"], shots=8, seed=3)
    p = call(state, "/api/drill/progress", wedge="gw 50")
    assert p["wedge"] == "gw 50" and p["targets"] and all(t["wedge"] == "gw 50" and t["mae_mph"] == pytest.approx(2.0) for t in p["targets"])
    assert [t["target_m"] for t in p["targets"]] == sorted(t["target_m"] for t in p["targets"]) and sum(t["shots"] for t in p["targets"]) == 8
    with pytest.raises(api.ApiError, match="No drill shots with the sw 54"):
        call(state, "/api/drill/progress", wedge="sw 54")


def test_sessions_with_hardly_any_shots_are_not_in_the_progress(state):
    d = call(state, "/api/drill/start", method="POST", wedges=["gw 50"], shots=6, tolerance_mph=2, seed=1)
    call(state, "/api/drill/record", method="POST", session=d["session"], n=1, speed_mph=60.0)
    call(state, "/api/drill/record", method="POST", session=d["session"], n=2, speed_mph=60.0)
    assert call(state, "/api/drill/progress")["sessions"] == []


def test_without_any_session_the_progress_is_empty(state):
    assert call(state, "/api/drill/progress") == {"wedges": [], "wedge": "", "sessions": [], "targets": [], "level": 0.95, "total_shots": 0}


def test_the_drill_folder_is_listed_and_can_be_chosen_and_left_empty(state, tmp_path):
    assert call(state, "/api/state")["datasets"]["drill"] == {"folder": str(state.config.drill_dir), "enabled": True, "loaded": False, "sessions": 0, "error": ""}
    chosen = tmp_path / "my drills" / "new"
    info = call(state, "/api/load", method="POST", drill_dir=str(chosen))["datasets"]["drill"]
    assert chosen.is_dir() and info["enabled"] and info["loaded"] and info["folder"] == str(chosen)
    play(state, [1.0], wedges=["gw 50"], shots=4, seed=1)
    assert any(chosen.glob("drill_*.csv")) and call(state, "/api/state")["datasets"]["drill"]["sessions"] == 1
    off = call(state, "/api/load", method="POST", drill_dir="")["datasets"]["drill"]
    assert off == {"folder": "", "enabled": False, "loaded": False, "sessions": 0, "error": ""}
    with pytest.raises(api.ApiError, match="No folder for the drill sessions"):
        call(state, "/api/drill/start", method="POST", wedges=["gw 50"], shots=4)
    assert call(state, "/api/drill/setup")["enabled"] is False


def test_only_swings_of_ten_oclock_and_above_set_the_targets(state):
    shots = state.included("pitching")
    gw = shots[shots["club"] == "gw"]
    assert set(gw["intent"]) == {9, 10, 11, 12}
    setup = next(w for w in call(state, "/api/drill/setup")["wedges"] if w["wedge"] == "gw 50")
    assert setup["n"] == int((gw["intent"] >= 10).sum()) < len(gw)
    assert setup["speed_range"][0] > gw[gw["intent"] == 9]["club_speed_mph"].mean()                       # the slow 9 o'clock swings are not in the range
    assert min(step["speed"] for step in setup["ladder"]) > gw[gw["intent"] == 9]["club_speed_mph"].mean() - 1


def test_the_nine_oclock_swings_do_not_change_the_targets_at_all(state):
    before = call(state, "/api/drill/setup")["wedges"]
    shots = state.shots["pitching"].copy()
    nine = shots["intent"] == 9
    shots.loc[nine, "carry_m"] = shots.loc[nine, "carry_m"] * 3 + 50                                      # nonsense carries for the 9 o'clock swings
    shots.loc[nine, "club_speed_mph"] = shots.loc[nine, "club_speed_mph"] * 0.5
    state.shots["pitching"] = shots
    assert call(state, "/api/drill/setup")["wedges"] == before
