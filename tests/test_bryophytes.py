"""The bryophytes of India (pipeline/bryophytes.py): names read from the checklist's text, by section and genus."""

import pymupdf
import pytest

from pipeline import bryophytes

LINES = [
    "Abstract: total 2489 taxa", "1786 species of mosses",                   # numbers in prose: not rows
    "LIST OF MOSSES FOUND IN INDIA", "GENUS- Andreaea", "1", "A. rupestris", "Kashmir",
    "2", "A.  wilsonii var. minor", "Sikkim", "Rare in Kerala",
    "GENUS-Rhynchostegium", "3 R.. celebicum", "Garhwal", "4", "R.duthiei", "Endemic in Himalayas",
    "GENUS-", "Funaria", "6", "F.", "hygrometrica", "var.", "calvescens", "South India",   # 5 is not in the paper
    "LIST OF LIVERWORTS FOUND IN INDIA", "GENUS- Riccia", "1", "R. billardierei", "Kerala",
    "ARCHIVE FOR BRYOLOGY 88 (2011)", "2",                                       # a running title and page number
    "2", "Riccia gangetica", "Allahabad", "3", "R", "susp.", "x", "4", "R crystallina", "Bombay",
    "LIST OF HORNWORTS FOUND IN INDIA", "GENUS- Notothylas", "1", "N. indica", "Madras",
    "REFERENCES", "1", "Chopra, R.S. 1975. Taxonomy of Indian Mosses.",
]


@pytest.fixture
def pdf(tmp_path):
    doc = pymupdf.open()
    for part in (LINES[:12], LINES[12:]):                                     # two pages
        p = doc.new_page(width=595, height=842)
        for i, line in enumerate(part):
            p.insert_text((60, 60 + 14 * i), line, fontsize=9)
    path = tmp_path / "b.pdf"
    doc.save(path)
    return path


def test_rows_by_section_with_the_genus_written_out(pdf):
    rows = bryophytes.parse(pdf)
    assert [(r["section"], r["no"], r["name"]) for r in rows] == [
        ("mosses", 1, "Andreaea rupestris"), ("mosses", 2, "Andreaea wilsonii var. minor"),
        ("mosses", 3, "Rhynchostegium celebicum"), ("mosses", 4, "Rhynchostegium duthiei"),
        ("mosses", 6, "Funaria hygrometrica var. calvescens"),
        ("liverworts", 1, "Riccia billardierei"), ("liverworts", 2, "Riccia gangetica"), ("liverworts", 3, None),
        ("liverworts", 4, "Riccia crystallina"), ("hornworts", 1, "Notothylas indica")]
    assert rows[0]["phylum"] == "Bryophyta" and rows[5]["phylum"] == "Marchantiophyta"
    assert rows[-1]["phylum"] == "Anthocerotophyta" and rows[3]["page"] == 2


def test_check_reports_numbers_not_read_except_those_the_paper_skips_and_rows_with_no_name():
    rows = [{"section": "mosses", "no": 1, "name": "Aus bus"}, {"section": "mosses", "no": 3, "name": "Aus cus"},
            {"section": "mosses", "no": 5, "name": None}]
    problems = bryophytes.check(rows, {"mosses": 5}, {"mosses": [4]})
    assert any("mosses" in p and "[2]" in p for p in problems) and any("no name" in p for p in problems)
    assert bryophytes.check(rows[:2], {"mosses": 3}, {"mosses": [2]}) == []


def test_run_downloads_once_and_keeps_both_files_in_r2(pdf, tmp_path, monkeypatch):
    from tests.r2_fake import FakeS3
    monkeypatch.setenv("R2_BUCKET", "b")
    monkeypatch.setattr(bryophytes, "TAXA", {"mosses": 6, "liverworts": 4, "hornworts": 1})
    monkeypatch.setattr(bryophytes, "SKIPPED", {"mosses": [5]})
    monkeypatch.setattr(bryophytes, "NO_NAME", {("liverworts", 3)})

    class Http:
        calls = 0

        def get(self, url, **kw):
            Http.calls += 1
            return type("R", (), {"content": pdf.read_bytes(), "raise_for_status": lambda self: None,
                                  "headers": {"Content-Type": "application/pdf"}})()

    s3 = FakeS3()
    table = bryophytes.run(Http(), s3, tmp_path / "c")
    assert table.read_text().splitlines()[1].startswith("mosses,1,Andreaea rupestris")
    assert {bryophytes.R2_DIR + bryophytes.PDF, bryophytes.R2_DIR + bryophytes.TABLE} <= set(s3.store)
    bryophytes.run(Http(), s3, tmp_path / "c")
    assert Http.calls == 1


def test_a_row_printed_after_the_next_one_still_counts():
    rows = [{"section": "mosses", "no": n, "name": "Aus bus"} for n in (1, 3, 2)]
    assert bryophytes.check(rows, {"mosses": 3}, {}) == []
