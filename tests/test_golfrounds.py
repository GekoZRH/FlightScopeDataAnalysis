import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from golf.data.golfrounds import describe_golf_rounds, find_golf_folder, load_golf_rounds

import fitbuild as fb

ZONE = "Europe/Zurich"
PARS = [4, 5, 3, 4, 4, 3, 5, 4, 4, 4, 3, 5, 4, 4, 3, 4, 5, 4]            # 72
INDEX = list(range(1, 19))


def hole(number, strokes, putts=2, fairway="HIT", penalties=None):
    out = {"number": number, "strokes": strokes, "handicapScore": strokes, "pinPositionLat": 1, "pinPositionLon": 2}
    if putts is not None:
        out["putts"] = putts
    if fairway is not None:
        out["fairwayShotOutcome"] = fairway
    if penalties is not None:
        out["penalties"] = penalties
    return out


def card(round_id, start="2026-03-14T08:00:00Z", holes=None, **extra):
    holes = holes if holes is not None else [hole(n, p + 1) for n, p in enumerate(PARS, start=1)]
    base = {
        "id": round_id, "courseGlobalId": 28390, "startTime": start, "formattedStartTime": start, "holesCompleted": len(holes),
        "roundType": "ALL", "inProgress": False, "excludeFromStats": False, "teeBox": "Weiss", "teeBoxRating": 72.0, "teeBoxSlope": 130,
        "strokes": sum(h["strokes"] for h in holes), "holes": holes,
    }
    base.update(extra)
    return base


def write_export(folder, cards, fits=None):
    golf = folder / "DI_CONNECT" / "DI-GOLF"
    golf.mkdir(parents=True)
    (golf / "Golf-SCORECARD.json").write_text(json.dumps({"version": "v1", "type": "SCORECARD", "data": cards}), encoding="utf-8")
    for round_id, content in (fits or {}).items():
        (golf / f"Golf-SCORECARD_RAWDATA-{round_id}.fit").write_bytes(content)
    return golf


@pytest.fixture
def export(tmp_path):
    cards = [
        card(2, start="2026-03-15T08:00:00Z"),
        card(1, start="2026-03-14T08:00:00Z"),
        card(3, holes=[hole(n, 5) for n in range(1, 10)], start="2026-03-16T08:00:00Z"),       # 9 holes: not a full round
        card(4, start="2026-03-17T08:00:00Z", excludeFromStats=True),
        card(5, start="2026-03-18T08:00:00Z", inProgress=True),
        card(6, start="2026-03-19T08:00:00Z"),                                                  # no raw file: no par
    ]
    fits = {i: fb.golf_fit("Golf Beispiel ~ Platz", list(zip(PARS, INDEX))) for i in (1, 2)}
    write_export(tmp_path, cards, fits)
    return tmp_path


def test_only_full_counted_rounds_are_read_oldest_first(export):
    g = load_golf_rounds(export, ZONE)
    assert list(g.rounds["round_id"]) == [1, 2, 6]
    assert len(g.holes) == 54 and describe_golf_rounds(g) == {"rounds": 3, "first": "2026-03-14", "last": "2026-03-19"}


def test_course_par_and_stroke_index_come_from_the_raw_file(export):
    g = load_golf_rounds(export, ZONE)
    first = g.rounds.iloc[0]
    assert first["course"] == "Golf Beispiel ~ Platz" and first["par"] == 72 and (first["rating"], first["slope"], first["strokes"]) == (72.0, 130, 90)
    holes = g.holes[g.holes["round_id"] == 1].sort_values("hole")
    assert list(holes["par"]) == PARS and list(holes["stroke_index"]) == INDEX


def test_a_round_without_a_raw_file_has_no_par_but_keeps_its_scores(export):
    g = load_golf_rounds(export, ZONE)
    row = g.rounds[g.rounds["round_id"] == 6].iloc[0]
    assert np.isnan(row["par"]) and row["course"] == "course 28390" and row["strokes"] == 90
    assert g.holes[g.holes["round_id"] == 6]["par"].isna().all() and g.holes[g.holes["round_id"] == 6]["strokes"].notna().all()


def test_the_date_is_the_local_day(tmp_path):
    cards = [card(1, start="2026-03-14T23:30:00Z"), card(2, start="2026-07-14T22:30:00Z")]       # 00:30 and 00:30 local (winter and summer time)
    write_export(tmp_path, cards)
    dates = list(load_golf_rounds(tmp_path, ZONE).rounds["date"])
    assert dates == [date(2026, 3, 15), date(2026, 7, 15)]


def test_missing_putts_fairways_and_penalties_stay_missing(tmp_path):
    holes = [hole(n, p + 1, putts=None if n == 1 else 2, fairway=None if n == 2 else "HIT", penalties=2 if n == 3 else None) for n, p in enumerate(PARS, start=1)]
    write_export(tmp_path, [card(1, holes=holes)])
    g = load_golf_rounds(tmp_path, ZONE).holes.set_index("hole")
    assert np.isnan(g.loc[1, "putts"]) and g.loc[2, "fairway"] is None and g.loc[3, "penalties"] == 2 and np.isnan(g.loc[4, "penalties"])


def test_a_damaged_raw_file_is_ignored_not_fatal(tmp_path):
    write_export(tmp_path, [card(1)], {1: b"not a fit file"})
    g = load_golf_rounds(tmp_path, ZONE)
    assert len(g.rounds) == 1 and np.isnan(g.rounds.iloc[0]["par"])


def test_an_implausible_par_is_not_used(tmp_path):
    write_export(tmp_path, [card(1)], {1: fb.golf_fit("X", [(9, 1)] * 18)})
    assert np.isnan(load_golf_rounds(tmp_path, ZONE).rounds.iloc[0]["par"])


def test_the_golf_folder_may_be_given_at_several_levels(export):
    golf = export / "DI_CONNECT" / "DI-GOLF"
    for level in (export, export / "DI_CONNECT", golf):
        assert find_golf_folder(level) == golf


def test_an_export_without_golf_data_is_reported(tmp_path):
    assert find_golf_folder(tmp_path) is None
    with pytest.raises(FileNotFoundError, match="No golf scorecards"):
        load_golf_rounds(tmp_path, ZONE)


def test_no_full_round_gives_empty_tables(tmp_path):
    write_export(tmp_path, [card(1, holes=[hole(n, 5) for n in range(1, 10)])])
    g = load_golf_rounds(tmp_path, ZONE)
    assert g.rounds.empty and g.holes.empty and list(g.rounds.columns)[:2] == ["round_id", "start_utc"]
