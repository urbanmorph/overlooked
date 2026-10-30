"""The lichen checklist of India (pipeline/lichens.py): rows read by position from the PDF's text layer."""

import pymupdf
import pytest

from pipeline import lichens


def page(doc, shift, rows, prose=None):
    """One table page as the paper sets it: the running title, then rows at the paper's column positions."""
    p = doc.new_page(width=595, height=842)
    p.insert_text((150, 40), "A comprehensive checklist of lichens from India - 2024", fontsize=9)
    y = 120
    for no, taxon, gf, sub, states, regions, status in rows:
        for text, x in ((str(no), 47), (gf, 269), (sub, 320), (states, 366), (regions, 435), (status, 488)):
            if text:
                p.insert_text((x + shift, y), text, fontsize=8)
        for i, line in enumerate(taxon):
            p.insert_text((82 + shift, y + 11 * i), line, fontsize=8)
        y += 11 * max(len(taxon), 1) + 5
    if prose:
        p.insert_text((82 + shift, y + 5), prose, fontsize=8)


@pytest.fixture
def pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(lichens, "TAXA", 4)
    monkeypatch.setattr(lichens, "FIRST_PAGE", 1)
    monkeypatch.setattr(lichens, "LAST_PAGE", 2)
    doc = pymupdf.open()
    page(doc, 0, [(1, ["Acarospora fuscata (Ach.) Arnold"], "CR", "SX", "HP UK", "WH", ""),
                  (2, ["A. nitrophila H. Magn. = Acarospora", "praeruptarum H. Magn."], "CR", "SX 8", "JK", "WH", "END")])
    page(doc, 29, [(3, ["Collema nigrescens (Huds.) DC."], "FO", "CO", "TN", "WG", ""),     # a page set further right
                   (4, ["C.ryssoleum (Tuck.) Tuck."], "FO", "CO", "SK WB", "EH", "")],            # a misprint
         prose="31 states and 4 regions: the discussion follows the table")
    path = tmp_path / "l.pdf"
    doc.save(path)
    return path


def test_rows_by_position_with_shortened_genera_misprints_and_the_text_after(pdf):
    rows = lichens.parse(pdf)
    assert lichens.check(rows) == []
    assert [r["name"] for r in rows] == ["Acarospora fuscata", "Acarospora nitrophila", "Collema nigrescens",
                                         "Collema ryssoleum"]
    one, two = rows[0], rows[1]
    assert (one["authority"], one["states"], one["growth_form"], one["endemic"]) == ("(Ach.) Arnold", "Himachal Pradesh;Uttarakhand", "CR", False)
    assert two["synonyms"] == "Acarospora praeruptarum H. Magn." and two["endemic"] and two["substratum"] == "SX"
    assert rows[3]["regions"] == "EH" and "discussion" not in str(rows[3])          # the text after the table


def test_split_taxon():
    assert lichens.split_taxon("A. archeri B.O. Sharma ≡ Graphis archeri Nyl.", "Acanthothecis") == \
        ("Acanthothecis archeri", "B.O. Sharma", "Graphis archeri Nyl.")
    assert lichens.split_taxon("C.ryssoleum (Tuck.) Tuck.", "Collema")[0] == "Collema ryssoleum"
    assert lichens.split_taxon("P trichothelioides R. Sant.", "Porina")[0] == "Porina trichothelioides"
    assert lichens.split_taxon("B. x Y.", "Acarospora") == (None, None, None)          # the genus does not fit


def test_check_names_missing_rows(monkeypatch):
    monkeypatch.setattr(lichens, "TAXA", 4)
    assert lichens.check([{"no": 1, "name": "A b", "page": 1}, {"no": 3, "name": None, "page": 1}]) == [
        "2 rows; missing [2, 4]; not expected []", "row 3 (page 1): no name"]
