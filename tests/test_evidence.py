"""Evidence per species (pipeline/evidence.py): type specimens and photos from India and DNA barcodes anywhere (GBIF
facet counts), barcodes from India (BOLD), and names in Indian languages (Wikidata)."""

import json

import duckdb
import pytest

from pipeline import evidence


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(evidence, "PAUSE", 0)


class Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeGbif:
    """Occurrence search with facet paging: `keys` per filter, served `facetLimit` at a time."""

    def __init__(self, keys):
        self.keys, self.calls, self.raw = keys, [], []

    def get(self, url, params=None, **kw):
        self.raw.append(params)
        p = dict(params)
        self.calls.append(p)
        kind = ("barcodes" if p.get("datasetKey") else "photos" if p.get("mediaType") else "types")
        rows = self.keys[kind]
        off, lim = p["facetOffset"], p["facetLimit"]
        page = [{"name": k, "count": n} for k, n in rows[off:off + lim]]
        return Resp({"facets": [{"field": "SPECIES_KEY", "counts": page}]})


def test_facet_counts_pages_until_a_short_page():
    http = FakeGbif({"types": [("A", 2), ("B", 1), ("C", 4)]})
    assert evidence.facet_counts(http, [("typeStatus", "Holotype")], page=2) == {"A": 2, "B": 1, "C": 4}
    assert [c["facetOffset"] for c in http.calls] == [0, 2]
    assert all(c["checklistKey"] == evidence.COL_XR and c["limit"] == 0 for c in http.calls)


def test_gbif_counts_asks_each_kind_once_with_its_filter():
    http = FakeGbif({"types": [("A", 1)], "photos": [("A", 3), ("B", 1)], "barcodes": [("C", 9)]})
    got = evidence.gbif_counts(http)
    assert got == {"types": {"A": 1}, "photos": {"A": 3, "B": 1}, "barcodes": {"C": 9}}
    statuses = [v for k, v in http.raw[0] if k == "typeStatus"]
    assert "Holotype" in statuses and "NotAType" not in statuses
    assert all(c.get("country") == "IN" for c in http.calls if not c.get("datasetKey"))


def test_bold_keeps_species_names_only():
    data = {"species": {"Aus bus": 3, "Aus sp.": 2, "Bus cus dus": 1, "Cus sp. SAEVG Morph01": 1, "Dus eus": 1}}
    assert evidence.bold_names(data) == {"Aus bus": 3, "Bus cus dus": 1, "Dus eus": 1}


def binding(col, taxon, lang, label):
    b = {"col": {"value": col}, "lang": {"value": lang}, "l": {"value": label}}
    if taxon:
        b["taxon"] = {"value": taxon}
    return b


class FakeWikidata:
    def __init__(self, bindings, fail_on=None, fails=0):
        self.bindings, self.queries, self.fail_on, self.fails = bindings, [], fail_on, fails

    def post(self, url, data=None, **kw):
        import requests
        q = data["query"]
        self.queries.append(q)
        if self.fails:
            self.fails -= 1
            raise requests.exceptions.HTTPError("502 Server Error")
        if self.fail_on and self.fail_on in q:
            raise requests.exceptions.ConnectionError("down")
        return Resp({"results": {"bindings": [b for b in self.bindings if f'"{b["col"]["value"]}"' in q]}})


def test_wikidata_names_leave_out_the_scientific_name_and_repeats():
    w = FakeWikidata([binding("K1", "Aus bus", "hi", "मोर"), binding("K1", "Aus bus", "ta", "மயில்"),
                      binding("K1", "Aus bus", "hi", "मोर"), binding("K1", "Aus bus", "mr", "Aus bus"),
                      binding("K2", "Cus dus", "bn", "cus dus")])
    assert evidence.wikidata_batch(w, ["K1", "K2", "K3"]) == {"K1": [["hi", "मोर"], ["ta", "மயில்"]]}
    assert "P10585" in w.queries[0]


def test_wikidata_asks_only_new_or_old_keys_and_saves_as_it_goes():
    w = FakeWikidata([binding("K1", None, "hi", "एक"), binding("K3", None, "kn", "ಮೂರು")])
    cache = {"K2": ["2026-10-20", []], "K4": ["2026-01-01", [["hi", "पुराना"]]]}
    saves = []
    done = evidence.wikidata_names(w, ["K1", "K2", "K3", "K4"], cache, "2026-10-30", save=lambda: saves.append(1),
                                   batch=2)
    assert done and cache["K1"] == ["2026-10-30", [["hi", "एक"]]] and cache["K2"] == ["2026-10-20", []]
    assert cache["K4"] == ["2026-10-30", []]                     # asked again (older than MAX_AGE_DAYS)
    assert len(w.queries) == 2 and saves
    assert evidence.wikidata_names(w, ["K1", "K2", "K3", "K4"], cache, "2026-10-31") and len(w.queries) == 2


def test_wikidata_stops_at_the_deadline_and_keeps_what_it_has():
    w = FakeWikidata([binding("K1", None, "hi", "एक")])
    cache = {}
    assert not evidence.wikidata_names(w, ["K1", "K2"], cache, "2026-10-30", batch=1, deadline=0)
    assert cache == {} and w.queries == []


def test_table_has_one_row_per_key_with_any_evidence(tmp_path):
    counts = {"types": {"K1": 2}, "photos": {"K1": 5, "K2": 1}, "barcodes": {"K3": 4, "Z9": 1}}
    names = {"K2": ["2026-10-30", [["hi", "दो"]]], "K4": ["2026-10-30", []]}
    path = evidence.write_table(counts, names, tmp_path / "species.parquet")
    rows = {r[0]: r[1:] for r in duckdb.sql(f"SELECT key, types, photos, barcodes, names FROM '{path}' ORDER BY key").fetchall()}
    assert rows["K1"] == (2, 5, None, None)
    assert rows["K2"] == (None, 1, None, [{"lang": "hi", "name": "दो"}])
    assert rows["K3"][2] == 4 and "K4" not in rows


def test_refresh_reuses_the_weeks_counts_and_keeps_copies_in_r2(tmp_path, monkeypatch):
    from tests.r2_fake import FakeS3
    monkeypatch.setenv("R2_BUCKET", "b")
    monkeypatch.setattr(evidence, "period", lambda: "2026-10-26")
    gbif = FakeGbif({"types": [("K1", 1)], "photos": [], "barcodes": []})
    bold = {"species": {"Aus bus": 2}}
    wd = FakeWikidata([binding("K1", None, "hi", "एक")])

    class Http:
        def get(self, url, params=None, **kw):
            return Resp(bold) if "boldsystems" in url else gbif.get(url, params, **kw)

        post = wd.post

    s3 = FakeS3()
    table, bold_csv = evidence.refresh(Http(), s3, ["K1"], tmp_path / "a", today="2026-10-30")
    assert duckdb.sql(f"SELECT key, types FROM '{table}'").fetchall() == [("K1", 1)]
    assert bold_csv.read_text().splitlines() == ["name,n", "Aus bus,2"]
    assert {evidence.R2_DIR + n for n in ("counts.json", "wikidata.json", "species.parquet", "bold_india.csv")} <= set(s3.store)
    n = len(gbif.calls)
    evidence.refresh(Http(), s3, ["K1"], tmp_path / "b", today="2026-10-30")   # a new machine: R2's copies
    assert len(gbif.calls) == n and len(wd.queries) == 1
    assert json.loads((tmp_path / "b" / "counts.json").read_text())["period"] == "2026-10-26"


def test_wikidata_asks_again_after_a_server_error_and_stops_cleanly_when_it_stays_down(monkeypatch):
    monkeypatch.setattr(evidence.time, "sleep", lambda s: None)
    w = FakeWikidata([binding("K1", None, "hi", "एक")], fails=2)
    cache = {}
    assert evidence.wikidata_names(w, ["K1"], cache, "2026-10-30") and cache["K1"][1] == [["hi", "एक"]]
    w = FakeWikidata([binding("K1", None, "hi", "एक")], fail_on='"K2"')
    cache = {}
    assert not evidence.wikidata_names(w, ["K1", "K2"], cache, "2026-10-30", batch=1)
    assert list(cache) == ["K1"]                          # kept; K2 is asked by the next run
