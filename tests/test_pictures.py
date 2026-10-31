"""Pictures for the species page (pipeline/pictures.py): a photo from India (the shortlist's corpus, iNaturalist
research grade), else iNaturalist's taxon photos, else the Wikimedia Commons image Wikidata names; each with its
credit and licence, never "all rights reserved"; and an English common name."""

import json

import duckdb
import pytest

from pipeline import pictures


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(pictures, "PAUSE", 0)


class Resp:
    def __init__(self, body):
        self.body, self.status_code, self.headers = body, 200, {}

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def inat_taxon(tid, name, common, photos):
    return {"id": tid, "name": name, "preferred_common_name": common,
            "taxon_photos": [{"photo": {"id": pid, "license_code": lic, "attribution": f"(c) {who}, some rights reserved",
                                        "medium_url": f"https://inat/{pid}.jpg"}} for pid, lic, who in photos]}


class FakeWeb:
    """Wikidata (SPARQL POST), iNaturalist taxa by id, and Commons imageinfo."""

    def __init__(self):
        self.calls = []
        self.wd = {"K1": {"img": "http://commons.wikimedia.org/wiki/Special:FilePath/Aus%20bus.jpg", "inat": "11", "en": "Bushy aus"},
                   "K2": {"img": "http://commons.wikimedia.org/wiki/Special:FilePath/Cus%20dus.jpg", "en": "Cus dus"},
                   "K3": {"inat": "33"}}
        self.by_name = {"Gus hus": [{"inat": "11", "en": "Hus gus"}],                  # by scientific name (P225)
                        "Ius jus": [{"en": "One"}, {"en": "Other"}],                     # two items: not used
                        "Kus lus": [{"en": "Kus lus", "cn": "Little kus"}],              # a taxon common name (P1843)
                        "Mus nus": [{"en": "Mus olus", "tn": "Mus olus"}]}               # the label is a Latin name
        self.inat = {"11": inat_taxon(11, "Aus bus", "Common Aus", [(1, None, "A"), (2, "cc-by-nc", "B")]),
                     "33": inat_taxon(33, "Eus fus", None, [(3, None, "C")])}

    def post(self, url, data=None, **kw):
        q = data["query"]
        self.calls.append(("wikidata", q))
        found = self.by_name if "wdt:P225 ?v" in q else {k: [v] for k, v in self.wd.items()}
        rows = []
        for k, items in found.items():
            if f'"{k}"' in q:
                rows += [{"v": {"value": k}, "item": {"value": f"Q{k}{i}"}, **{f: {"value": x} for f, x in v.items()}}
                         for i, v in enumerate(items)]
        return Resp({"results": {"bindings": rows}})

    def get(self, url, params=None, **kw):
        if "inaturalist" in url:
            ids = url.rsplit("/", 1)[1].split(",")
            self.calls.append(("inat", ids))
            return Resp({"results": [self.inat[i] for i in ids if i in self.inat]})
        titles = params["titles"].split("|")
        self.calls.append(("commons", titles))
        pages = {str(i): {"title": t, "imageinfo": [{"thumburl": f"https://up/{t}?utm_source=commons.wikimedia.org", "descriptionurl": f"https://commons/{t}",
                 "extmetadata": {"Artist": {"value": '<a href="x">Ann Bee</a>'}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}
                 for i, t in enumerate(titles)}
        return Resp({"query": {"pages": pages}})


def test_credits_are_cleaned_and_unknown_authors_left_out():
    assert pictures.clean_credit('<span>Ann <b>Bee</b></span>') == "Ann Bee"
    assert pictures.clean_credit("Unknown authorUnknown author") == ""
    assert pictures.clean_credit("The original uploader was Tabdulla at English Wikipedia.") == "Tabdulla"
    assert len(pictures.clean_credit("x" * 300)) <= 80


def test_the_first_inaturalist_photo_with_a_creative_commons_licence():
    t = inat_taxon(11, "Aus bus", "Common Aus", [(1, None, "A"), (2, "cc-by-nc", "B"), (3, "cc-by", "C")])
    p = pictures.inat_photo(t)
    assert p == ["https://inat/2.jpg", "https://www.inaturalist.org/photos/2", "B", "CC BY-NC", "iNaturalist"]
    assert pictures.inat_photo(inat_taxon(1, "X y", None, [(1, None, "A")])) is None


def test_refresh_asks_each_source_once_and_picks_india_then_inaturalist_then_commons(tmp_path):
    corpus = tmp_path / "corpus.csv"
    corpus.write_text("name,url,page,by,licence\nCus dus,https://open/9.jpg,https://www.inaturalist.org/observations/9,Dee,CC BY-NC\n")
    web = FakeWeb()
    rows = [("K1", "Aus bus"), ("K2", "Cus dus"), ("K3", "Eus fus"), ("K4", "Zus zus")]
    table = pictures.refresh(web, None, rows, corpus, cache=tmp_path / "c", today="2026-10-31")
    got = {r[0]: r[1:] for r in duckdb.sql(f"SELECT * FROM '{table}' ORDER BY key").fetchall()}
    assert got["K1"] == ("https://inat/2.jpg", "https://www.inaturalist.org/photos/2", "B", "CC BY-NC", "iNaturalist", "Common Aus")
    assert got["K2"][0] == "https://open/9.jpg" and got["K2"][4] == "iNaturalist (India)"   # a photo from India first
    assert got["K2"][5] is None                                                            # the label is the Latin name
    assert "K3" not in got                                     # only "all rights reserved", no common name
    assert "K4" not in got
    assert not any(c[0] == "commons" for c in web.calls)       # K1 and K2 have a photo: Commons is not asked
    n = len(web.calls)
    pictures.refresh(web, None, rows, corpus, cache=tmp_path / "c", today="2026-11-02")
    assert len(web.calls) == n                                 # a second run asks nothing


def test_commons_fills_in_when_nothing_else_has_a_photo(tmp_path):
    corpus = tmp_path / "corpus.csv"
    corpus.write_text("name,url,page,by,licence\n")
    web = FakeWeb()
    web.wd["K1"].pop("inat")
    table = pictures.refresh(web, None, [("K1", "Aus bus")], corpus, cache=tmp_path / "c", today="2026-10-31")
    (row,) = duckdb.sql(f"SELECT * FROM '{table}'").fetchall()
    # the thumbnail without Commons' tracking parameters
    assert row == ("K1", "https://up/File:Aus bus.jpg", "https://commons/File:Aus bus.jpg", "Ann Bee", "CC BY-SA 4.0",
                   "Wikimedia Commons", "Bushy aus")


def test_a_time_limit_stops_cleanly_and_keeps_what_it_has(tmp_path):
    corpus = tmp_path / "corpus.csv"
    corpus.write_text("name,url,page,by,licence\n")
    web = FakeWeb()
    pictures.refresh(web, None, [("K1", "Aus bus")], corpus, cache=tmp_path / "c", today="2026-10-31", deadline=0)
    assert web.calls == []
    assert json.loads((tmp_path / "c" / pictures.STORE).read_text()) == {"version": pictures.VERSION, "wikidata": {}, "byname": {}, "inat": {}, "commons": {}}


def test_the_corpus_table_takes_one_photo_per_species(tmp_path):
    con = duckdb.connect()
    corpus, photos = tmp_path / "corpus.parquet", tmp_path / "photos.parquet"
    con.sql(f"""COPY (SELECT * FROM (VALUES ('1', 'o1', 'Aus bus', 'x', 'y'), ('2', 'o2', 'Aus bus', 'x', 'y'), ('3', 'o3', 'Cus dus', 'x', 'y'))
                t(gbifID, obs_id, species, license, rightsHolder)) TO '{corpus}' (FORMAT parquet)""")   # the real corpus has both
    con.sql(f"""COPY (SELECT * FROM (VALUES
                ('1', 'https://open/1.jpg', 'http://creativecommons.org/licenses/by-nc/4.0/', 'Ann', 0),
                ('2', 'https://open/2.jpg', 'http://creativecommons.org/licenses/by/4.0/', 'Bo', 0),
                ('3', 'https://open/3.jpg', 'http://creativecommons.org/publicdomain/zero/1.0/', 'Cy', 1))
                t(gbifID, open_url, license, rightsHolder, position)) TO '{photos}' (FORMAT parquet)""")
    out = pictures.corpus_table(corpus, photos, tmp_path / "corpus.csv")
    rows = out.read_text().splitlines()
    assert rows[0] == "name,url,page,by,licence"
    assert "Aus bus,https://open/1.jpg,https://www.inaturalist.org/observations/o1,Ann,CC BY-NC 4.0" in rows
    assert "Cus dus,https://open/3.jpg,https://www.inaturalist.org/observations/o3,Cy,CC0 1.0" in rows


def test_a_busy_or_dropped_request_is_asked_again(monkeypatch):
    import requests
    monkeypatch.setattr(pictures.time, "sleep", lambda s: None)
    ok = Resp({"results": []})
    busy = Resp({})
    busy.status_code = 429
    answers = [requests.exceptions.ChunkedEncodingError("cut"), busy, ok]

    class Http:
        def get(self, *a, **k):
            x = answers.pop(0)
            if isinstance(x, Exception):
                raise x
            return x

    assert pictures.fetch(Http(), "https://x") is ok


def test_a_species_wikidata_lacks_by_its_catalogue_id_is_found_by_its_scientific_name(tmp_path):
    corpus = tmp_path / "corpus.csv"
    corpus.write_text("name,url,page,by,licence\n")
    web = FakeWeb()
    rows = [("K1", "Aus bus"), ("K4", "Gus hus"), ("K5", "Ius jus")]
    table = pictures.refresh(web, None, rows, corpus, cache=tmp_path / "c", today="2026-10-31")
    got = {r[0]: r[1:] for r in duckdb.sql(f"SELECT * FROM '{table}' ORDER BY key").fetchall()}
    assert got["K4"][0] == "https://inat/2.jpg" and got["K4"][5] == "Common Aus"
    assert "K5" not in got                                     # the name is on two Wikidata items
    named = [q for c, q in web.calls if c == "wikidata" and "wdt:P225 ?v" in q]
    assert len(named) == 1 and '"Aus bus"' not in named[0]      # only the keys the catalogue ID did not find
    n = len(web.calls)
    pictures.refresh(web, None, rows, corpus, cache=tmp_path / "c", today="2026-11-02")
    assert len(web.calls) == n


def test_wikidata_s_taxon_common_name_comes_before_its_label(tmp_path):
    corpus = tmp_path / "corpus.csv"
    corpus.write_text("name,url,page,by,licence\n")
    table = pictures.refresh(FakeWeb(), None, [("K6", "Kus lus")], corpus, cache=tmp_path / "c", today="2026-10-31")
    assert duckdb.sql(f"SELECT key, common FROM '{table}'").fetchall() == [("K6", "Little kus")]


def test_a_store_from_an_older_query_asks_wikidata_again(tmp_path):
    (tmp_path / "c").mkdir()
    old = {"wikidata": {"K6": ["2026-10-31", None, None, None]}, "byname": {"K6": ["2026-10-31", None, None, "Kus lus"]},
           "inat": {}, "commons": {}}
    (tmp_path / "c" / pictures.STORE).write_text(json.dumps(old))
    corpus = tmp_path / "corpus.csv"
    corpus.write_text("name,url,page,by,licence\n")
    table = pictures.refresh(FakeWeb(), None, [("K6", "Kus lus")], corpus, cache=tmp_path / "c", today="2026-11-01")
    assert duckdb.sql(f"SELECT common FROM '{table}'").fetchall() == [("Little kus",)]


def test_a_label_that_is_the_item_s_own_scientific_name_is_not_a_common_name(tmp_path):
    corpus = tmp_path / "corpus.csv"
    corpus.write_text("name,url,page,by,licence\n")
    table = pictures.refresh(FakeWeb(), None, [("K7", "Mus nus")], corpus, cache=tmp_path / "c", today="2026-10-31")
    assert duckdb.sql(f"SELECT * FROM '{table}'").fetchall() == []
