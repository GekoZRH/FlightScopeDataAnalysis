import json
import re
import threading
import urllib.error
import urllib.request
from datetime import date, timedelta

import numpy as np
import pytest

from golf.config import DEFAULT_CONFIG, load_config
from golf.dashboard import api, service
from golf.dashboard.server import create_server
from golf.dashboard.service import AppState

HEADER = "Index,Player,Time,Carry [m],Roll [m],Lateral [m],Club Speed [mph],Club,Shot Type"


def write_session(folder, day, rows):
    lines = [HEADER]
    for i, (club, carry, lateral, speed) in enumerate(rows, start=1):
        lateral_text = f"{abs(lateral):.1f} {'R' if lateral >= 0 else 'L'}"
        lines.append(f"{i},Me,{day:%Y-%m-%d}; 10-{i // 60:02d}-{i % 60:02d},{carry:.1f},1.0,{lateral_text},{speed:.1f},{club},Straight")
    (folder / f"Lesson - {day:%d%m%Y} 100000_windows-1252.csv").write_text("\n".join(lines) + "\n", encoding="windows-1252")


@pytest.fixture
def state(tmp_path):
    rng = np.random.default_rng(3)
    swing, pitching = tmp_path / "swing", tmp_path / "pitching"
    swing.mkdir(), pitching.mkdir()
    start = date(2026, 3, 1)
    for k in range(6):
        day = start + timedelta(days=7 * k)
        rows = [("Driver Ping", 210 + rng.normal(0, 8), rng.normal(5, 6), 100 + rng.normal(0, 2)) for _ in range(12)]
        rows += [("7 Iron 245", 160 + rng.normal(0, 5 - 0.5 * k), rng.normal(-2, 4), 85 + rng.normal(0, 2)) for _ in range(10)]
        rows += [("Gap Wedge", 90 + rng.normal(0, 4), rng.normal(0, 3), 78 + rng.normal(0, 2)) for _ in range(4)]
        write_session(swing, day, rows)
        wedge = []
        for label, base_carry, base_speed in (("GW 50", 92, 78), ("GW 50_11", 82, 73), ("GW 50_10", 68, 63), ("GW 50_9", 50, 52)):
            wedge += [(label, base_carry + rng.normal(0, 4), rng.normal(-1, 2), base_speed + rng.normal(0, 3 - 0.2 * k)) for _ in range(8)]
        write_session(pitching, day, wedge)

    text = DEFAULT_CONFIG.read_text(encoding="utf-8")
    text = re.sub(r'swing_dir = ".*"', 'swing_dir = "swing"', text)
    text = re.sub(r'pitching_dir = ".*"', 'pitching_dir = "pitching"', text)
    text = re.sub(r'output_dir = ".*"', 'output_dir = "out"', text)
    config_path = tmp_path / "golf.toml"
    config_path.write_text(text, encoding="utf-8")
    return AppState(config_path)


def call(state, path, method="GET", **params):
    body = params if method == "POST" else {}
    query = {} if method == "POST" else {k: str(v) for k, v in params.items()}
    return api.handle(state, method, path, query, body)


# --- data ----------------------------------------------------------------------------

def test_dataset_info_counts_files_and_shots(state):
    info = call(state, "/api/state")["datasets"]
    assert info["swing"]["loaded"] and info["swing"]["files"] == 6 and info["swing"]["shots"] == 156
    assert info["pitching"]["shots"] == 6 * 32 and info["swing"]["unreadable"] == []


def test_a_missing_folder_is_reported_not_raised(tmp_path):
    text = DEFAULT_CONFIG.read_text(encoding="utf-8")
    text = re.sub(r'swing_dir = ".*"', 'swing_dir = "nowhere"', text)
    (tmp_path / "golf.toml").write_text(text, encoding="utf-8")
    broken = AppState(tmp_path / "golf.toml")
    assert not call(broken, "/api/state")["datasets"]["swing"]["loaded"]
    assert call(broken, "/api/swing/review", session="2026-03-01")["rows"] == []
    with pytest.raises(api.ApiError):
        call(broken, "/api/swing/dispersion", label="7i 245", session="2026-03-01")


def test_choosing_folders_is_validated_and_remembered(state, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(api.ApiError, match="No CSV files"):
        call(state, "/api/load", method="POST", swing_dir=str(other))
    with pytest.raises(api.ApiError, match="not a folder"):
        call(state, "/api/load", method="POST", swing_dir=str(tmp_path / "missing"))
    (other / "x.csv").write_text(HEADER + "\n1,Me,2026-04-01; 10-00-01,100,1,1.0 R,80,7 Iron 245,Fade\n", encoding="windows-1252")
    info = call(state, "/api/load", method="POST", swing_dir=str(other))["datasets"]
    assert info["swing"]["shots"] == 1
    assert json.loads(state.config.local_path.read_text())["swing_dir"] == str(other)


# --- full swing -------------------------------------------------------------------------

def test_swing_review_compares_with_earlier_sessions(state):
    overview = call(state, "/api/swing/overview")
    assert overview["sessions"][0] == "2026-04-05" and overview["labels"][0] == "driver ping"
    review = call(state, "/api/swing/review", session="2026-04-05")
    rows = {r["label"]: r for r in review["rows"]}
    assert set(rows) == {"driver ping", "7i 245", "gw 50"}      # 'Gap Wedge' is aliased to gw 50
    driver = rows["driver ping"]
    assert driver["n"] == 12 and driver["n_before"] == 48       # the 4 sessions before
    assert driver["measures"]["carry"]["d_mean"]["lo"] < driver["measures"]["carry"]["d_mean"]["hi"]
    assert rows["gw 50"]["verdict"] is None                       # only 4 shots in the session
    all_before = call(state, "/api/swing/review", session="2026-04-05", baseline="all")
    assert {r["label"]: r for r in all_before["rows"]}["driver ping"]["n_before"] == 60


def test_first_session_has_nothing_to_compare_with(state):
    row = call(state, "/api/swing/review", session="2026-03-01")["rows"][0]
    assert row["n_before"] == 0 and row["verdict"] is None


def test_progress_has_one_point_per_session(state):
    sessions = call(state, "/api/swing/progress", label="7i 245")["sessions"]
    assert [s["date"] for s in sessions][0] == "2026-03-01" and len(sessions) == 6
    assert all(s["carry_sd_lo"] < s["carry_sd"] < s["carry_sd_hi"] for s in sessions)


@pytest.mark.parametrize("compare", ["last4", "all", "window"])
def test_dispersion_returns_points_rings_and_a_verdict(state, compare):
    d = call(state, "/api/swing/dispersion", label="driver ping", session="2026-04-05", compare=compare)
    assert len(d["now"]["carry"]) == 12 and len(d["before"]["carry"]) > 12
    assert len(d["rings"]["now"]["68"]) > 20 and len(d["rings"]["before"]["95"]) > 20
    assert d["verdict"]["carry"] in (-1, 0, 1)
    assert d["sessions"] and all(len(s["ring"]) > 10 for s in d["sessions"])


def test_the_95_ring_is_larger_than_the_68_ring(state):
    ring = call(state, "/api/swing/dispersion", label="driver ping", session="2026-04-05")["rings"]["now"]
    width = lambda points: max(p[0] for p in points) - min(p[0] for p in points)
    assert width(ring["95"]) > width(ring["68"])


# --- bag and wedge selection -------------------------------------------------------------

def test_bag_choice_is_saved_and_used(state):
    bag = call(state, "/api/bag")
    assert [c["club"] for c in bag["clubs"]] == ["driver ping", "7i 245", "gw 50"]
    assert all(c["selected"] for c in bag["clubs"])
    saved = call(state, "/api/bag", method="POST", clubs=["7i 245", "driver ping"])
    assert [c["club"] for c in saved["clubs"] if c["selected"]] == ["driver ping", "7i 245"]   # standard order
    assert call(state, "/api/swing/overview")["labels"] == ["driver ping", "7i 245"]
    assert load_config(state.config_path).bag["swing"].clubs == ("driver ping", "7i 245")


def test_bag_choice_is_checked(state):
    with pytest.raises(api.ApiError, match="Not found"):
        call(state, "/api/bag", method="POST", clubs=["driver ping", "putter"])
    with pytest.raises(api.ApiError, match="at least one"):
        call(state, "/api/bag", method="POST", clubs=[])


def test_wedge_grid_and_selection(state):
    grid = call(state, "/api/wedges")["rows"]
    assert grid[0]["club"] == "gw 50" and grid[0]["counts"] == {"12": 48, "11": 48, "10": 48, "9": 48}
    call(state, "/api/wedges", method="POST", pairs=[["gw 50", 12], ["gw 50", 10]])
    assert call(state, "/api/wedges")["rows"][0]["selected"] == [12, 10]
    labels = call(state, "/api/pitching/overview")["labels"]
    assert labels == ["gw 50", "gw 50_10"]
    with pytest.raises(api.ApiError, match="No shots recorded"):
        call(state, "/api/wedges", method="POST", pairs=[["lw 58", 12]])


# --- pitching ------------------------------------------------------------------------------

def test_pitching_review_has_speed_carry_and_lateral(state):
    review = call(state, "/api/pitching/review", session="2026-04-05")
    row = {r["label"]: r for r in review["rows"]}["gw 50_10"]
    assert set(row["measures"]) == {"speed", "carry", "lateral"}
    assert row["measures"]["speed"]["mean"] == pytest.approx(63, abs=4)
    assert row["verdict"] in (-1, 0, 1)                           # 8 shots against 32 before


def test_accuracy_over_time_has_a_series_per_intent(state):
    d = call(state, "/api/pitching/accuracy", club="gw 50", measure="speed_sd")
    assert [s["name"] for s in d["series"]] == ["full", "11", "10", "9"]
    assert len(d["sessions"]) == 6 and all(len(s["y"]) == 6 for s in d["series"])
    assert call(state, "/api/pitching/accuracy", club="gw 50", measure="lateral_sd")["title"].startswith("Lateral")


def test_straightness_and_ladder(state):
    rows = call(state, "/api/pitching/straightness")["rows"]
    assert len(rows) == 4 and all(r["lo95"] < r["lo68"] < r["mean"] < r["hi68"] < r["hi95"] for r in rows)
    ladder = call(state, "/api/pitching/ladder", target=82, tolerance=3)["rows"]
    assert ladder[0]["label"] == "gw 50_11" and ladder[0]["chance"] > ladder[-1]["chance"]


# --- cards ------------------------------------------------------------------------------------

def test_cards_are_written_to_a_folder_per_data_set(state):
    from pathlib import Path

    swing = call(state, "/api/card", method="POST", mode="swing")
    pitching = call(state, "/api/card", method="POST", mode="pitching")
    assert swing["rows"] == 3 and pitching["rows"] == 4 and swing["as_of"] == "2026-04-05"
    assert Path(swing["file"]).parent == state.config.cards_dir("swing")
    assert Path(pitching["file"]).parent == state.config.cards_dir("pitching")
    assert state.config.cards_dir("swing") != state.config.cards_dir("pitching")
    assert swing["url"].startswith("/files/cards/") and pitching["url"].endswith("wedge_distance_card.png")
    folder = state.config.cards_dir("swing")
    assert (folder / "swing_distance_card.png").stat().st_size > 10_000
    assert (folder / "archive" / "2026-04-05_swing_distance_card.png").exists()


def test_a_generated_card_can_be_fetched_through_the_server(state):
    from golf.dashboard.server import create_server, make_handler

    result = call(state, "/api/card", method="POST", mode="swing")
    httpd = create_server(state, port=0)
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = make_handler(state, port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        status, body = fetch(port, result["url"])
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert status == 200 and body[1:4] == b"PNG"


def test_card_follows_the_bag_choice(state):
    call(state, "/api/bag", method="POST", clubs=["driver ping"])
    assert call(state, "/api/card", method="POST", mode="swing")["rows"] == 1


# --- web server ----------------------------------------------------------------------------------

@pytest.fixture
def server(state):
    httpd = create_server(state, port=0)
    port = httpd.server_address[1]
    # the handler was built for the requested port 0; rebuild it for the real one
    from golf.dashboard.server import make_handler
    httpd.RequestHandlerClass = make_handler(state, port)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield port
    httpd.shutdown()
    httpd.server_close()


def fetch(port, path, method="GET", data=None, headers=None):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_server_serves_page_script_and_data(server):
    status, page = fetch(server, "/")
    assert status == 200 and b"Golf practice dashboard" in page
    assert fetch(server, "/app.js")[0] == 200 and fetch(server, "/app.css")[0] == 200
    status, js = fetch(server, "/plotly.js")
    assert status == 200 and len(js) > 1_000_000
    status, body = fetch(server, "/api/swing/overview")
    assert status == 200 and json.loads(body)["labels"][0] == "driver ping"


def test_server_rejects_foreign_hosts_and_posts_without_the_header(server):
    assert fetch(server, "/api/state", headers={"Host": "evil.example"})[0] == 403
    assert fetch(server, "/api/bag", method="POST", data=b'{"clubs": ["driver ping"]}')[0] == 403
    status, _ = fetch(server, "/api/bag", method="POST", data=b'{"clubs": ["driver ping"]}', headers={"X-Golf": "1"})
    assert status == 200


def test_server_reports_user_errors_as_400_and_hides_other_files(server):
    status, body = fetch(server, "/api/bag", method="POST", data=b'{"clubs": []}', headers={"X-Golf": "1"})
    assert status == 400 and "at least one" in json.loads(body)["error"]
    assert fetch(server, "/api/nothing")[0] == 404
    assert fetch(server, "/files/../golf.toml")[0] == 404
    assert fetch(server, "/files/cards/missing.png")[0] == 404
    assert fetch(server, "/..%2fgolf.toml")[0] == 404


# --- sessions ------------------------------------------------------------------------------------

def session_dates(state, mode="swing"):
    return [s["date"] for s in call(state, "/api/sessions", mode=mode)["sessions"]]


def test_sessions_are_listed_newest_first_and_all_take_part(state):
    listing = call(state, "/api/sessions", mode="swing")
    assert [s["date"] for s in listing["sessions"]][:2] == ["2026-04-05", "2026-03-29"]
    assert all(s["selected"] for s in listing["sessions"]) and listing["sessions"][0]["shots"] == 26
    assert listing["window_weeks"] == 4 and listing["fallback_weeks"] == 12


def test_only_the_selected_sessions_are_analysed(state):
    chosen = session_dates(state)[:3]                       # the three newest
    listing = call(state, "/api/sessions", method="POST", mode="swing", selected=chosen)
    assert [s["date"] for s in listing["sessions"] if s["selected"]] == chosen

    assert call(state, "/api/swing/overview")["sessions"] == chosen
    assert [s["date"] for s in call(state, "/api/swing/progress", label="driver ping")["sessions"]] == chosen[::-1]
    newest = {r["label"]: r for r in call(state, "/api/swing/review", session=chosen[0], baseline="all")["rows"]}
    assert newest["driver ping"]["n_before"] == 24           # two earlier sessions of 12 shots, not five
    card = call(state, "/api/card", method="POST", mode="swing")
    assert card["sessions"] == 3 and card["from"] == chosen[-1] and card["as_of"] == chosen[0]


def test_the_card_uses_every_shot_of_the_selected_sessions(state):
    from golf.report.build import generate_card

    chosen = session_dates(state)[:2]
    call(state, "/api/sessions", method="POST", mode="swing", selected=chosen)
    _, card = generate_card("swing", state.included("swing"), state.config)
    assert dict(zip(card["label"], card["n"])) == {"driver ping": 24, "7i 245": 20, "gw 50": 8}
    assert dict(zip(card["label"], card["status"])) == {"driver ping": "ok", "7i 245": "ok", "gw 50": "short"}


def test_swing_and_pitching_selections_are_independent(state):
    call(state, "/api/sessions", method="POST", mode="swing", selected=session_dates(state)[:1])
    assert len(call(state, "/api/pitching/overview")["sessions"]) == 6
    assert len(call(state, "/api/pitching/accuracy", club="gw 50", measure="speed_sd")["sessions"]) == 6
    call(state, "/api/sessions", method="POST", mode="pitching", selected=session_dates(state, "pitching")[:2])
    assert len(call(state, "/api/pitching/overview")["sessions"]) == 2
    assert len(call(state, "/api/pitching/accuracy", club="gw 50", measure="speed_sd")["sessions"]) == 2
    assert len(call(state, "/api/swing/overview")["sessions"]) == 1
    info = call(state, "/api/state")["datasets"]
    assert info["swing"]["sessions_selected"] == 1 and info["pitching"]["sessions_selected"] == 2


def test_sessions_added_later_take_part_and_other_folders_start_complete(state, tmp_path):
    call(state, "/api/sessions", method="POST", mode="swing", selected=session_dates(state)[:3])
    write_session(tmp_path / "swing", date(2026, 5, 1), [("Driver Ping", 210.0 + i, 1.0, 100.0) for i in range(12)])
    call(state, "/api/load", method="POST", swing_dir=str(tmp_path / "swing"))
    listing = call(state, "/api/sessions", mode="swing")["sessions"]
    assert listing[0]["date"] == "2026-05-01" and listing[0]["selected"]
    assert sum(s["selected"] for s in listing) == 4

    other = tmp_path / "other"
    other.mkdir()
    write_session(other, date(2026, 6, 1), [("Driver Ping", 200.0 + i, 1.0, 100.0) for i in range(6)])
    call(state, "/api/load", method="POST", swing_dir=str(other))
    assert [s["selected"] for s in call(state, "/api/sessions", mode="swing")["sessions"]] == [True]


def test_the_session_selection_is_checked(state):
    with pytest.raises(api.ApiError, match="at least one"):
        call(state, "/api/sessions", method="POST", mode="swing", selected=[])
    with pytest.raises(api.ApiError, match="Not a session"):
        call(state, "/api/sessions", method="POST", mode="swing", selected=["1999-01-01"])
    assert call(state, "/api/sessions", mode="swing")["sessions"][0]["selected"]


def test_the_command_line_card_uses_the_saved_selection(state, tmp_path):
    from golf.cli import build_cards

    chosen = session_dates(state)[:2]
    call(state, "/api/sessions", method="POST", mode="swing", selected=chosen)
    build_cards(config_path=state.config_path)
    import matplotlib.image as image
    assert image.imread(state.config.cards_dir("swing") / "swing_distance_card.png").shape[0] == 4050
    assert (state.config.cards_dir("swing") / "archive" / f"{chosen[0]}_swing_distance_card.png").exists()
