"""GRIIS India (pipeline/griis.py): the species of India's Global Register of Introduced and Invasive Species, read
from GBIF's species API page by page, kept in R2, and used as a flag (label 'int'), never a filter."""

import duckdb

from pipeline import griis


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeApi:
    """Two pages of names: species, a variety (left out: only species-rank names flag a species) and a genus."""

    def __init__(self, fail=False):
        self.fail, self.asked = fail, []

    def get(self, url, params=None, **kw):
        self.asked.append(params["offset"])
        if self.fail:
            raise ConnectionError("down")
        pages = {0: [{"canonicalName": "Oreochromis mossambicus", "rank": "SPECIES"},
                     {"canonicalName": "Coffea arabica", "rank": "SPECIES"}],
                 2: [{"canonicalName": "Lantana camara aculeata", "rank": "VARIETY"},
                     {"canonicalName": "Pangasianodon hypophthalmus", "rank": "SPECIES"},
                     {"canonicalName": "Acacia", "rank": "GENUS"}]}
        return Resp({"results": pages.get(params["offset"], []), "endOfRecords": params["offset"] >= 2})


def test_species_names_from_every_page(tmp_path, monkeypatch):
    monkeypatch.setattr(griis, "LIMIT", 2)
    http = FakeApi()
    out = griis.refresh(http, None, tmp_path)
    assert http.asked == [0, 2]
    names = [r[0] for r in duckdb.sql(f"SELECT name FROM '{out}' ORDER BY 1").fetchall()]
    assert names == ["Coffea arabica", "Oreochromis mossambicus", "Pangasianodon hypophthalmus"]


def test_the_last_copy_when_gbif_does_not_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(griis, "LIMIT", 2)
    first = griis.refresh(FakeApi(), None, tmp_path)
    again = griis.refresh(FakeApi(fail=True), None, tmp_path)
    assert again == first and again.exists()
    assert griis.refresh(FakeApi(fail=True), None, tmp_path / "empty") is None
