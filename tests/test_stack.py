import json
import re
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from golf import cli
from golf.config import DEFAULT_CONFIG, load_config, update_local_settings
from golf.dashboard import api
from golf.dashboard.service import AppState
from golf.data import load_shots, load_stack, read_stack_file, unreadable_weights
from golf.data.stack import parse_weight, stack_files

from test_dashboard import write_session

HEADER = "Index,Player,Time,V-Plane [deg],H-Plane [deg],Club Speed [mph],Club"


def write_stack(path, day, sets, start="19-00-00", missing_plane_at=None):
    """sets: list of (weight text, [speeds]). Swings are 27 s apart, a set rest is 3.5 minutes."""
    clock = datetime.strptime(f"{day:%Y-%m-%d} {start}", "%Y-%m-%d %H-%M-%S")
    lines, n = [HEADER], 0
    for weight, speeds in sets:
        for speed in speeds:
            n += 1
            v_plane, h_plane = ("", "") if n == missing_plane_at else ("61.0", "2.5 R")
            lines.append(f"{n},Me,{clock:%Y-%m-%d; %H-%M-%S},{v_plane},{h_plane},{speed:.1f},{weight}")
            clock += timedelta(seconds=27)
        clock += timedelta(minutes=3.5)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(chr(10).join(lines) + chr(10), encoding="windows-1252")


@pytest.fixture
def world(tmp_path):
    """Swing, pitching and stack data, each in its own folder, and a configuration pointing at them."""
    rng = np.random.default_rng(8)
    swing, pitching, stack = tmp_path / "swing", tmp_path / "pitching", tmp_path / "stack"
    swing.mkdir(), pitching.mkdir()
    start = date(2026, 3, 1)
    for k in range(4):
        day = start + timedelta(days=7 * k)
        write_session(swing, day, [("Driver Ping", 210 + rng.normal(0, 6), rng.normal(0, 5), 100.0) for _ in range(10)])
        write_session(pitching, day, [(label, base + rng.normal(0, 3), rng.normal(0, 2), s) for label, base, s in
                                      (("GW 50", 92, 78.0), ("GW 50_9", 50, 52.0)) for _ in range(6)])
    # stack: one folder per session (as the training app saves them), and one session directly in the folder
    for k in range(4):
        day = date(2026, 9, 14) + timedelta(days=7 * k)
        sets = [("235g", list(90 + k + rng.normal(0, 0.8, 8))), ("160g", list(98 + k + rng.normal(0, 0.8, 8))),
                ("195g", list(94 + 0.5 * k + rng.normal(0, 0.8, 4)))]
        name = f"Stack - {day:%d%m%Y} 170000"
        target = stack / name / f"{name}_windows-1252.csv" if k < 3 else stack / f"{name}_windows-1252.csv"
        write_stack(target, day, sets, missing_plane_at=3 if k == 0 else None)
        if k < 3:
            (stack / name / "Clipboard01.png").write_bytes(b"not a csv")

    text = DEFAULT_CONFIG.read_text(encoding="utf-8")
    for key, value in (("swing_dir", "swing"), ("pitching_dir", "pitching"), ("stack_dir", "stack"), ("garmin_dir", ""), ("withings_dir", ""), ("output_dir", "out")):
        text = re.sub(rf'{key} = ".*"', f'{key} = "{value}"', text)
    (tmp_path / "golf.toml").write_text(text, encoding="utf-8")
    return tmp_path / "golf.toml"


def call(state, path, method="GET", **params):
    body = params if method == "POST" else {}
    query = {} if method == "POST" else {k: str(v) for k, v in params.items()}
    return api.handle(state, method, path, query, body)


# --- reading stack files --------------------------------------------------------------------

@pytest.mark.parametrize("text, grams", [("235g", 235.0), (" 80 G ", 80.0), ("95g", 95.0), ("62,5g", 62.5)])
def test_weight_is_read_from_the_club_column(text, grams):
    assert parse_weight(text) == grams


@pytest.mark.parametrize("text", ["", "warmup", "195", "g", None, float("nan")])
def test_other_club_values_are_not_a_weight(text):
    assert np.isnan(parse_weight(text))


def test_a_stack_file_has_weight_speed_and_signed_planes(tmp_path):
    path = tmp_path / "s.csv"
    write_stack(path, date(2026, 10, 3), [("235g", [90.4, 91.1]), ("95g", [104.0])], missing_plane_at=2)
    shots = read_stack_file(path)
    assert shots["weight_g"].tolist() == [235.0, 235.0, 95.0]
    assert shots["club_speed_mph"].tolist() == [90.4, 91.1, 104.0]
    assert shots["h_plane_deg"].iloc[0] == 2.5 and np.isnan(shots["h_plane_deg"].iloc[1])
    assert shots["label"].tolist() == ["235 g", "235 g", "95 g"] and str(shots["session_date"].iloc[0]) == "2026-10-03"
    assert shots["timestamp"].is_monotonic_increasing and set(shots["mode"]) == {"stack"}


def test_rows_without_a_readable_weight_are_kept_and_reported(tmp_path):
    path = tmp_path / "s.csv"
    write_stack(path, date(2026, 10, 3), [("235g", [90.0]), ("warmup", [60.0, 61.0])])
    shots = read_stack_file(path)
    assert len(shots) == 3
    report = unreadable_weights(shots)
    assert report["raw_club"].tolist() == ["warmup"] and report["shots"].tolist() == [2]


def test_a_file_without_the_needed_columns_is_refused(tmp_path):
    (tmp_path / "bad.csv").write_text("Index,Time\n1,2026-10-03; 19-00-00\n", encoding="windows-1252")
    with pytest.raises(ValueError, match="missing required column"):
        read_stack_file(tmp_path / "bad.csv")


def test_files_are_found_in_the_folder_and_one_level_below(world):
    folder = world.parent / "stack"
    names = [p.name for p in stack_files(folder)]
    assert len(names) == 4 and all(n.endswith(".csv") for n in names)
    deeper = folder / "Stack - old" / "deeper"
    deeper.mkdir(parents=True)
    write_stack(deeper / "x.csv", date(2025, 1, 1), [("100g", [80.0])])
    assert len(stack_files(folder)) == 4                      # two levels down is not read


def test_load_stack_reads_all_sessions_in_time_order(world):
    shots = load_stack(world.parent / "stack")
    assert len(shots) == 4 * 20 and shots["timestamp"].is_monotonic_increasing
    assert shots["session_date"].nunique() == 4 and set(shots["weight_g"]) == {235.0, 160.0, 195.0}


def test_load_shots_dispatches_stack_and_rejects_a_missing_folder(world, tmp_path):
    assert len(load_shots("stack", load_config(world))) == 80
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError, match="No CSV files"):
        load_shots("stack", load_config(world), directory=tmp_path / "empty")
    config = load_config(world, local_path=tmp_path / "local.json")
    update_local_settings(config, {"stack_dir": ""})
    with pytest.raises(FileNotFoundError, match="No folder is chosen"):
        load_shots("stack", load_config(world, local_path=tmp_path / "local.json"))


# --- optional folders in the configuration ---------------------------------------------------

def test_stack_folder_is_part_of_the_configuration(world):
    config = load_config(world)
    assert config.stack_dir == world.parent / "stack" and config.data_dir("stack") == config.stack_dir
    assert set(config.excluded_sessions) == {"swing", "pitching", "stack"}


def test_an_empty_folder_means_no_data_of_that_kind(world, tmp_path):
    local = tmp_path / "golf.local.json"
    local.write_text(json.dumps({"swing_dir": "", "stack_dir": "  "}), encoding="utf-8")
    config = load_config(world)
    assert config.swing_dir is None and config.stack_dir is None and config.pitching_dir is not None
    with pytest.raises(ValueError, match="No swing data folder"):
        config.cards_dir("swing")


def test_an_empty_folder_in_golf_toml_also_means_no_data(world):
    text = re.sub(r'stack_dir = ".*"', 'stack_dir = ""', world.read_text(encoding="utf-8"))
    world.write_text(text, encoding="utf-8")
    assert load_config(world).stack_dir is None


# --- the dashboard with stack data ----------------------------------------------------------

def test_the_dashboard_loads_all_three_kinds(world):
    info = call(AppState(world), "/api/state")["datasets"]
    assert [info[m]["loaded"] for m in ("swing", "pitching", "stack")] == [True, True, True]
    assert info["stack"]["files"] == 4 and info["stack"]["shots"] == 80 and info["stack"]["sessions"] == 4
    assert info["stack"]["unreadable"] == [] and info["stack"]["not_in_bag"] == []


def test_stack_progress_has_one_line_per_weight(world):
    state = AppState(world)
    overview = call(state, "/api/stack/overview")
    assert overview["weights"] == [235.0, 195.0, 160.0] and len(overview["sessions"]) == 4
    progress = call(state, "/api/stack/progress")
    assert progress["dates"] == sorted(progress["dates"]) and len(progress["dates"]) == 4
    assert [s["name"] for s in progress["series"]] == ["235 g", "195 g", "160 g"]          # heaviest first
    heavy, light = progress["series"][0], progress["series"][2]
    assert all(v is not None for v in heavy["y"]) and heavy["n"] == [8, 8, 8, 8]
    assert heavy["y"][3] > heavy["y"][0] and 87 < heavy["y"][0] < 94 and 96 < light["y"][0] < 102   # faster over time, lighter is faster
    assert all(lo < y < hi for y, lo, hi in zip(heavy["y"], heavy["lo"], heavy["hi"]))


def test_a_weight_used_in_some_sessions_only_has_gaps(world, tmp_path):
    write_stack(world.parent / "stack" / "extra.csv", date(2026, 10, 20), [("255g", [86.0, 87.0, 88.0, 87.5])])
    state = AppState(world)
    progress = call(state, "/api/stack/progress")
    assert len(progress["dates"]) == 5
    top = progress["series"][0]
    assert top["name"] == "255 g" and top["y"][:4] == [None] * 4 and top["y"][4] == pytest.approx(87.125)


def test_stack_sessions_can_be_selected_like_the_others(world):
    state = AppState(world)
    sessions = call(state, "/api/sessions", mode="stack")["sessions"]
    assert len(sessions) == 4 and sessions[0]["shots"] == 20 and sessions[0]["clubs"] == 3
    chosen = [s["date"] for s in sessions][:2]
    call(state, "/api/sessions", method="POST", mode="stack", selected=chosen)
    assert call(state, "/api/stack/overview")["sessions"] == chosen
    assert call(state, "/api/stack/progress")["dates"] == chosen[::-1]
    assert len(call(state, "/api/sessions", mode="swing")["sessions"]) == 4          # the other kinds are untouched
    assert call(state, "/api/state")["datasets"]["stack"]["sessions_selected"] == 2


def test_stack_swings_with_an_unreadable_weight_are_left_out_of_the_lines(world):
    write_stack(world.parent / "stack" / "extra.csv", date(2026, 10, 20), [("235g", [90.0] * 8), ("warmup", [60.0, 61.0])])
    state = AppState(world)
    info = call(state, "/api/state")["datasets"]["stack"]
    assert [u["raw_club"] for u in info["unreadable"]] == ["warmup"]
    assert [s["name"] for s in call(state, "/api/stack/progress")["series"]] == ["235 g", "195 g", "160 g"]


# --- leaving a folder empty ---------------------------------------------------------------------

def test_leaving_a_folder_empty_turns_that_kind_off_and_keeps_the_others(world):
    state = AppState(world)
    info = call(state, "/api/load", method="POST", swing_dir="")["datasets"]
    assert info["swing"] == {"folder": "", "enabled": False, "loaded": False, "error": ""}
    assert info["pitching"]["loaded"] and info["stack"]["loaded"]                       # untouched
    assert json.loads(state.config.local_path.read_text())["swing_dir"] == ""
    assert call(AppState(world), "/api/state")["datasets"]["swing"]["enabled"] is False  # remembered after a restart


def test_a_kind_without_a_folder_gives_empty_answers_not_errors(world):
    state = AppState(world)
    call(state, "/api/load", method="POST", swing_dir="", pitching_dir="", stack_dir="")
    info = call(state, "/api/state")["datasets"]
    assert not any(info[m]["enabled"] or info[m]["loaded"] for m in info)
    assert call(state, "/api/swing/overview")["sessions"] == [] and call(state, "/api/pitching/overview")["sessions"] == []
    assert call(state, "/api/stack/overview") == {"loaded": False, "sessions": [], "weights": []}
    assert call(state, "/api/stack/progress") == {"dates": [], "series": []}
    assert call(state, "/api/swing/review", session="2026-03-01")["rows"] == []
    assert call(state, "/api/sessions", mode="stack") == {"loaded": False, "sessions": []}
    assert call(state, "/api/bag")["loaded"] is False and call(state, "/api/wedges")["loaded"] is False
    with pytest.raises(api.ApiError):
        call(state, "/api/card", method="POST", mode="swing")


def test_a_folder_can_be_filled_in_again(world):
    state = AppState(world)
    call(state, "/api/load", method="POST", stack_dir="")
    assert call(state, "/api/state")["datasets"]["stack"]["enabled"] is False
    info = call(state, "/api/load", method="POST", stack_dir=str(world.parent / "stack"))["datasets"]
    assert info["stack"]["loaded"] and info["stack"]["shots"] == 80


def test_a_load_that_names_only_some_folders_keeps_the_rest(world):
    state = AppState(world)
    info = call(state, "/api/load", method="POST", stack_dir="")["datasets"]
    assert info["swing"]["loaded"] and info["pitching"]["loaded"] and not info["stack"]["enabled"]


def test_stack_folders_are_checked(world, tmp_path):
    state = AppState(world)
    with pytest.raises(api.ApiError, match="not a folder"):
        call(state, "/api/load", method="POST", stack_dir=str(tmp_path / "nowhere"))
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(api.ApiError, match="No CSV files"):
        call(state, "/api/load", method="POST", stack_dir=str(empty))
    nested = tmp_path / "nested"
    write_stack(nested / "Stack - a" / "a.csv", date(2026, 11, 1), [("200g", [88.0, 89.0])])
    info = call(state, "/api/load", method="POST", stack_dir=str(nested))["datasets"]
    assert info["stack"]["loaded"] and info["stack"]["shots"] == 2


def test_a_folder_that_does_not_exist_is_an_error_not_a_disabled_kind(world):
    text = re.sub(r'stack_dir = ".*"', 'stack_dir = "missing"', world.read_text(encoding="utf-8"))
    world.write_text(text, encoding="utf-8")
    info = call(AppState(world), "/api/state")["datasets"]["stack"]
    assert info["enabled"] is True and info["loaded"] is False and "No CSV files" in info["error"]


def test_cards_skip_a_kind_without_a_folder(world, capsys):
    state = AppState(world)
    call(state, "/api/load", method="POST", swing_dir="")
    written = cli.build_cards(config_path=world)
    out = capsys.readouterr().out
    assert "[swing] skipped" in out and len(written) == 2 and all("wedge_distance_card" in p.name for p in written)
