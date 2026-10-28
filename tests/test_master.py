"""Master list: matching, flags, labels and the site files, on small synthetic inputs."""

import json
import threading
import time

import duckdb
import pytest

from pipeline import layer_newspecies, master
from pipeline.groups import GROUPS


def write(con, sql, path):
    con.sql(f"COPY ({sql}) TO '{path}' (FORMAT parquet)")
    return path


@pytest.fixture
def inputs(tmp_path):
    con = duckdb.connect()
    sp = write(con, """SELECT * FROM (VALUES
        ('K1', 'Aus bus', 'Animalia', 'Chordata', 'Aves', 'Passeriformes', 'Muscicapidae', 'Aus'),
        ('K2', 'Cus dus', 'Plantae', 'Tracheophyta', 'Liliopsida', 'Asparagales', 'Orchidaceae', 'Cus'),
        ('K3', 'Eus fus', 'Animalia', 'Arthropoda', 'Insecta', 'Coleoptera', 'Carabidae', 'Eus'),
        ('G1', 'Hus ius', 'Animalia', 'Chordata', 'Aves', 'Passeriformes', 'Muscicapidae', 'Hus')
        ) t(species_key, name, kingdom, phylum, class, "order", family, genus)""", tmp_path / "species.parquet")
    dec = write(con, """SELECT * FROM (VALUES ('K1', 2010, 'HUMAN_OBSERVATION', 5), ('K2', 1900, 'PRESERVED_SPECIMEN', 1),
        ('K3', 2010, 'MATERIAL_SAMPLE', 2), ('G1', 2000, 'HUMAN_OBSERVATION', 1)) t(species_key, decade, basis, n_records)""",
                tmp_path / "species_decade.parquet")
    led = write(con, """SELECT * FROM (VALUES ('K1', 101, 32, 2010, 2015, 5), ('K2', 201, 29, 1900, 1900, 1),
        ('K3', 101, 32, 2011, 2011, 2), ('G1', 101, 32, 2000, 2000, 1))
        t(species_key, district_lgd, state_lgd, first_year, last_year, n_records)""", tmp_path / "ledger.parquet")
    zsi = tmp_path / "zsi.csv"
    zsi.write_text(
        "checklist,family,name,rank,authority,mark,col_accepted_id,col_accepted_name,col_family,match_type,needs_review\n"
        "120_Aves.pdf,Muscicapidae,Aus bus,species,\"Smith, 1801\",*,K1,Aus bus,Muscicapidae,exact,false\n"
        "120_Aves.pdf,Muscicapidae,Aus bus minor,subspecies,,,K1x,Aus bus minor,Muscicapidae,exact,false\n"
        "120_Aves.pdf,Muscicapidae,Gus hus,species,\"Smith, 2019\",,K4,Gus hus,Muscicapidae,exact,false\n"
        "120_Aves.pdf,Muscicapidae,Hus ius,species,\"Jones, 1850\",,Z1,Hus ius,Muscicapidae,exact,false\n"
        "108_Insecta_Coleoptera.pdf,Unknownidae,Xus (Yus) yus,species,,,,,,none,false\n"
        "120_Aves.pdf,Muscicapidae,Qus rus,species,\"Brown, 1920\",,K7,,,exact,false\n")  # no accepted name given
    bsi = tmp_path / "bsi.csv"
    bsi.write_text("source,checklist,group,family,name,rank,authority,status,states,page,edition,url\n"
                   "BSI,FPI,flowering plants,Orchidaceae,Cus dus,species,L.,accepted,Kerala,1,e,u\n"
                   "BSI,FPI,flowering plants,Orchidaceae,Old dus,species,L.,synonym,,1,e,u\n"
                   "BSI,FPI,pteridophytes,Pteridaceae,Pus qus var. minor,variety,L.,accepted,,2,e,u\n")
    wcvp = write(con, """SELECT * FROM (VALUES ('Cus dus', 'Orchidaceae', 'Cus', true), ('Wus vus', 'Orchidaceae', 'Wus', false))
        t(species, family, genus, endemic_india)""", tmp_path / "wcvp.parquet")
    dist = write(con, """SELECT * FROM (VALUES (101, 32, 'ERNAKULAM', 'KERALA'), (201, 29, 'MYSURU', 'KARNATAKA'))
        t(dist_lgd, state_lgd, dtname, stname)""", tmp_path / "districts.parquet")
    inat_doc = {"complete": True, "places": {"india": 6681, "32": 7, "29": 8},
                "lists": {"32": {"research": [[1, "Aus bus", "Aves", 3]],
                                 "needs_id": [[31, "Hus ius minor", "Aves", 2], [3, "Hus ius", "Aves", 4]]},
                          "29": {"research": [], "needs_id": [[2, "Zus zus", "Aves", 1]]},
                          "india": {"research": [[1, "Aus bus", "Aves", 3], [4, "Hia ius", "Aves", 1]],
                                    "needs_id": [[2, "Zus zus", "Aves", 1], [3, "Hus ius", "Aves", 6]]}}}
    ns_doc = layer_newspecies.compact([{"name": "Gus hus", "year": 2020, "sources": ["Plazi"], "journal": "J",
                                         "state": "", "link": "https://x/1", "group": "Birds", "key": "K4",
                                         "matched_by": "exact name", "status": "none", "latest_after": None,
                                         "any_record": False},
                                        {"name": "Qus rus", "year": 2015, "sources": ["ZSI Animal Discoveries"], "journal": "",
                                         "state": "", "link": "https://x/2", "group": "Birds", "key": "K7",
                                         "matched_by": "exact name", "status": "none", "latest_after": None,
                                         "any_record": True},
                                        {"name": "Wus xus", "year": 2021, "sources": ["Plazi"], "journal": "J",
                                         "state": "", "link": "https://x/3", "group": "Birds", "key": None,
                                         "matched_by": "name as published in GBIF", "status": "recorded",
                                         "latest_after": 2023, "any_record": True}])
    col = write(con, """SELECT * FROM (VALUES ('K1', 1758, '(Linnaeus, 1758)'), ('K2', NULL, '(L.) DC.'),
        ('G1', 1849, 'Moore, 1849')) t(id, year, authority)""", tmp_path / "col_years.parquet")
    wcvp_y = write(con, """SELECT * FROM (VALUES ('Cus dus', 1753, '(L.) DC.'), ('Aus bus', 1700, 'X'))
        t(name, year, authority)""", tmp_path / "wcvp_years.parquet")
    return {"paths": {"species": sp, "species_decade": dec, "ledger": led, "unlocated": None},
            "inputs": {"zsi": zsi, "wcvp": wcvp, "bsi": bsi, "inat": inat_doc, "newspecies": ns_doc,
                       "described": {"col": col, "wcvp": wcvp_y},
                       "inat_genus": {"lists": {"32": [[50, "Hus", "Aves", 3]],
                                                "india": [[50, "Hus", "Aves", 5], [60, "Nus", "Insecta", 2],
                                                          [55, "Hia", "Aves", 1], [56, "Hus", "Plantae", 2]]}},
                       "inat_coarse": {"counts": {"32": {"Aves": 4}, "india": {"Aves": 9, "Insecta": 1}}}},
            "districts": dist}


class Resp:
    def __init__(self, data):
        self.data, self.ok = data, True

    def json(self):
        return self.data


class FakeGbif:
    """GBIF v2 match: 'Wus vus' matches K5, 'Hia ius' (an older name) matches G1 (Hus ius); else no exact match."""

    def __init__(self):
        self.headers, self.asked = {}, []

    def get(self, url, params=None, **kw):
        self.asked.append(params["scientificName"])
        if params["scientificName"] == "Wus vus":
            return Resp({"usage": {"key": "K5", "name": "Wus vus L.", "canonicalName": "Wus vus"},
                         "classification": [{"rank": "KINGDOM", "name": "Plantae"}, {"rank": "PHYLUM", "name": "Tracheophyta"},
                                            {"rank": "FAMILY", "name": "Orchidaceae"}],
                         "diagnostics": {"matchType": "EXACT"}})
        if params["scientificName"] == "Hia ius":
            return Resp({"usage": {"key": "G1", "name": "Hus ius L.", "canonicalName": "Hus ius"},
                         "classification": [{"rank": "KINGDOM", "name": "Animalia"}],
                         "diagnostics": {"matchType": "EXACT"}})
        return Resp({"diagnostics": {"matchType": "NONE"}})


def iucn_table(con):
    con.sql("""CREATE TABLE iucn AS SELECT * FROM (VALUES
        ('Aus bus', 'EN', true, '1', 'Animalia', 'Chordata', 'Aves', 'Passeriformes', 'Muscicapidae'),
        ('Cus dus', 'VU', false, '2', 'Plantae', 'Tracheophyta', 'Liliopsida', 'Asparagales', 'Orchidaceae'))
        t(name, category, accepted, iucn_id, kingdom, phylum, class, "order", family)""")


@pytest.fixture
def built(inputs, tmp_path, monkeypatch):
    monkeypatch.setattr(layer_newspecies.time, "sleep", lambda s: None)
    monkeypatch.setattr(master, "CACHE", tmp_path / "cache")
    con = duckdb.connect()
    iucn_table(con)
    http = FakeGbif()
    out = tmp_path / "out"
    summary = master.build(con, inputs["paths"], out, {"period": "2026-10", "snapshot": "2026-10", "built": "x"},
                           inputs["districts"], inputs["inputs"], cache={}, http=http)
    rows = {r[1]: dict(zip(["key", "name", "group", "sources", "observed", "iucn", "labels", "states_observed"], r))
            for r in duckdb.sql(f"SELECT * FROM '{out / 'master.parquet'}'").fetchall()}
    return {"summary": summary, "rows": rows, "out": out, "http": http}


def test_documented_and_with_an_open_record(built):
    """An open record: any GBIF record, or an iNaturalist research-grade observation. A needs-ID observation is not
    one: it waits for a name. A species named only in needs-ID observations is not on the list (it still waits)."""
    t = built["summary"]["totals"]
    assert t == {"documented": 10, "observed": 5}   # Wus xus: a record under the name as published
    assert built["rows"]["Qus rus"]["key"] == "K7"
    r = built["rows"]
    assert r["Aus bus"]["observed"] and r["Aus bus"]["states_observed"] == [32]
    assert r["Hus ius"]["states_observed"] == [32]    # GBIF; its needs-ID observations add nothing
    assert "Zus zus" not in r                        # only needs ID
    assert not r["Gus hus"]["observed"]
    assert set(r["Aus bus"]) == {"key", "name", "group", "sources", "observed", "iucn", "labels", "states_observed"}


def test_sources_and_labels(built):
    r = built["rows"]
    assert r["Aus bus"]["sources"] == ["ZSI", "GBIF", "iNaturalist", "IUCN"]
    assert r["Aus bus"]["labels"] == ["rg", "ho", "end"]
    assert r["Cus dus"]["sources"] == ["BSI", "WCVP", "GBIF", "IUCN"]
    assert "Old dus" not in r and r["Pus qus"]["group"] == "Plants: ferns & lycophytes" and r["Cus dus"]["labels"] == ["sp", "end"]
    assert r["Eus fus"]["labels"] == ["dna", "do"]
    assert r["Gus hus"]["sources"] == ["ZSI", "Plazi"] and r["Gus hus"]["labels"] == ["chk", "nra"]


def test_iucn_by_name_and_synonym(built):
    r = built["rows"]
    assert r["Aus bus"]["iucn"] == "EN"
    assert r["Cus dus"]["iucn"] == "VU"       # through an IUCN synonym
    assert r["Eus fus"]["iucn"] == "NE"


def test_names_matched_or_kept(built):
    r = built["rows"]
    assert r["Wus vus"]["key"] == "K5"                       # GBIF match
    assert r["Xus yus"]["key"] is None and "nm" in r["Xus yus"]["labels"]   # kept, subgenus dropped
    assert r["Hus ius"]["key"] == "G1"                       # ZSI's key folded into GBIF's for the same name
    assert "Aus bus minor" not in r                          # subspecies counted as its species
    assert built["http"].asked == ["Hia ius", "Zus zus", "Wus vus", "Pus qus"]  # iNaturalist, WCVP, BSI; never ZSI
    assert "Hia ius" not in r                                # an older name of Hus ius


def test_groups_from_classification_or_hints(built):
    r = built["rows"]
    assert r["Cus dus"]["group"] == r["Wus vus"]["group"] == "Plants: orchids"
    assert r["Xus yus"]["group"] == "Insects: beetles"      # from the ZSI checklist name
    assert r["Gus hus"]["group"] == "Birds"


def test_site_files(built):
    out, s = built["out"], built["summary"]
    birds = GROUPS.index("Birds")
    # [documented, with an open record, [species per IUCN category], threatened with an open record]
    assert s["india"][birds][:2] == [5, 3]                   # Aus, Gus, Hus, Qus, Wus xus; Aus, Hus, Wus xus
    assert s["india"][birds][2][s["iucn"].index("EN")] == 1 and s["india"][birds][3] == 1
    assert [st["code"] for st in s["states"]] == ["29", "32"]
    assert {"licence", "attribution", "disclaimer"} <= set(s)
    assert s["by_state"]["29"][birds] == [0, 0]              # Zus zus: needs ID only
    assert s["by_state"]["32"][birds] == [2, 1]
    labels = [lab["code"] for lab in s["labels"]]
    g = json.loads((out / "g" / f"{birds}.json").read_text())["rows"]
    aus = next(x for x in g if x[1] == "Aus bus")
    assert aus[0] == "K1" and aus[3] == 1 and aus[6] == 1 << 1      # an open record in state index 1 (32)
    assert aus[7] == 1758 and len(aus) == 8                         # year described
    assert "Zus zus" not in {x[1] for x in g}
    assert aus[5] & (1 << labels.index("end")) and aus[2] == 0b1011001  # ZSI, GBIF, iNaturalist, IUCN
    search = json.loads((out / "search" / "au.json").read_text())["rows"]
    assert search == [["Aus bus", "K1", birds, 1, 1, aus[2], aus[5], 1758]]
    zus = json.loads((out / "search" / "zu.json").read_text())["rows"]
    assert [z[:4] for z in zus] == [["Zus zus", "", birds, 2]]     # status 2: waits for a name, not on the list
    assert json.loads((out / "search" / "xu.json").read_text())["rows"][0][1] == ""
    places = json.loads((out / "search" / "places.json").read_text())["rows"]
    assert ["Kerala", "state", 32, 32] in places and ["Mysuru", "district", 201, 29] in places


def test_waiting_for_a_name(built):
    """iNaturalist needs-ID species per area: counts per group, and a file per group with the taxon to identify."""
    out, w = built["out"], built["summary"]["waiting"]
    birds = GROUPS.index("Birds")
    assert w["places"] == {"india": 6681, "32": 7, "29": 8}
    # [species waiting, observations waiting, species with no open record in that area]
    assert w["india"][birds] == [2, 7, 1]           # Zus zus (never identified) and Hus ius
    assert w["by_state"]["29"][birds] == [1, 1, 1]
    assert w["by_state"]["32"][birds] == [1, 6, 0]  # Hus ius and its subspecies; a GBIF record in Kerala
    rows = json.loads((out / "w" / f"{birds}.json").read_text())["rows"]
    g = {r[1]: r for r in json.loads((out / "g" / f"{birds}.json").read_text())["rows"]}
    # The species' g row (with the year), then iNaturalist taxon (the species, not a subspecies), observations in India,
    # [[state index, n]]. Zus zus is on no list (status 2), but its observations still wait.
    assert rows[0][:8] == g["Hus ius"]
    assert rows[1][1] == "Zus zus" and rows[1][3] == 2 and rows[1][6] == 0
    assert [r[8:] for r in rows] == [[3, 6, [[1, 6]]], [2, 1, [[0, 1]]]]


def test_waiting_at_genus_and_above(built):
    """Observations named only to genus: per genus, with what the list knows of the genus in India.
    Observations named only above genus: counts per area and iNaturalist iconic group."""
    out, w = built["out"], built["summary"]["waiting"]
    birds, other = GROUPS.index("Birds"), GROUPS.index("Insects: other")
    assert w["genus"]["india"][birds] == [2, 6] and w["genus"]["india"][other] == [1, 2]
    assert w["genus"]["by_state"]["32"][birds] == [1, 3]
    assert w["coarse"] == {"india": {"Aves": 9, "Insecta": 1}, "by_state": {"32": {"Aves": 4}}}
    # [genus, iNaturalist taxon, observations in India, [[state index, n]], species of the genus on the list,
    #  of them with no open record, threatened, endemic]
    rows = json.loads((out / "wg" / f"{birds}.json").read_text())["rows"]
    # Hia: the genus of an older name of Hus ius, still known to the list through that name.
    assert rows == [["Hia", 55, 1, [], 1, 0, 0, 0], ["Hus", 50, 5, [[1, 3]], 1, 0, 0, 0]]
    assert json.loads((out / "wg" / f"{other}.json").read_text())["rows"] == [["Nus", 60, 2, [], 0, 0, 0, 0]]
    # A plant genus spelled like the bird genus Hus: not counted with the birds.
    plants = GROUPS.index("Plants: other flowering plants & conifers")
    assert json.loads((out / "wg" / f"{plants}.json").read_text())["rows"] == [["Hus", 56, 2, [], 0, 0, 0, 0]]


def test_species_files(built):
    """sp/<shard>.json: one object per species key, for the species page."""
    from pipeline import site_data
    out = built["out"]
    birds = GROUPS.index("Birds")
    g = {r[1]: r for r in json.loads((out / "g" / f"{birds}.json").read_text())["rows"]}
    part = json.loads((out / "sp" / f"{site_data.shard_of('G1')}.json").read_text())
    # [name, group index, sources, status, IUCN, labels, states with an open record,
    #  iNaturalist taxon, observations waiting in India, [[state index, n]], year described, authority,
    #  the paper for a new species: [sources, journal, link, after the description, latest year after]]
    assert part["G1"] == [g["Hus ius"][1], birds, *g["Hus ius"][2:7], 3, 6, [[1, 6]], 1849, "Moore, 1849", None]
    gus = json.loads((out / "sp" / f"{site_data.shard_of('K4')}.json").read_text())["K4"]
    assert gus[0] == "Gus hus" and gus[7:10] == [None, 0, []]          # nothing waits
    assert gus[10:] == [2020, "Smith, 2019", [["Plazi"], "J", "https://x/1", "none", None, 2020]]
    assert all("" not in json.loads(p.read_text()) for p in (out / "sp").iterdir())  # unmatched names have no page
    assert not (out / "ns.json").exists()


def test_year_described_from_the_first_source_that_has_one(built):
    """The paper of a new species, then Catalogue of Life, then the ZSI authority, then WCVP (plants only)."""
    years = dict(duckdb.sql(f"SELECT name, year FROM '{built['out'] / 'master.parquet'}'").fetchall())
    assert years["Gus hus"] == 2020        # the paper; ZSI says 2019, close enough
    assert years["Hus ius"] == 1849        # Catalogue of Life, over ZSI's 1850
    assert years["Aus bus"] == 1758        # Catalogue of Life; WCVP is not asked for an animal
    assert years["Qus rus"] == 1920        # ZSI authority, over a paper of 2015: an older name listed as new
    labels = dict(duckdb.sql(f"SELECT name, labels FROM '{built['out'] / 'master.parquet'}'").fetchall())
    assert "nra" in labels["Gus hus"]      # no record since the description
    assert "nra" not in labels["Qus rus"]  # listed in 2015 but described in 1920: records since 1920 are not checked
    assert years["Cus dus"] == 1753        # WCVP: Catalogue of Life gives no year for this plant
    assert years["Eus fus"] is None
    d = built["summary"]["described"]
    assert d["from"] == 1753 and d["to"] == 2021 and d["unknown"] == 4   # Wus xus: its paper, 2021


def test_prefix():
    assert master.prefix("Aus bus") == "au" and master.prefix("×Cus") == "_c" and master.prefix("A") == "a_"


def test_second_run_asks_nothing(inputs, built, tmp_path):
    con = duckdb.connect()
    iucn_table(con)
    cache = json.loads((tmp_path / "cache" / "gbif_match.json").read_text())
    http = FakeGbif()
    master.build(con, inputs["paths"], tmp_path / "out2", {"period": "m", "snapshot": "s", "built": "x"},
                 inputs["districts"], inputs["inputs"], cache=cache, http=http)
    assert http.asked == []


def test_match_stops_at_deadline(inputs, tmp_path, monkeypatch):
    monkeypatch.setattr(master, "CACHE", tmp_path / "cache")
    con = duckdb.connect()
    iucn_table(con)
    http = FakeGbif()
    s = master.build(con, inputs["paths"], tmp_path / "o", {"period": "m", "snapshot": "s", "built": "x"},
                     inputs["districts"], inputs["inputs"], cache={}, http=http, deadline=0)
    assert http.asked == [] and s["names_pending_match"] == 4
    assert any("not yet matched" in n for n in s["notes"])


def test_iucn_parse(tmp_path):
    from pipeline import iucn
    (tmp_path / "taxon.txt").write_text(
        "1\tAus bus L.\tANIMALIA\tCHORDATA\tAVES\tPASSERIFORMES\tMUSCICAPIDAE\tAus\tbus\tL.\tspecies\t\taccepted\t1\tc\tr\n"
        "9\tAus cus L.\t\t\t\t\t\t\t\t\t\t\tsynonym\t1\t\t\n"
        "8\tAus bus minor L.\t\t\t\t\t\t\t\t\t\t\tsynonym\t1\t\t\n")
    (tmp_path / "distribution.txt").write_text("1\t\tGlobal\tc\t\tLower Risk/near threatened\tPresent\n"
                                               .replace("Lower Risk/near threatened", "near threatened"))
    con = duckdb.connect()
    iucn.parse(con, tmp_path, tmp_path / "iucn.parquet")
    rows = con.sql("SELECT name, category, accepted, kingdom, class FROM iucn ORDER BY name").fetchall()
    assert rows == [("Aus bus", "NT", True, "Animalia", "Aves"), ("Aus cus", "NT", False, "Animalia", "Aves")]


def test_match_survives_a_timeout(tmp_path, monkeypatch):
    import requests
    monkeypatch.setattr(master, "CACHE", tmp_path)
    monkeypatch.setattr(master, "BACKOFF", 0)
    monkeypatch.setattr(layer_newspecies.time, "sleep", lambda s: None)

    class Flaky(FakeGbif):
        def get(self, url, params=None, **kw):
            if params["scientificName"] == "Bad name" and "Bad name" not in self.asked:
                self.asked.append("Bad name")
                raise requests.ReadTimeout("slow")
            return super().get(url, params=params, **kw)

    cache, http = {}, Flaky()
    assert master.match_names(["Bad name", "Wus vus"], cache, None, http=http) == 2
    assert cache["Wus vus"]["key"] == "K5" and cache["Bad name"] is None   # tried again after the pause
    monkeypatch.setattr(master, "RETRIES", 1)

    class Down(FakeGbif):
        def get(self, url, params=None, **kw):
            self.asked.append(params["scientificName"])
            raise requests.ConnectionError("down")

    down = Down()
    cache = {}
    assert master.match_names(["A b", "C d"], cache, None, http=down) == 0 and cache == {}  # asked again next run


def test_match_runs_a_few_requests_at_once(tmp_path, monkeypatch):
    monkeypatch.setattr(master, "CACHE", tmp_path)
    monkeypatch.setattr(layer_newspecies.time, "sleep", lambda s: None)

    class Slow(FakeGbif):
        def __init__(self):
            super().__init__()
            self.lock, self.now, self.most = threading.Lock(), 0, 0

        def get(self, url, params=None, **kw):
            with self.lock:
                self.now += 1
                self.most = max(self.most, self.now)
                self.asked.append(params["scientificName"])
            threading.Event().wait(0.05)  # time.sleep is patched out
            with self.lock:
                self.now -= 1
                self.asked.pop()
            return super().get(url, params=params, **kw)

    names = [f"Aus n{i}" for i in range(12)] + ["Wus vus"]
    cache = {"Aus n0": None}                       # already asked: skipped
    http = Slow()
    assert master.match_names(names, cache, None, http=http) == 12
    assert 1 < http.most <= master.WORKERS
    assert "Aus n0" not in http.asked and cache["Wus vus"]["key"] == "K5" and len(cache) == 13
    assert len(json.loads((tmp_path / "gbif_match.json").read_text())) == 13


def test_match_stops_at_deadline_with_workers(tmp_path, monkeypatch):
    monkeypatch.setattr(master, "CACHE", tmp_path)
    http = FakeGbif()
    assert master.match_names(["A b", "C d"], {}, None, deadline=time.monotonic() - 1, http=http) == 0
    assert http.asked == []


def test_changes_between_weeks(tmp_path):
    """Species that moved since the last list: added, a first open record in India or in a state, dropped."""
    con = duckdb.connect()
    g0, g1 = GROUPS[0], GROUPS[1]
    con.sql(f"""CREATE TABLE prev AS SELECT * FROM (VALUES
        ('K1', 'Aus bus', '{g0}', ['ZSI'], false, []::INTEGER[], ['chk']),
        ('K3', 'Cus dus', '{g1}', ['GBIF'], true, [32], ['ho']),
        ('K4', 'Dus eus', '{g1}', ['GBIF'], true, [32], ['ho']),
        (NULL, 'Old name', '{g1}', ['ZSI'], false, []::INTEGER[], ['chk', 'nm']))
        t(key, name, "group", sources, observed, states_observed, labels)""")  # as in master.parquet
    prev = tmp_path / "prev.parquet"
    con.sql(f"COPY prev TO '{prev}' (FORMAT parquet)")
    con.sql("""CREATE TABLE master AS SELECT * FROM (VALUES
        ('K1', 'Aus bus', 0, ['ZSI', 'GBIF'], true, [29], 1),
        ('K3', 'Cus dus', 1, ['GBIF'], true, [29, 32], 1),
        ('K4', 'Dus eus', 1, ['GBIF'], true, [32], 1),
        ('K5', 'Eus fus', 1, ['BSI'], false, []::INTEGER[], 0),
        (NULL, 'Fus gus', 1, ['iNaturalist'], false, []::INTEGER[], 2))
        t(key, name, gi, sources, observed, states_observed, status)""")
    ch = master.changes(con, prev, "2026-10-26", "2026-11-02", n_groups=2)
    assert ch["from"] == "2026-10-26" and ch["to"] == "2026-11-02"
    assert ch["counts"] == {"observed": 1, "state": 1, "documented": 1, "dropped": 1, "iucn": 0}
    # per group: [added, first open record in India, first open record in a state]
    assert ch["groups"] == [[0, 1, 0], [1, 0, 1]]
    assert sorted(ch["rows"]) == sorted([          # Fus gus waits for a name: not on the list, so not added
        ["observed", "K1", "Aus bus", 0, [29], ["GBIF"]],
        ["state", "K3", "Cus dus", 1, [29], []],
        ["documented", "K5", "Eus fus", 1, [], ["BSI"]],
        ["dropped", "", "Old name", 1, [], []]])
    assert master.changes(con, None, None, "2026-11-02", n_groups=2) == {"from": None, "to": "2026-11-02"}


def test_a_list_from_before_open_records_is_compared_by_the_same_rule(tmp_path):
    """Lists up to 2026-10-26 counted needs-ID observations as observed. Read with today's rule: a species known
    only from them was not on the list, and observed meant identified (or a record under the name as published)."""
    con = duckdb.connect()
    g0 = GROUPS[0]
    con.sql(f"""CREATE TABLE prev AS SELECT * FROM (VALUES
        ('K1', 'Aus bus', '{g0}', ['iNaturalist', 'IUCN'], true, false, [32], []::INTEGER[], ['nid'], 'EN'),
        ('K2', 'Bus cus', '{g0}', ['ZSI', 'iNaturalist'], true, false, [32], []::INTEGER[], ['nid'], 'LC'),
        ('K3', 'Cus dus', '{g0}', ['GBIF', 'iNaturalist'], true, true, [29, 32], [29], ['ho', 'nid'], 'VU'),
        ('K4', 'Dus eus', '{g0}', ['ZSI', 'GBIF'], true, false, []::INTEGER[], []::INTEGER[], ['vn'], 'NE'))
        t(key, name, "group", sources, observed, identified, states_observed, states_identified, labels, iucn)""")
    prev = tmp_path / "old.parquet"
    con.sql(f"COPY prev TO '{prev}' (FORMAT parquet)")
    assert sorted(con.sql(f"SELECT key, observed, states_observed FROM ({master.previous_list(con, prev)})").fetchall()) == [
        ("K2", False, []), ("K3", True, [29]), ("K4", True, [])]
    con.sql("""CREATE TABLE master AS SELECT * FROM (VALUES
        ('K2', 'Bus cus', 0, ['ZSI', 'iNaturalist'], false, []::INTEGER[], 0, 'LC'),
        ('K3', 'Cus dus', 0, ['GBIF', 'iNaturalist'], true, [29], 1, 'VU'),
        ('K4', 'Dus eus', 0, ['ZSI', 'GBIF'], true, []::INTEGER[], 1, 'NE'))
        t(key, name, gi, sources, observed, states_observed, status, iucn)""")
    ch = master.changes(con, prev, "2026-10-26", "2026-10-26", n_groups=1)
    assert ch["counts"] == dict.fromkeys(master.CHANGE_KINDS, 0)   # nothing moved; Aus bus was never on the list
    s = master.previous_summary(con, {"parquet": prev, "summary": summary_for("2026-10-26", [4, 0], [4, 0], [1, 0],
                                                                                 [{}, {}], [2, 0], [9, 0])})
    assert s["india"][0][:2] == [3, 2] and s["india"][0][3] == 1   # documented, open record, threatened (Cus dus)
    assert s["waiting"] == {"india": [[2, 9, 0], [0, 0, 0]]} and s["period"] == "2026-10-26"
    assert master.history_entry(s)["india"] == [3, 2, 1, 2, 9]


def test_first_month_has_no_changes(built):
    assert json.loads((built["out"] / "changes.json").read_text()) == {"from": None, "to": "2026-10"}


def test_previous_period_is_the_list_published_before_this_one():
    """The list to compare with is the one latest.json names, or the one it names as previous when this week
    is already published (a second run in the same week). The switch from monthly to weekly needs no gap."""
    prev = master.previous_period
    assert prev(None, "2026-10-26") is None
    assert prev({"month": "2026-10"}, "2026-10-26") == "2026-10"                      # last monthly list
    assert prev({"period": "2026-10-26", "previous": "2026-10"}, "2026-10-26") == "2026-10"
    assert prev({"period": "2026-10-26"}, "2026-11-02") == "2026-10-26"
    assert prev({"period": "2026-11-02"}, "2026-10-26") is None                       # never a later list


def test_new_species_from_every_source_and_the_whole_window():
    """Every name the new-species layer gives (ZSI Animal Discoveries too) is documented, labelled new from the
    layer's first year."""
    con = duckdb.connect()
    master.start(con)
    row = {"journal": "J", "state": "", "link": "https://x/1", "group": "Birds", "matched_by": "exact name",
           "status": "none", "latest_after": None, "any_record": False}
    master.load_newspecies(con, layer_newspecies.compact([
        {**row, "name": "Aus bus", "year": 2008, "sources": ["ZSI Animal Discoveries"], "key": "K1"},
        {**row, "name": "Cus dus", "year": 2010, "sources": ["Plazi", "BSI Plant Discoveries"], "key": "K2"}]))
    got = con.sql("SELECT source, name, key, new FROM names_in ORDER BY name, source").fetchall()
    assert got == [("ZSI", "Aus bus", "K1", True), ("BSI", "Cus dus", "K2", True), ("Plazi", "Cus dus", "K2", True)]


def test_a_snapshot_with_no_unlocated_file_is_reported(tmp_path, monkeypatch, capsys):
    """Records with no coordinates count as observed; without the file they count nowhere, so say so."""
    monkeypatch.setattr(master, "SNAPSHOTS", tmp_path)
    (tmp_path / "2026-10").mkdir()
    for n in ("species", "ledger", "species_decade"):
        (tmp_path / "2026-10" / f"{n}.parquet").write_bytes(b"x")
    assert master.snapshot_input(None, "2026-10")["unlocated"] is None
    assert "warning: snapshot 2026-10 has no unlocated.parquet" in capsys.readouterr().out


def test_records_under_the_name_as_published_count_as_observed(built):
    """GBIF has no key for the name yet, but has records under it after the description: observed in India
    (no state), with a label that says why."""
    rows = {n: r for n, *r in duckdb.sql(f"""SELECT name, observed, states_observed, labels
                                             FROM '{built['out'] / 'master.parquet'}'""").fetchall()}
    observed, states, labels = rows["Wus xus"]
    assert observed and not states
    assert "vn" in labels and "chk" not in labels and "lm" not in labels


def test_records_that_cannot_go_in_a_district_are_tagged_by_problem(inputs, tmp_path, monkeypatch):
    """A species known only from such records is documented and observed, with the label No exact location and a
    label for each problem; a species with exact records too gets the problem label but not No exact location."""
    monkeypatch.setattr(master, "CACHE", tmp_path / "cache")
    con = duckdb.connect()
    iucn_table(con)
    unl = tmp_path / "unlocated.parquet"
    con.sql(f"""COPY (SELECT * FROM (VALUES
        ('U1', 'Mus nus', 'Mus', 'species', 'Birds', 'Kerala', 32, 'd1', 'PRESERVED_SPECIMEN', 'issue', 1900, 1910, 4),
        ('U1', 'Mus nus', 'Mus', 'species', 'Birds', NULL, NULL, 'd1', 'PRESERVED_SPECIMEN', 'none', 1900, 1900, 1),
        ('K3', 'Gus hus', 'Gus', 'species', 'Birds', NULL, NULL, 'd2', 'HUMAN_OBSERVATION', 'coarse', 2012, 2012, 1))
        t(species_key, name, genus, taxonrank, grp, stateprovince, state_lgd, datasetkey, basis, problem,
          first_year, last_year, n_records)) TO '{unl}' (FORMAT parquet)""")
    paths = {**inputs["paths"], "unlocated": unl}
    out = tmp_path / "out_u"
    master.build(con, paths, out, {"period": "2026-10", "snapshot": "2026-10", "built": "x"},
                 inputs["districts"], inputs["inputs"], cache={}, http=FakeGbif())
    rows = {k: (o, s, set(lab)) for k, o, s, lab in duckdb.sql(
        f"SELECT key, observed, states_observed, labels FROM '{out / 'master.parquet'}'").fetchall()}
    observed, states, labels = rows["U1"]
    assert observed and states == [32]
    assert {"sp", "lm", "lnc", "lfl"} <= labels and "lco" not in labels
    assert "lco" in rows["K3"][2] and "lm" not in rows["K3"][2]
    codes = [c for c, _, _ in master.LABELS]
    assert codes[:15] == ["rg", "nid", "ho", "sp", "pap", "dna", "mo", "oc", "chk", "lm", "do", "end", "nra", "nm", "vn"]


def test_records_from_excluded_datasets_or_other_countries_add_no_species(inputs, tmp_path, monkeypatch):
    """A snapshot built before a dataset was excluded, or with records whose place is outside India, must not put
    those species on the list: VectorBase (US mosquitoes coded IN) and a record from Nepal add nothing."""
    monkeypatch.setattr(master, "CACHE", tmp_path / "cache")
    con = duckdb.connect()
    iucn_table(con)
    unl = tmp_path / "unlocated.parquet"
    con.sql(f"""COPY (SELECT * FROM (VALUES
        ('U1', 'Mus nus', 'Mus', 'species', 'Birds', 'Kerala', 32, 'd1', 'PRESERVED_SPECIMEN', 'none', 1900, 1910, 4),
        ('V1', 'Aedes tus', 'Aedes', 'species', 'Insects: flies', 'Madhya Pradesh', 23,
         'c3969d4c-b9c1-439a-96be-ebf369f17a0c', 'HUMAN_OBSERVATION', 'issue', 1998, 2019, 880),
        ('F1', 'Fus gus', 'Fus', 'species', 'Birds', 'Nepal', NULL, 'd2', 'PRESERVED_SPECIMEN', 'none', 1890, 1890, 1))
        t(species_key, name, genus, taxonrank, grp, stateprovince, state_lgd, datasetkey, basis, problem,
          first_year, last_year, n_records)) TO '{unl}' (FORMAT parquet)""")
    out = tmp_path / "out_x"
    master.build(con, {**inputs["paths"], "unlocated": unl}, out, {"period": "2026-10-26", "snapshot": "s", "built": "x"},
                 inputs["districts"], inputs["inputs"], cache={}, http=FakeGbif())
    keys = {k for (k,) in duckdb.sql(f"SELECT key FROM '{out / 'master.parquet'}'").fetchall()}
    assert "U1" in keys and "V1" not in keys and "F1" not in keys


def test_species_known_only_from_gbif_records_with_no_place_are_labelled(inputs, tmp_path, monkeypatch):
    """The label "Only GBIF records with no exact location" marks a species that rests on one source and no mapped
    record, so a reader can set such species apart; a species with an exact record does not get it."""
    monkeypatch.setattr(master, "CACHE", tmp_path / "cache")
    con = duckdb.connect()
    iucn_table(con)
    unl = tmp_path / "unlocated.parquet"
    con.sql(f"""COPY (SELECT * FROM (VALUES
        ('U1', 'Mus nus', 'Mus', 'species', 'Birds', 'Kerala', 32, 'd1', 'PRESERVED_SPECIMEN', 'none', 1900, 1910, 4),
        ('K3', 'Gus hus', 'Gus', 'species', 'Birds', NULL, NULL, 'd2', 'HUMAN_OBSERVATION', 'coarse', 2012, 2012, 1))
        t(species_key, name, genus, taxonrank, grp, stateprovince, state_lgd, datasetkey, basis, problem,
          first_year, last_year, n_records)) TO '{unl}' (FORMAT parquet)""")
    out = tmp_path / "out_g"
    master.build(con, {**inputs["paths"], "unlocated": unl}, out, {"period": "2026-10-26", "snapshot": "s", "built": "x"},
                 inputs["districts"], inputs["inputs"], cache={}, http=FakeGbif())
    labels = {k: set(lab) for k, lab in duckdb.sql(f"SELECT key, labels FROM '{out / 'master.parquet'}'").fetchall()}
    assert "lgo" in labels["U1"] and "lm" in labels["U1"]
    assert "lgo" not in labels["K3"]
    assert ("lgo", "Only GBIF records with no exact location", "other") in master.LABELS


def test_iucn_category_changes_are_a_kind_of_change(tmp_path):
    """A species whose IUCN Red List category changed since the last list is a change of its own, with both
    categories; a species with no category before or after is not one. Lists without IUCN give no such rows."""
    con = duckdb.connect()
    g0 = GROUPS[0]
    con.sql(f"""CREATE TABLE prev AS SELECT * FROM (VALUES
        ('K1', 'Aus bus', '{g0}', ['GBIF'], true, [32], 'VU'),
        ('K2', 'Bus cus', '{g0}', ['GBIF'], true, [32], 'LC'),
        ('K3', 'Cus dus', '{g0}', ['GBIF'], true, [32], NULL))
        t(key, name, "group", sources, observed, states_observed, iucn)""")
    prev = tmp_path / "prev.parquet"
    con.sql(f"COPY prev TO '{prev}' (FORMAT parquet)")
    con.sql("""CREATE TABLE master AS SELECT * FROM (VALUES
        ('K1', 'Aus bus', 0, ['GBIF'], true, [32], 1, 'EN'),
        ('K2', 'Bus cus', 0, ['GBIF'], true, [32], 1, 'LC'),
        ('K3', 'Cus dus', 0, ['GBIF'], true, [32], 1, 'NT'))
        t(key, name, gi, sources, observed, states_observed, status, iucn)""")
    ch = master.changes(con, prev, "2026-10", "2026-10-26", n_groups=1)
    assert ch["counts"]["iucn"] == 2
    assert sorted(r for r in ch["rows"] if r[0] == "iucn") == [
        ["iucn", "K1", "Aus bus", 0, [], [], ["VU", "EN"]], ["iucn", "K3", "Cus dus", 0, [], [], [None, "NT"]]]


def summary_for(period, docs, obs, ident, cats, w_species, w_obs):
    """A summary.json with two groups, as site_files wrote it up to 2026-10-26 (with identified)."""
    iucn = master.IUCN_CATS
    row = lambda d, o, i, c: [d, o, i, [c.get(k, 0) for k in iucn], 0]
    return {"period": period, "groups": ["G0", "G1"], "totals": {"documented": 0, "observed": 0, "identified": 0},
            "india": [row(docs[0], obs[0], ident[0], cats[0]), row(docs[1], obs[1], ident[1], cats[1])],
            "waiting": {"india": [[w_species[0], w_obs[0], 0], [w_species[1], w_obs[1], 0]]}}


def summary_now(period, docs, obs, cats, w_species, w_obs):
    """A summary.json with two groups, as site_files writes it (the parts history reads)."""
    iucn = master.IUCN_CATS
    row = lambda d, o, c: [d, o, [c.get(k, 0) for k in iucn], 0]
    return {"period": period, "groups": ["G0", "G1"], "totals": {"documented": 0, "observed": 0},
            "india": [row(docs[0], obs[0], cats[0]), row(docs[1], obs[1], cats[1])],
            "waiting": {"india": [[w_species[0], w_obs[0], 0], [w_species[1], w_obs[1], 0]]}}


def test_history_has_one_entry_per_list_with_the_totals_by_group():
    s1 = summary_now("2026-10", [10, 5], [6, 2], [{"CR": 1, "VU": 2, "LC": 3}, {"EN": 1}], [3, 1], [30, 7])
    s2 = summary_now("2026-10-26", [11, 5], [7, 2], [{"CR": 1, "VU": 3}, {"EN": 1}], [2, 1], [25, 7])
    h = master.history(None, s1)
    h = master.history(h, s2)
    assert h["measures"] == ["documented", "observed", "threatened", "waiting_species", "waiting_observations"]
    assert [e["period"] for e in h["lists"]] == ["2026-10", "2026-10-26"]
    assert h["lists"][1]["india"] == [16, 9, 5, 3, 32]
    assert h["lists"][1]["groups"] == [[11, 7, 4, 2, 25], [5, 2, 1, 1, 7]]
    assert master.history(h, s2) == h                              # the same list again changes nothing
    assert [e["period"] for e in master.history(h, {**s1, "period": "2026-11-02"})["lists"]] == ["2026-10", "2026-10-26", "2026-11-02"]


def test_next_history_continues_the_previous_list_or_starts_from_its_summary():
    s1 = summary_now("2026-10", [10, 5], [6, 2], [{}, {}], [3, 1], [30, 7])
    s2 = summary_now("2026-10-26", [11, 5], [7, 2], [{}, {}], [2, 1], [25, 7])
    first_week = master.next_history({"summary": s1, "history": None}, s2)      # October had no history.json
    assert [e["period"] for e in first_week["lists"]] == ["2026-10", "2026-10-26"]
    s3 = {**s2, "period": "2026-11-02"}
    assert len(master.next_history({"summary": s2, "history": first_week}, s3)["lists"]) == 3
    assert [e["period"] for e in master.next_history(None, s1)["lists"]] == ["2026-10"]
    # A history with the measures of before (identified): only the previous list, read with today's rule.
    old = {"measures": ["documented", "observed", "identified"], "lists": [{"period": "2026-10"}]}
    h = master.next_history({"summary": s2, "history": old}, s3)
    assert [e["period"] for e in h["lists"]] == ["2026-10-26", "2026-11-02"]


def test_the_list_writes_its_history(built):
    h = json.loads((built["out"] / "history.json").read_text())
    assert [e["period"] for e in h["lists"]] == ["2026-10"] and h["measures"] == master.MEASURES


# ---------------------------------------------------------------- one folder per build

def layer_folder(tmp_path, name, files=3):
    out = tmp_path / name
    out.mkdir()
    for i in range(files):
        (out / f"f{i}.json").write_text(f'{{"{name}": {i}}}')
    (out / "manifest.json").write_text(json.dumps({"inputs": name}))
    return out


def test_a_build_goes_to_its_own_folder_and_the_pointers_move_last(tmp_path, monkeypatch):
    """Files first, then the manifest, then the week's current.json, then latest.json: the site reads one build or the
    other, never a mix. Old builds of the week beyond the one before go, and the files from before builds."""
    from pipeline import r2
    from tests.r2_fake import FakeS3
    monkeypatch.setenv("R2_BUCKET", "b")
    s3 = FakeS3()
    s3.put_object(Bucket="b", Key="layers/master/2026-10-26/summary.json", Body=b"{}")    # the layout before builds
    s3.put_object(Bucket="b", Key="layers/master/2026-11-02/g/0.json", Body=b"{}")        # from before builds
    s3.put_object(Bucket="b", Key="layers/master/2026-10-19/20261019T010000Z/summary.json", Body=b"{}")  # another week
    for n, build in enumerate(["20261102T010000Z", "20261102T090000Z", "20261103T010000Z"]):
        s3.writes.clear()
        master.publish(s3, layer_folder(tmp_path, build), "2026-11-02", build, {"period": "2026-11-02"})
        base = f"layers/master/2026-11-02/{build}/"
        assert s3.writes[-3:] == [base + "manifest.json", "layers/master/2026-11-02/current.json", "layers/master/latest.json"]
        assert set(s3.writes[:-3]) == {base + f"f{i}.json" for i in range(3)}
        assert r2.get_json(s3, "layers/master/latest.json") == {"period": "2026-11-02", "base": base}
        assert master.period_base(s3, "2026-11-02") == base
    builds = {k.split("/")[3] for k in r2.list_keys(s3, "layers/master/2026-11-02/")
              if k.count("/") == 4 and master.BUILD_RE.fullmatch(k.split("/")[3])}
    assert builds == {"20261102T090000Z", "20261103T010000Z"}                 # the oldest build of the week went
    assert "layers/master/2026-11-02/g/0.json" not in s3.store                  # the week has a pointer now
    assert "layers/master/2026-10-26/summary.json" in s3.store and "layers/master/2026-10-19/20261019T010000Z/summary.json" in s3.store
    assert master.period_base(s3, "2026-10-26") == "layers/master/2026-10-26/"   # a week from before: its own folder


def test_a_failed_upload_moves_no_pointer(tmp_path, monkeypatch):
    from pipeline import r2
    from tests.r2_fake import FakeS3
    monkeypatch.setenv("R2_BUCKET", "b")
    monkeypatch.setattr(r2, "RETRY_PAUSE", 0)
    s3 = FakeS3(fail={"layers/master/2026-11-02/B2/f1.json": -1})
    master.publish(s3, layer_folder(tmp_path, "B1"), "2026-11-02", "B1", {"period": "2026-11-02"})
    with pytest.raises(r2.UploadFailed):
        master.publish(s3, layer_folder(tmp_path, "B2"), "2026-11-02", "B2", {"period": "2026-11-02"})
    assert master.period_base(s3, "2026-11-02") == "layers/master/2026-11-02/B1/"
    assert r2.get_json(s3, "layers/master/latest.json")["base"] == "layers/master/2026-11-02/B1/"
    assert "layers/master/2026-11-02/B2/manifest.json" not in s3.store


def test_the_previous_list_comes_from_its_build_in_r2_not_a_local_copy(tmp_path, monkeypatch):
    """A local folder of an earlier list can be out of date; with R2 the list is the build its pointer names."""
    from tests.r2_fake import FakeS3
    monkeypatch.setenv("R2_BUCKET", "b")
    monkeypatch.setattr(master, "LAYERS", tmp_path / "layers")
    monkeypatch.setattr(master, "CACHE", tmp_path / "cache")
    stale = tmp_path / "layers" / "master" / "2026-10-26"
    stale.mkdir(parents=True)
    (stale / "summary.json").write_text('{"period": "stale"}')
    s3 = FakeS3()
    build = layer_folder(tmp_path, "B9")
    (build / "summary.json").write_text('{"period": "2026-10-26"}')
    (build / "master.parquet").write_bytes(b"PAR1")
    master.publish(s3, build, "2026-10-26", "B9", {"period": "2026-10-26"})
    prev = master.previous_layer(s3, "2026-11-02")
    assert prev["period"] == "2026-10-26" and prev["summary"] == {"period": "2026-10-26"}
    assert prev["parquet"].read_bytes() == b"PAR1"


def test_build_ids_sort_in_time_order():
    assert master.build_id("2026-10-28T16:00:44Z") == "20261028T160044Z"
    assert master.build_id("2026-10-28T09:00:00Z") < master.build_id("2026-10-28T16:00:44Z")


def test_retention_keeps_the_last_build_of_each_past_week(monkeypatch):
    """This week: the current build and the one before. A past week: only the build its current.json names. Files
    from before builds go where the week has a pointer; a week with no pointer keeps them (its only copy). Keys
    outside layers/master/<week>/ and the build latest.json names are never touched."""
    from pipeline import r2
    from tests.r2_fake import FakeS3
    monkeypatch.setenv("R2_BUCKET", "b")
    s3 = FakeS3()
    put = lambda k, body=b"{}": s3.put_object(Bucket="b", Key=k, Body=body)
    pointer = lambda week, b: put(f"layers/master/{week}/current.json",
                                  json.dumps({"base": f"layers/master/{week}/{b}/", "build": b}).encode())
    for k in ("summary.json", "g/0.json"):
        put(f"layers/master/2026-10/{k}")                                   # no pointer: its only copy
        put(f"layers/master/2026-10-26/{k}")                                # superseded by its builds
    for b in ("20261027T010000Z", "20261028T161358Z"):
        put(f"layers/master/2026-10-26/{b}/summary.json")
    pointer("2026-10-26", "20261028T161358Z")
    for b in ("20261102T010000Z", "20261102T090000Z", "20261103T010000Z"):
        put(f"layers/master/2026-11-02/{b}/summary.json")
    pointer("2026-11-02", "20261103T010000Z")
    put("layers/master/latest.json", json.dumps({"base": "layers/master/2026-11-02/20261103T010000Z/"}).encode())
    put("snapshots/2026-10-26/species.parquet")
    master.prune(s3, "2026-11-02", "20261103T010000Z")
    assert r2.list_keys(s3, "") == sorted([
        "layers/master/2026-10/g/0.json", "layers/master/2026-10/summary.json",
        "layers/master/2026-10-26/20261028T161358Z/summary.json", "layers/master/2026-10-26/current.json",
        "layers/master/2026-11-02/20261102T090000Z/summary.json", "layers/master/2026-11-02/20261103T010000Z/summary.json",
        "layers/master/2026-11-02/current.json", "layers/master/latest.json", "snapshots/2026-10-26/species.parquet"])
    master.prune(s3, "2026-11-02", "20261103T010000Z")                     # idempotent
    assert len(r2.list_keys(s3, "")) == 9
