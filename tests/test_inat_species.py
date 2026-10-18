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


def test_genus_counts_pages_and_restart(cache):
    """Genera of needs-ID observations named only to genus, per area; saved after every page."""
    with pytest.raises(inat.Budget):
        inat.genus_counts(FakeClient(total=5, budget=2), [("32", "9627")], "2026-10")
    c = FakeClient(total=5)
    inat.genus_counts(c, [("32", "9627")], "2026-10")
    assert [p["page"] for p in c.calls] == [3]
    assert all(p["rank"] == "genus" and p["quality_grade"] == "needs_id" for p in c.calls)
    doc = inat.genus_doc(inat.cached("genus_counts_2026-10.json"), [("32", "9627")], "2026-10-18")
    assert doc["complete"] and len(doc["lists"]["32"]) == 5 and doc["places"] == {"32": "9627"}


class CountClient:
    """Answers observations?per_page=0 with a count per iconic group."""

    def __init__(self, budget=100):
        self.budget, self.calls = budget, []

    def get(self, path, **params):
        if len(self.calls) >= self.budget:
            raise inat.Budget("budget used")
        self.calls.append(params)
        return {"total_results": len(params["iconic_taxa"])}


def test_coarse_counts_per_area_and_group(cache):
    """Needs-ID observations named only above genus (subtribe or higher), per area and iconic group."""
    groups = ["Aves", "Insecta"]
    with pytest.raises(inat.Budget):
        inat.coarse_counts(CountClient(budget=3), [("32", "9627"), ("india", "6681")], "2026-10", groups)
    c = CountClient()
    inat.coarse_counts(c, [("32", "9627"), ("india", "6681")], "2026-10", groups)
    assert len(c.calls) == 1 and c.calls[0]["lrank"] == "subtribe" and c.calls[0]["per_page"] == 0
    doc = inat.coarse_doc(inat.cached("coarse_counts_2026-10.json"), [("32", "9627"), ("india", "6681")], "d", groups)
    assert doc["complete"] and doc["counts"] == {"32": {"Aves": 4, "Insecta": 7}, "india": {"Aves": 4, "Insecta": 7}}
