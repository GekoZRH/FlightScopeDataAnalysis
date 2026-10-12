import re
from datetime import date

import pandas as pd
import pytest

from golf.data import competition
from golf.data.competition import (KEY_COLUMNS, RECORD_COLUMNS, RECORD_NAME, load_record, merge_certificate,
                                   parse_certificate_text, update_record)

HEADER = """Handicap Certificate
Name Test Player HCP Index 5.0 HCP Status Valid
Home club Golf Example Low HCP 4.8
National ID 00-00 Date {when}
# Date Club Type Par/Slope/CR HCP Old HCP New HCP result Hcp Score PCC Adj. Hcp.res
"""

# the four ways the two score columns are filled on a certificate
ROWS = {
    "stableford_first": "1 26/09/2026 Golf Example Competition 72/134/71.5 5.0 5.0 28 84 0 0.0 10.5",
    "strokes_first": "2 30/08/2026 Golf und Country Club Beispiel-Zürich Competition 72/136/71.7 5.0 5.0 86 26 1 0.0 11.1",
    "differential_and_strokes": "3 25/05/2026 Golf Kyburg Competition 71/136/72.9 5.0 5.0 13.4 89 0 0.0 13.4",
    "differential_and_stableford": "4 09/05/2026 Golfclub Test / Golfpark Test Competition 71/128/71.1 5.0 5.0 14.0 24 0 0.0 14.0",
}


def certificate(*rows, when="26/09/2026"):
    return HEADER.format(when=when) + "\n".join(rows) + "\n"


# --- reading one certificate ------------------------------------------------------------------------------

def test_the_date_and_every_round_are_read():
    c = parse_certificate_text(certificate(*ROWS.values()))
    assert c.certificate_date == date(2026, 9, 26) and len(c.rounds) == 4
    first = c.rounds.iloc[0]
    assert (first["date"], first["club"], first["type"], first["par"], first["slope"], first["course_rating"]) == \
        ("2026-09-26", "Golf Example", "Competition", 72, 134, 71.5)
    assert (first["hcp_old"], first["hcp_new"], first["pcc"], first["adjustment"], first["differential"]) == (5.0, 5.0, 0, 0.0, 10.5)
    assert c.warnings == [] and c.unread == []


def test_the_score_columns_are_told_apart_by_size():
    r = parse_certificate_text(certificate(*ROWS.values())).rounds
    assert list(zip(r["gross"], r["stableford"].fillna(-1).astype(int), r["gross_derived"])) == [
        (84, 28, False),        # Stableford then strokes
        (86, 26, False),        # strokes then Stableford
        (89, -1, False),        # differential then strokes
        (87, 24, True),         # differential then Stableford: strokes follow from the differential
    ]


def test_missing_strokes_follow_from_the_differential():
    r = parse_certificate_text(certificate(ROWS["differential_and_stableford"])).rounds.iloc[0]
    assert r["gross"] == round(14.0 * 128 / 113 + 71.1) and r["gross_derived"]


def test_the_pcc_is_part_of_the_differential_check():
    c = parse_certificate_text(certificate(ROWS["strokes_first"]))              # 86 strokes with PCC 1 gives 11.1
    assert c.warnings == []


def test_strokes_that_do_not_fit_the_differential_are_reported():
    wrong = ROWS["stableford_first"].replace("10.5", "14.5")
    c = parse_certificate_text(certificate(wrong))
    assert len(c.rounds) == 1 and len(c.warnings) == 1 and "84 strokes" in c.warnings[0]


def test_the_same_course_twice_on_a_day_is_two_rounds():
    twice = "5 09/05/2026 Golfclub Test Competition 71/128/71.1 5.0 5.0 24 87 0 0.0 14.0"
    c = parse_certificate_text(certificate(twice, twice.replace("5 09", "6 09").replace("24 87", "30 81").replace("14.0", "8.7")))
    assert list(c.rounds["same_day"]) == [1, 2]


def test_line_breaks_inside_a_row_do_not_matter():
    spread = ROWS["stableford_first"].replace(" ", "\n")
    assert len(parse_certificate_text(certificate(spread)).rounds) == 1


def test_a_row_that_cannot_be_read_is_reported_and_not_lost_silently():
    broken = "7 01/05/2026 Golf Broken Competition 72/134 5.0 5.0 28 84"
    c = parse_certificate_text(certificate(ROWS["stableford_first"], broken))
    assert len(c.rounds) == 1 and len(c.unread) == 1 and "Golf Broken" in c.unread[0]


def test_a_text_without_rounds_is_empty_not_an_error():
    c = parse_certificate_text("Handicap Certificate")
    assert c.rounds.empty and c.certificate_date is None


# --- the record -------------------------------------------------------------------------------------------

def merged(*texts):
    record = pd.DataFrame(columns=RECORD_COLUMNS)
    for i, text in enumerate(texts):
        record, _, _ = merge_certificate(record, parse_certificate_text(text), f"c{i}.pdf")
    return record


def test_a_new_certificate_adds_its_new_rounds():
    old = certificate(ROWS["strokes_first"], ROWS["differential_and_strokes"], when="30/08/2026")
    new = certificate(ROWS["stableford_first"], ROWS["strokes_first"], when="26/09/2026")
    record = merged(old, new)
    assert len(record) == 3 and set(record["date"]) == {"2026-09-26", "2026-08-30", "2026-05-25"}


def test_rounds_that_dropped_off_the_certificate_stay_in_the_record():
    old = certificate(ROWS["strokes_first"], ROWS["differential_and_strokes"], when="30/08/2026")
    new = certificate(ROWS["stableford_first"], when="26/09/2026")                         # the other two are gone
    record = merged(old, new)
    kept = record[record["date"] == "2026-05-25"].iloc[0]
    assert len(record) == 3 and kept["gross"] == 89 and kept["last_seen"] == "2026-08-30" and kept["source"] == "c0.pdf"


def test_a_round_still_on_the_certificate_is_refreshed_not_duplicated():
    first = certificate(ROWS["strokes_first"], when="30/08/2026")
    corrected = certificate(ROWS["strokes_first"].replace("11.1", "12.0").replace(" 1 0.0 ", " 0 0.0 "), when="26/09/2026")
    record = merged(first, corrected)
    assert len(record) == 1
    row = record.iloc[0]
    assert row["first_seen"] == "2026-08-30" and row["last_seen"] == "2026-09-26" and row["differential"] == 12.0 and row["pcc"] == 0


def test_reading_the_same_certificate_twice_changes_nothing():
    text = certificate(*ROWS.values())
    record = merged(text, text)
    assert len(record) == 4 and (record["first_seen"] == record["last_seen"]).all()


def test_the_record_is_sorted_newest_first():
    record = merged(certificate(*ROWS.values()))
    assert list(record["date"]) == sorted(record["date"], reverse=True)


# --- the folder -------------------------------------------------------------------------------------------

@pytest.fixture
def folder(tmp_path, monkeypatch):
    texts = {}
    monkeypatch.setattr(competition, "read_pdf_text", lambda path: texts[path.name])
    return tmp_path, texts


def test_the_record_file_is_written_and_read_back(folder):
    path, texts = folder
    (path / "certificate.pdf").write_bytes(b"")
    texts["certificate.pdf"] = certificate(*ROWS.values())
    report = update_record(path)
    assert report.rounds == 4 and report.certificates[0]["added"] == 4 and report.kept == 0
    record = load_record(path)
    assert list(record.columns) == RECORD_COLUMNS and len(record) == 4
    assert record["club"].str.contains("Zürich").any()                                      # umlauts survive the file
    assert (path / RECORD_NAME).is_file()


def test_a_replaced_pdf_keeps_the_old_rounds(folder):
    path, texts = folder
    (path / "certificate.pdf").write_bytes(b"")
    texts["certificate.pdf"] = certificate(ROWS["strokes_first"], ROWS["differential_and_strokes"], when="30/08/2026")
    update_record(path)
    texts["certificate.pdf"] = certificate(ROWS["stableford_first"], when="26/09/2026")      # same file name, new content
    report = update_record(path)
    assert report.rounds == 3 and report.kept == 2 and report.certificates[0]["added"] == 1
    assert len(load_record(path)) == 3


def test_several_pdfs_are_read_oldest_certificate_first(folder):
    path, texts = folder
    for name, when in (("a.pdf", "26/09/2026"), ("b.pdf", "30/08/2026")):
        (path / name).write_bytes(b"")
    texts["a.pdf"] = certificate(ROWS["stableford_first"], ROWS["strokes_first"], when="26/09/2026")
    texts["b.pdf"] = certificate(ROWS["strokes_first"], when="30/08/2026")
    report = update_record(path)
    assert [c["date"] for c in report.certificates] == ["2026-08-30", "2026-09-26"]
    assert report.rounds == 2 and load_record(path).set_index("date").loc["2026-08-30", "last_seen"] == "2026-09-26"


def test_unreadable_rows_and_warnings_are_passed_on(folder):
    path, texts = folder
    (path / "c.pdf").write_bytes(b"")
    texts["c.pdf"] = certificate(ROWS["stableford_first"].replace("10.5", "14.5"), "7 01/05/2026 Golf Broken Competition 72/134 5.0 5.0 28 84")
    report = update_record(path)
    assert len(report.warnings) == 1 and len(report.unread) == 1 and "c.pdf" in report.warnings[0]


def test_a_folder_with_only_the_record_is_fine(folder):
    path, texts = folder
    (path / "c.pdf").write_bytes(b"")
    texts["c.pdf"] = certificate(*ROWS.values())
    update_record(path)
    (path / "c.pdf").unlink()                                                               # the PDF is gone, the record remains
    report = update_record(path)
    assert report.rounds == 4 and report.certificates == []


def test_an_empty_folder_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="No PDF certificate"):
        update_record(tmp_path)
    with pytest.raises(FileNotFoundError, match="not a folder"):
        update_record(tmp_path / "missing")


def test_a_file_that_is_not_a_record_is_refused(tmp_path):
    (tmp_path / RECORD_NAME).write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a rounds record"):
        load_record(tmp_path)


def test_without_pypdf_the_message_says_what_to_install(tmp_path, monkeypatch):
    import builtins
    real = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "pypdf":
            raise ImportError("no pypdf")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(ImportError, match="pip install pypdf"):
        competition.read_pdf_text(tmp_path / "x.pdf")


def test_key_columns_are_part_of_the_record():
    assert set(KEY_COLUMNS) <= set(RECORD_COLUMNS)
