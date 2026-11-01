"""eBird's species with records from India (pipeline/ebird_india.py): a current, reviewed bird list that has the newer
splits (Ardea coromanda, Tyto javanica) the 2023 checklists lack. From GBIF's eBird Observation Dataset, by Catalogue
of Life ID; kept in R2's cache."""

import json

from pipeline import ebird_india


class Http:
    def __init__(self, counts=None, fail=False):
        self.counts, self.fail, self.urls = counts or {}, fail, []

    def get(self, url, params=None, **kw):
        self.urls.append((url, params))
        if self.fail:
            raise ConnectionError("down")
        body = {"facets": [{"field": "SPECIES_KEY", "counts": [{"name": k, "count": n} for k, n in self.counts.items()]}]}
        return type("R", (), {"json": lambda self: body, "raise_for_status": lambda self: None})()


def test_the_species_with_enough_records_are_on_the_list(tmp_path):
    http = Http({"9KHT": 1219440, "4QMM8": 659076, "X1": 3})
    path = ebird_india.refresh(http, None, tmp_path)
    assert json.loads(path.read_text()) == {"9KHT": 1219440, "4QMM8": 659076, "X1": 3}
    assert ebird_india.keys(path) == {"9KHT", "4QMM8"}                  # 3 records: a vagrant or an error
    _, params = http.urls[0]
    assert params["checklistKey"] == ebird_india.COL_XR and params["country"] == "IN"
    assert params["datasetKey"] == ebird_india.EBIRD


def test_a_run_that_cannot_reach_gbif_and_has_no_copy_gives_none(tmp_path):
    assert ebird_india.refresh(Http(fail=True), None, tmp_path) is None
    assert ebird_india.keys(None) == set()


def test_a_short_answer_is_refused_not_saved(tmp_path):
    http = Http({f"K{i}": 100 for i in range(ebird_india.FACET_LIMIT)})   # the limit reached: the list may be cut
    assert ebird_india.refresh(http, None, tmp_path) is None
