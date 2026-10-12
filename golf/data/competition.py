"""Competition rounds from the handicap certificates (PDF) of the golf federation, kept as a permanent record.

The certificate lists your latest rounds and the list changes with every new rounds: older rounds drop off the
end. So the rounds are not read from the PDF each time but copied into a record file (`competition_rounds.csv`
next to the PDFs). A new certificate adds its new rounds and refreshes the ones it still lists; rounds that are
no longer on it stay in the record untouched.

Reading the PDF needs the `pypdf` package. The parsing itself works on text, so it can be tested without a PDF.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

RECORD_NAME = "competition_rounds.csv"

RECORD_COLUMNS = [
    "date", "club", "type", "par", "slope", "course_rating", "hcp_old", "hcp_new",
    "stableford", "gross", "gross_derived", "pcc", "adjustment", "differential",
    "same_day", "first_seen", "last_seen", "source",
]
KEY_COLUMNS = ["date", "club", "par", "slope", "course_rating", "same_day"]

# A row of the certificate, with all whitespace (also line breaks) as single spaces:
#   1 26/09/2026 Golf Club Name Competition 72/134/71.5 3.6 3.6 28 84 0 0.0 10.5
_ROW = re.compile(
    r"(?<!\S)(?P<n>\d+) (?P<date>\d{2}/\d{2}/\d{4}) (?P<club>.+?) (?P<type>\S+) "
    r"(?P<par>\d+)/(?P<slope>\d+)/(?P<cr>\d+(?:\.\d+)?) "
    r"(?P<old>-?\d+\.\d) (?P<new>-?\d+\.\d) (?P<a>-?\d+(?:\.\d+)?) (?P<b>-?\d+(?:\.\d+)?) "
    r"(?P<pcc>-?\d+) (?P<adj>-?\d+\.\d) (?P<diff>-?\d+\.\d)(?!\S)"
)
_ROW_START = re.compile(r"(?<!\S)\d+ \d{2}/\d{2}/\d{4} ")
_CERTIFICATE_DATE = re.compile(r"(?<!\S)Date (\d{2}/\d{2}/\d{4})(?!\S)")

GROSS_FROM = 60           # a whole number from here is strokes, below it Stableford points
DIFFERENTIAL_TOLERANCE = 0.15


@dataclass
class Certificate:
    """What one certificate says: its date, its rounds and what could not be read."""

    certificate_date: Optional[date]
    rounds: pd.DataFrame
    warnings: List[str] = field(default_factory=list)
    unread: List[str] = field(default_factory=list)       # rows that look like rounds but could not be read


def _day(text: str) -> date:
    return datetime.strptime(text, "%d/%m/%Y").date()


def _scores(a: str, b: str):
    """Strokes and Stableford points out of the two score columns.

    The certificate does not keep the same thing in "HCP result" and "Hcp Score": for some rounds they are
    Stableford points and strokes (in either order), for others the handicap differential (a number with a
    decimal point) and one of them. So they are told apart by size: below 60 is Stableford, 60 and above strokes.
    """
    gross = stableford = None
    for token in (a, b):
        if "." in token:                       # the differential, which has its own column
            continue
        value = int(token)
        if value >= GROSS_FROM:
            gross = value
        else:
            stableford = value
    return gross, stableford


def parse_certificate_text(text: str) -> Certificate:
    """Rounds of a certificate from its text.

    A round whose strokes are not on the certificate gets them from the differential (and the course rating,
    slope and PCC), marked `gross_derived`. A round whose strokes and differential do not agree is reported
    in `warnings`; a row that cannot be read is reported in `unread` and never dropped silently.
    """
    flat = " ".join(text.split())
    match = _CERTIFICATE_DATE.search(flat)
    certificate_date = _day(match.group(1)) if match else None

    rows, warnings = [], []
    seen: Dict[tuple, int] = {}
    matched_at = set()
    for m in _ROW.finditer(flat):
        matched_at.add(m.start())
        par, slope, rating = int(m["par"]), int(m["slope"]), float(m["cr"])
        pcc, differential = int(m["pcc"]), float(m["diff"])
        gross, stableford = _scores(m["a"], m["b"])
        derived = gross is None
        if derived:
            gross = int(round(differential * slope / 113.0 + rating + pcc))
        else:
            expected = (gross - rating - pcc) * 113.0 / slope
            if abs(expected - differential) > DIFFERENTIAL_TOLERANCE:
                warnings.append(f"{m['date']} {m['club']}: {gross} strokes should give a differential of {expected:.1f}, the certificate says {differential}")
        key = (m["date"], m["club"], par, slope, rating)
        seen[key] = seen.get(key, 0) + 1
        rows.append({
            "date": _day(m["date"]).isoformat(), "club": m["club"], "type": m["type"], "par": par, "slope": slope,
            "course_rating": rating, "hcp_old": float(m["old"]), "hcp_new": float(m["new"]),
            "stableford": stableford, "gross": gross, "gross_derived": derived, "pcc": pcc,
            "adjustment": float(m["adj"]), "differential": differential, "same_day": seen[key],
        })

    unread = []
    for start in _ROW_START.finditer(flat):
        if start.start() not in matched_at:
            unread.append(flat[start.start():start.start() + 110])
    frame = pd.DataFrame(rows, columns=[c for c in RECORD_COLUMNS if c not in ("first_seen", "last_seen", "source")])
    return Certificate(certificate_date, frame, warnings, unread)


def read_pdf_text(path: Path) -> str:
    """All text of a PDF (needs the `pypdf` package)."""
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise ImportError("Reading the certificate needs the pypdf package: run  pip install pypdf  in the golf environment") from error
    return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)


def read_certificate(path: Path) -> Certificate:
    return parse_certificate_text(read_pdf_text(Path(path)))


def round_key(row) -> str:
    """A text that names one round of the record (for choosing which rounds take part)."""
    return f"{row['date']}|{row['club']}|{row['par']}/{row['slope']}/{row['course_rating']}|{row['same_day']}"


def with_round_keys(record: pd.DataFrame) -> pd.DataFrame:
    keyed = record.copy()
    keyed["round_key"] = [round_key(row) for _, row in record.iterrows()]
    return keyed


def load_record(folder: Path) -> pd.DataFrame:
    """The record of all rounds seen so far (empty if there is none yet)."""
    path = Path(folder) / RECORD_NAME
    if not path.is_file():
        return pd.DataFrame(columns=RECORD_COLUMNS)
    record = pd.read_csv(path, encoding="utf-8")
    missing = [c for c in RECORD_COLUMNS if c not in record.columns]
    if missing:
        raise ValueError(f"{path} is not a rounds record (missing columns: {', '.join(missing)})")
    record["gross_derived"] = record["gross_derived"].astype(bool)
    return record[RECORD_COLUMNS]


def merge_certificate(record: pd.DataFrame, certificate: Certificate, source: str) -> tuple[pd.DataFrame, int, int]:
    """Add the rounds of a certificate to the record. Returns the new record and the numbers added and refreshed."""
    seen = (certificate.certificate_date or date.today()).isoformat()
    rows = certificate.rounds.copy()
    rows["source"] = source
    rows["last_seen"] = seen
    rows["first_seen"] = seen

    record = record.copy()
    index = {tuple(r): i for i, r in zip(record.index, record[KEY_COLUMNS].itertuples(index=False, name=None))}
    added = refreshed = 0
    new_rows = []
    for row in rows.to_dict("records"):
        key = tuple(row[c] for c in KEY_COLUMNS)
        if key in index:
            i = index[key]
            row["first_seen"] = min(record.at[i, "first_seen"], seen)          # keep when it was first seen
            row["last_seen"] = max(record.at[i, "last_seen"], seen)
            for column in RECORD_COLUMNS:
                record.at[i, column] = row[column]
            refreshed += 1
        else:
            new_rows.append(row)
            added += 1
    if new_rows:
        added_rows = pd.DataFrame(new_rows, columns=RECORD_COLUMNS)
        record = added_rows if record.empty else pd.concat([record, added_rows], ignore_index=True)
    record = record.sort_values(["date", "club", "same_day"], ascending=[False, True, True]).reset_index(drop=True)
    return record[RECORD_COLUMNS], added, refreshed


@dataclass
class UpdateReport:
    certificates: List[dict] = field(default_factory=list)       # one entry per PDF: name, date, rounds, added, refreshed
    warnings: List[str] = field(default_factory=list)
    unread: List[str] = field(default_factory=list)
    rounds: int = 0                                              # rounds in the record afterwards
    kept: int = 0                                                # rounds in the record that no certificate lists any more


def update_record(folder: Path) -> UpdateReport:
    """Read every PDF in `folder`, oldest certificate first, and update the record file next to them."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"{folder} is not a folder")
    report = UpdateReport()
    record = load_record(folder)
    parsed = []
    for pdf in sorted(folder.glob("*.pdf")):
        certificate = read_certificate(pdf)
        parsed.append((certificate.certificate_date or date.min, pdf.stat().st_mtime, pdf, certificate))
    for _, _, pdf, certificate in sorted(parsed, key=lambda item: (item[0], item[1])):
        record, added, refreshed = merge_certificate(record, certificate, pdf.name)
        report.certificates.append({
            "file": pdf.name, "date": certificate.certificate_date.isoformat() if certificate.certificate_date else "",
            "rounds": int(len(certificate.rounds)), "added": added, "refreshed": refreshed,
        })
        report.warnings += [f"{pdf.name}: {w}" for w in certificate.warnings]
        report.unread += [f"{pdf.name}: {u}" for u in certificate.unread]
    if parsed:
        record.to_csv(folder / RECORD_NAME, index=False, encoding="utf-8")
    elif record.empty:
        raise FileNotFoundError(f"No PDF certificate and no {RECORD_NAME} in {folder}")
    report.rounds = int(len(record))
    if parsed and not record.empty:
        latest = max(p[3].certificate_date or date.min for p in parsed).isoformat()
        report.kept = int((record["last_seen"] < latest).sum())
    return report
