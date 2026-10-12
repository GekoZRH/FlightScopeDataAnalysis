from datetime import timedelta

import numpy as np
import pytest

from golf.dashboard import api, service
from golf.dashboard.service import AppState
from golf.data import competition as competition_module
from golf.data.competition import RECORD_NAME

from test_correlations import DAYS, build_world, call
import test_competition as tc


def sleepy_rounds(tmp_path, **extra):
    """More sleep the night before means fewer strokes. Strokes and sleep both vary from round to round."""
    rng = np.random.default_rng(4)
    sleep = list(rng.permutation(np.linspace(5.8, 9.2, len(DAYS))))
    strokes = lambda k: round(84 - 3 * (sleep[k] - 7.5))              # 79 to 89: never more than bogey golf
    config = build_world(tmp_path, sleep_hours=sleep, speed_for=lambda k: 90.0, golf_strokes=strokes, **extra)
    return AppState(config), sleep, strokes


@pytest.fixture
def world(tmp_path):
    comp = [(DAYS[k], 80 + k, 8.0 + k * 0.5) for k in range(0, 14, 2)]                 # 7 rounds, on the same days as 7 Garmin rounds
    return sleepy_rounds(tmp_path, competition=comp)[0]


# --- what is loaded -------------------------------------------------------------------------------------

def test_both_kinds_of_round_are_described(world):
    info = call(world, "/api/state")["datasets"]
    assert info["competition"]["loaded"] and info["competition"]["rounds"] == 7 and info["competition"]["first"] == DAYS[0].isoformat()
    assert info["golf"]["loaded"] and info["golf"]["rounds"] == 14 and info["golf"]["first"] == DAYS[0].isoformat()


def test_without_any_round_data_everything_is_off(tmp_path):
    state = AppState(build_world(tmp_path, sleep_hours=[8.0] * len(DAYS), speed_for=lambda k: 90.0))
    info = call(state, "/api/state")["datasets"]
    assert info["competition"] == {"folder": "", "enabled": False, "loaded": False, "error": ""} and info["golf"]["loaded"] is False
    overview = call(state, "/api/rounds/overview")
    assert overview["competition"]["loaded"] is False and overview["garmin"]["loaded"] is False
    for path, params in (("/api/rounds/competition", {}), ("/api/rounds/garmin-summary", {}), ("/api/rounds/garmin-rounds", {}),
                         ("/api/rounds/trend", {"source": "garmin", "measure": "strokes"}), ("/api/rounds/trend", {"source": "competition", "measure": "gross"})):
        with pytest.raises(api.ApiError, match="No .* loaded"):
            call(state, path, **params)


def test_the_overview_offers_measures_and_years(world):
    o = call(world, "/api/rounds/overview")
    assert [m["key"] for m in o["competition"]["measures"]] == ["gross", "stableford", "differential", "hcp_new"]
    assert "fir_pct" in [m["key"] for m in o["garmin"]["measures"]] and o["competition"]["years"] == [2026] and o["competition"]["derived"] == 0


# --- trends ---------------------------------------------------------------------------------------------

def test_a_competition_trend_has_every_round_and_the_latest_averages(world):
    d = call(world, "/api/rounds/trend", source="competition", measure="gross")
    assert [p["value"] for p in d["points"]] == [80, 82, 84, 86, 88, 90, 92]
    assert d["windows"] == [5, 10] and d["latest"]["short"] == pytest.approx(np.mean([84, 86, 88, 90, 92])) and d["latest"]["long"] == pytest.approx(86)
    assert d["latest"]["all"] == pytest.approx(86)


def test_a_garmin_trend_is_calculated_from_the_holes(world):
    d = call(world, "/api/rounds/trend", source="garmin", measure="putts_18")
    assert len(d["points"]) == 14 and all(p["value"] == 36 for p in d["points"])
    assert call(world, "/api/rounds/trend", source="garmin", measure="fir_pct")["points"][0]["value"] == 100


def test_a_period_keeps_the_rounds_but_not_the_averages_of_other_periods(world):
    all_rounds = call(world, "/api/rounds/trend", source="garmin", measure="strokes")
    year = call(world, "/api/rounds/trend", source="garmin", measure="strokes", period="year:2026")
    assert len(year["points"]) == 14 and [p["short"] for p in year["points"]] == [p["short"] for p in all_rounds["points"]]
    assert call(world, "/api/rounds/trend", source="garmin", measure="strokes", period="year:2019")["points"] == []


def test_calculated_strokes_are_marked(tmp_path):
    comp = [(DAYS[0], 80, 8.0), (DAYS[1], 82, 10.0)]
    state = sleepy_rounds(tmp_path, competition=comp)[0]
    record = state.competition.copy()
    record.loc[0, "gross_derived"] = True
    state.competition = record
    d = call(state, "/api/rounds/trend", source="competition", measure="gross")
    assert [p["derived"] for p in d["points"]] == [True, False] and d["derived"] == 1
    assert call(state, "/api/rounds/overview")["competition"]["derived"] == 1


def test_bad_trend_requests_are_refused(world):
    with pytest.raises(api.ApiError, match="Unknown measure"):
        call(world, "/api/rounds/trend", source="garmin", measure="mood")
    with pytest.raises(api.ApiError, match="Unknown source"):
        call(world, "/api/rounds/trend", source="tv", measure="strokes")
    with pytest.raises(api.ApiError, match="Unknown period"):
        call(world, "/api/rounds/trend", source="garmin", measure="strokes", period="week")


# --- tables ---------------------------------------------------------------------------------------------

def test_the_competition_table_is_newest_first_and_linked_by_day(world):
    t = call(world, "/api/rounds/competition")
    assert [r["date"] for r in t["rows"]] == sorted((r["date"] for r in t["rows"]), reverse=True) and len(t["rows"]) == 7
    assert t["linked"] == 7 and t["garmin_loaded"]
    newest = t["rows"][0]
    assert newest["gross"] == 92 and newest["garmin"]["fir_pct"] == 100 and newest["garmin"]["putts_per_hole"] == 2


def test_a_competition_round_without_a_garmin_round_has_no_link(tmp_path):
    comp = [(DAYS[0], 80, 8.0), (DAYS[0] + timedelta(days=1), 82, 10.0)]
    state = sleepy_rounds(tmp_path, competition=comp)[0]
    t = call(state, "/api/rounds/competition")
    assert t["linked"] == 1 and [r["garmin"] is None for r in t["rows"]] == [True, False]


def test_without_garmin_rounds_the_table_has_no_garmin_columns(tmp_path):
    config = build_world(tmp_path, sleep_hours=[8.0] * len(DAYS), speed_for=lambda k: 90.0, competition=[(DAYS[0], 80, 8.0)])
    t = call(AppState(config), "/api/rounds/competition")
    assert t["garmin_loaded"] is False and t["linked"] == 0 and t["rows"][0]["garmin"] is None


def test_the_summary_has_three_columns(world):
    s = call(world, "/api/rounds/garmin-summary")
    assert [(c["key"], c["rounds"]) for c in s["columns"]] == [("all", 14), ("year", 14), ("last", 10)]
    rows = {r["key"]: r for r in s["rows"]}
    assert rows["rounds"]["values"]["all"] == "14" and rows["fir_pct"]["values"]["all"] == "100" and rows["putts_per_hole"]["values"]["last"] == "2.00"
    assert rows["scrambling_pct"]["values"]["all"] is None or isinstance(rows["scrambling_pct"]["values"]["all"], str)


def test_the_latest_rounds_are_listed_newest_first(world):
    t = call(world, "/api/rounds/garmin-rounds")
    assert t["rounds"] == 14 and t["rows"][0]["date"] == DAYS[-1].isoformat()
    first = t["rows"][0]
    assert first["course"] == "Golf Beispiel" and first["tee"] == "Weiss" and first["putts_18"] == 36


# --- the certificates in the dashboard ------------------------------------------------------------------

@pytest.fixture
def pdfs(tmp_path, monkeypatch):
    texts = {}
    monkeypatch.setattr(competition_module, "read_pdf_text", lambda path: texts[path.name])
    return tmp_path / "CompetitionResults", texts


def load_with_certificate(tmp_path, texts, text):
    folder = tmp_path / "CompetitionResults"
    folder.mkdir()
    (folder / "certificate.pdf").write_bytes(b"")
    texts["certificate.pdf"] = text
    config = build_world(tmp_path, sleep_hours=[8.0] * len(DAYS), speed_for=lambda k: 90.0, competition=None)
    import re
    text_toml = config.read_text(encoding="utf-8")
    config.write_text(re.sub(r'competition_dir = ".*"', 'competition_dir = "CompetitionResults"', text_toml), encoding="utf-8")
    return AppState(config)


def test_loading_the_data_reads_the_certificate_into_the_record(pdfs, tmp_path):
    _, texts = pdfs
    state = load_with_certificate(tmp_path, texts, tc.certificate(*tc.ROWS.values()))
    info = call(state, "/api/state")["datasets"]["competition"]
    assert info["loaded"] and info["rounds"] == 4 and info["error"] == "" and info["notes"] == []
    assert (tmp_path / "CompetitionResults" / RECORD_NAME).is_file()


def test_a_replaced_certificate_keeps_the_old_rounds_on_the_next_load(pdfs, tmp_path):
    _, texts = pdfs
    state = load_with_certificate(tmp_path, texts, tc.certificate(tc.ROWS["strokes_first"], tc.ROWS["differential_and_strokes"], when="30/08/2026"))
    texts["certificate.pdf"] = tc.certificate(tc.ROWS["stableford_first"], when="26/09/2026")
    state.reload_data()
    assert state.competition["date"].tolist().count("2026-05-25") == 1 and len(state.competition) == 3


def test_a_pdf_that_cannot_be_read_still_gives_the_record(pdfs, tmp_path, monkeypatch):
    _, texts = pdfs
    state = load_with_certificate(tmp_path, texts, tc.certificate(*tc.ROWS.values()))

    def broken(path):
        raise ImportError("Reading the certificate needs the pypdf package")

    monkeypatch.setattr(competition_module, "read_pdf_text", broken)
    state.reload_data()
    info = call(state, "/api/state")["datasets"]["competition"]
    assert info["loaded"] and info["rounds"] == 4 and "pypdf" in info["error"]


def test_warnings_about_the_certificate_are_passed_on(pdfs, tmp_path):
    _, texts = pdfs
    state = load_with_certificate(tmp_path, texts, tc.certificate(tc.ROWS["stableford_first"].replace("10.5", "14.5"), "7 01/05/2026 Golf Broken Competition 72/134 5.0 5.0 28 84"))
    notes = call(state, "/api/state")["datasets"]["competition"]["notes"]
    assert len(notes) == 2 and "should give" in notes[0] and "could not be read" in notes[1]


def test_the_competition_folder_can_be_chosen_and_left_empty(pdfs, tmp_path):
    _, texts = pdfs
    state = load_with_certificate(tmp_path, texts, tc.certificate(*tc.ROWS.values()))
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(api.ApiError, match="No handicap certificate"):
        call(state, "/api/load", method="POST", competition_dir=str(other))
    off = call(state, "/api/load", method="POST", competition_dir="")["datasets"]["competition"]
    assert off["enabled"] is False
    back = call(state, "/api/load", method="POST", competition_dir=str(tmp_path / "CompetitionResults"))["datasets"]["competition"]
    assert back["loaded"] and back["rounds"] == 4


# --- scores against sleep and the other health measures -------------------------------------------------

def test_round_results_are_offered_next_to_the_practice_results(world):
    keys = [o["key"] for o in call(world, "/api/garmin/overview")["outcomes"]]
    assert keys == ["swing_speed", "swing_spread", "comp_differential", "round_differential", "round_fir", "round_gir", "round_putts"]


def test_the_planted_sleep_effect_on_the_garmin_rounds_is_found(tmp_path):
    state, sleep, strokes = sleepy_rounds(tmp_path)
    table = call(state, "/api/garmin/table", outcome="round_differential")
    row = next(r for r in table["rows"] if r["key"] == "sleep_h")
    assert row["n"] == len(DAYS) and row["r"] < -0.85 and row["high"] < 0                      # more sleep, a lower differential
    assert table["sessions"] == len(DAYS) and table["title"] == "Score differential compared with the trend"


def test_the_competition_differential_can_be_related_to_sleep_too(tmp_path):
    rng = np.random.default_rng(8)
    sleep = list(rng.permutation(np.linspace(5.8, 9.2, len(DAYS))))
    comp = [(DAYS[k], 80, 14.0 - 2.0 * (sleep[k] - 5.8)) for k in range(len(DAYS))]
    state = AppState(build_world(tmp_path, sleep_hours=sleep, speed_for=lambda k: 90.0, competition=comp))
    row = next(r for r in call(state, "/api/garmin/table", outcome="comp_differential")["rows"] if r["key"] == "sleep_h")
    assert row["r"] < -0.9 and row["n"] == len(DAYS)


def test_the_scatter_of_a_round_result_has_one_dot_per_day_played(tmp_path):
    state, sleep, _ = sleepy_rounds(tmp_path)
    d = call(state, "/api/garmin/scatter", outcome="round_putts", predictor="sleep_h")
    assert d["fit"] is None or len(d["points"]) == len(DAYS)                                     # putts never vary here: no correlation
    d = call(state, "/api/garmin/scatter", outcome="round_differential", predictor="sleep_h")
    assert len(d["points"]) == len(DAYS) and d["fit"]["slope"] < 0 and "differential" in d["y_title"].lower()


def test_without_the_trend_removed_the_raw_differential_is_used(tmp_path):
    state, _, strokes = sleepy_rounds(tmp_path)
    d = call(state, "/api/garmin/scatter", outcome="round_differential", predictor="sleep_h", detrend="0")
    assert sorted(p["y"] for p in d["points"]) == pytest.approx(sorted(strokes(k) - 72.0 for k in range(len(DAYS))))
    assert d["y_title"] == "Score differential"


def test_the_round_outcome_needs_its_data(tmp_path):
    state = AppState(build_world(tmp_path, sleep_hours=[8.0] * len(DAYS), speed_for=lambda k: 90.0))
    with pytest.raises(api.ApiError, match="No Garmin round data is loaded"):
        call(state, "/api/garmin/table", outcome="round_gir")
    assert "round_gir" not in [o["key"] for o in call(state, "/api/garmin/overview")["outcomes"]]
