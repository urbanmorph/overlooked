"""iNaturalist species lists per state: paging, restart and the layer file."""

import pytest

from pipeline import inat


class FakeClient:
    """Answers species_counts with `total` taxa, PER_PAGE at a time; stops after `budget` requests."""

    def __init__(self, total, budget=100):
        self.total, self.budget, self.calls = total, budget, []

    def get(self, path, **params):
        if len(self.calls) >= self.budget:
            raise inat.Budget("budget used")
        self.calls.append(params)
        start = (params["page"] - 1) * params["per_page"]
        ids = range(start, min(start + params["per_page"], self.total))
        return {"total_results": self.total,
                "results": [{"count": 1, "taxon": {"id": i, "name": f"Aus b{i}", "iconic_taxon_name": "Insecta"}}
                            for i in ids]}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(inat, "CACHE", tmp_path)
    monkeypatch.setattr(inat, "PER_PAGE", 2)
    return tmp_path


def test_species_places_states_then_india():
    places = {"32": {"place_id": "9627"}, "4": {"place_id": "10788"}, "99": {"place_id": None}}
    assert inat.species_places(places) == [("4", "10788"), ("32", "9627"), ("india", "6681")]


def test_species_counts_pages_and_qualities(cache):
    c = FakeClient(total=3)
    done = inat.species_counts(c, [("32", "9627")], "2026-10")
    assert len(c.calls) == 4  # 2 pages x 2 quality grades
    assert {p["quality_grade"] for p in c.calls} == {"research", "needs_id"}
    assert all(p["hrank"] == "species" for p in c.calls)
    assert [r[1] for r in done["32|research"]["rows"]] == ["Aus b0", "Aus b1", "Aus b2"]
    assert inat.species_requests(done) == 4


def test_species_counts_restart_continues_at_next_page(cache):
    with pytest.raises(inat.Budget):
        inat.species_counts(FakeClient(total=5, budget=2), [("32", "9627")], "2026-10")
    doc = inat.species_doc(inat.cached("species_counts_2026-10.json"), [("32", "9627")], "2026-10-17")
    assert not doc["complete"] and len(doc["lists"]["32"]["research"]) == 4
    c = FakeClient(total=5)
    inat.species_counts(c, [("32", "9627")], "2026-10")
    assert [p["page"] for p in c.calls] == [3, 1, 2, 3]  # research page 3, then needs ID from the start
    doc = inat.species_doc(inat.cached("species_counts_2026-10.json"), [("32", "9627")], "2026-10-17")
    assert doc["complete"] and len(doc["lists"]["32"]["needs_id"]) == 5
    again = FakeClient(total=5)
    inat.species_counts(again, [("32", "9627")], "2026-10")
    assert again.calls == []  # idempotent: nothing left to fetch


def test_species_doc_drops_repeated_taxa():
    done = {"32|research": {"place_id": "1", "page": 1, "total": 2, "rows": [[1, "A b", "Aves", 3], [1, "A b", "Aves", 2]]}}
    doc = inat.species_doc(done, [("32", "1")], "d")
    assert doc["lists"]["32"]["research"] == [[1, "A b", "Aves", 3]]
