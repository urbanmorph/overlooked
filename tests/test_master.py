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
        "checklist,family,name,rank,mark,col_accepted_id,col_accepted_name,col_family,match_type,needs_review\n"
        "120_Aves.pdf,Muscicapidae,Aus bus,species,*,K1,Aus bus,Muscicapidae,exact,false\n"
        "120_Aves.pdf,Muscicapidae,Aus bus minor,subspecies,,K1x,Aus bus minor,Muscicapidae,exact,false\n"
        "120_Aves.pdf,Muscicapidae,Gus hus,species,,K4,Gus hus,Muscicapidae,exact,false\n"
        "120_Aves.pdf,Muscicapidae,Hus ius,species,,Z1,Hus ius,Muscicapidae,exact,false\n"
        "108_Insecta_Coleoptera.pdf,Unknownidae,Xus (Yus) yus,species,,,,,none,false\n"
        "120_Aves.pdf,Muscicapidae,Qus rus,species,,K7,,,exact,false\n")  # no accepted name given
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
                                         "any_record": False}])
    return {"paths": {"species": sp, "species_decade": dec, "ledger": led, "unlocated": None, "candidates": None},
            "inputs": {"zsi": zsi, "wcvp": wcvp, "bsi": bsi, "inat": inat_doc, "newspecies": ns_doc,
                       "inat_genus": {"lists": {"32": [[50, "Hus", "Aves", 3]],
                                                "india": [[50, "Hus", "Aves", 5], [60, "Nus", "Insecta", 2],
                                                          [55, "Hia", "Aves", 1]]}},
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
    summary = master.build(con, inputs["paths"], out, {"month": "2026-10", "snapshot": "2026-10", "built": "x"},
                           inputs["districts"], inputs["inputs"], cache={}, http=http)
    rows = {r[1]: dict(zip(["key", "name", "group", "sources", "observed", "identified", "iucn", "labels",
                            "states_observed", "states_identified"], r))
            for r in duckdb.sql(f"SELECT * FROM '{out / 'master.parquet'}'").fetchall()}
    return {"summary": summary, "rows": rows, "out": out, "http": http}


def test_documented_observed_identified(built):
    t = built["summary"]["totals"]
    assert t == {"documented": 10, "observed": 5, "identified": 4}
    assert built["rows"]["Qus rus"]["key"] == "K7"
    r = built["rows"]
    assert r["Aus bus"]["identified"] and r["Aus bus"]["states_identified"] == [32]
    assert r["Zus zus"]["observed"] and not r["Zus zus"]["identified"]
    assert r["Zus zus"]["states_observed"] == [29] and r["Zus zus"]["states_identified"] == []
    assert not r["Gus hus"]["observed"]


def test_sources_and_labels(built):
    r = built["rows"]
    assert r["Aus bus"]["sources"] == ["ZSI", "GBIF", "iNaturalist", "IUCN"]
    assert r["Aus bus"]["labels"] == ["rg", "ho", "end"]
    assert r["Cus dus"]["sources"] == ["BSI", "WCVP", "GBIF", "IUCN"]
    assert "Old dus" not in r and r["Pus qus"]["group"] == "Plants: ferns & lycophytes" and r["Cus dus"]["labels"] == ["sp", "end"]
    assert r["Eus fus"]["labels"] == ["dna", "do"]
    assert r["Gus hus"]["sources"] == ["ZSI", "Plazi"] and r["Gus hus"]["labels"] == ["chk", "ns"]
    assert r["Zus zus"]["labels"] == ["nid", "nm"]


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
    assert r["Gus hus"]["group"] == r["Zus zus"]["group"] == "Birds"


def test_site_files(built):
    out, s = built["out"], built["summary"]
    birds = GROUPS.index("Birds")
    assert s["india"][birds][:3] == [5, 3, 2]                # Aus, Gus, Hus, Qus, Zus
    assert s["india"][birds][3][s["iucn"].index("EN")] == 1 and s["india"][birds][4] == 1
    assert [st["code"] for st in s["states"]] == ["29", "32"]
    assert {"licence", "attribution", "disclaimer"} <= set(s)
    assert s["by_state"]["29"][birds] == [1, 0, 0]
    labels = [lab["code"] for lab in s["labels"]]
    g = json.loads((out / "g" / f"{birds}.json").read_text())["rows"]
    aus = next(x for x in g if x[1] == "Aus bus")
    assert aus[0] == "K1" and aus[3] == 2 and aus[7] == 1 << 1      # identified in state index 1 (32)
    assert aus[5] & (1 << labels.index("end")) and aus[2] == 0b1011001  # ZSI, GBIF, iNaturalist, IUCN
    search = json.loads((out / "search" / "au.json").read_text())["rows"]
    assert search == [["Aus bus", "K1", birds, 2, 1, aus[2], aus[5]]]
    assert json.loads((out / "search" / "xu.json").read_text())["rows"][0][1] == ""
    places = json.loads((out / "search" / "places.json").read_text())["rows"]
    assert ["Kerala", "state", 32, 32] in places and ["Mysuru", "district", 201, 29] in places


def test_waiting_for_a_name(built):
    """iNaturalist needs-ID species per area: counts per group, and a file per group with the taxon to identify."""
    out, w = built["out"], built["summary"]["waiting"]
    birds = GROUPS.index("Birds")
    assert w["places"] == {"india": 6681, "32": 7, "29": 8}
    # [species waiting, observations waiting, species with no identification in that area]
    assert w["india"][birds] == [2, 7, 1]           # Zus zus (never identified) and Hus ius
    assert w["by_state"]["29"][birds] == [1, 1, 1]
    assert w["by_state"]["32"][birds] == [1, 6, 0]  # Hus ius and its subspecies; identified in Kerala by GBIF
    rows = json.loads((out / "w" / f"{birds}.json").read_text())["rows"]
    # [key, name, iNaturalist taxon (the species, not a subspecies), observations in India, [[state index, n]]]
    assert rows == [["G1", "Hus ius", 3, 6, [[1, 6]]], ["", "Zus zus", 2, 1, [[0, 1]]]]


def test_waiting_at_genus_and_above(built):
    """Observations named only to genus: per genus, with what the list knows of the genus in India.
    Observations named only above genus: counts per area and iNaturalist iconic group."""
    out, w = built["out"], built["summary"]["waiting"]
    birds, other = GROUPS.index("Birds"), GROUPS.index("Insects: other")
    assert w["genus"]["india"][birds] == [2, 6] and w["genus"]["india"][other] == [1, 2]
    assert w["genus"]["by_state"]["32"][birds] == [1, 3]
    assert w["coarse"] == {"india": {"Aves": 9, "Insecta": 1}, "by_state": {"32": {"Aves": 4}}}
    # [genus, iNaturalist taxon, observations in India, [[state index, n]], species of the genus on the list,
    #  of them never identified, threatened, endemic]
    rows = json.loads((out / "wg" / f"{birds}.json").read_text())["rows"]
    # Hia: the genus of an older name of Hus ius, still known to the list through that name.
    assert rows == [["Hia", 55, 1, [], 1, 0, 0, 0], ["Hus", 50, 5, [[1, 3]], 1, 0, 0, 0]]
    assert json.loads((out / "wg" / f"{other}.json").read_text())["rows"] == [["Nus", 60, 2, [], 0, 0, 0, 0]]


def test_prefix():
    assert master.prefix("Aus bus") == "au" and master.prefix("×Cus") == "_c" and master.prefix("A") == "a_"


def test_second_run_asks_nothing(inputs, built, tmp_path):
    con = duckdb.connect()
    iucn_table(con)
    cache = json.loads((tmp_path / "cache" / "gbif_match.json").read_text())
    http = FakeGbif()
    master.build(con, inputs["paths"], tmp_path / "out2", {"month": "m", "snapshot": "s", "built": "x"},
                 inputs["districts"], inputs["inputs"], cache=cache, http=http)
    assert http.asked == []


def test_match_stops_at_deadline(inputs, tmp_path, monkeypatch):
    monkeypatch.setattr(master, "CACHE", tmp_path / "cache")
    con = duckdb.connect()
    iucn_table(con)
    http = FakeGbif()
    s = master.build(con, inputs["paths"], tmp_path / "o", {"month": "m", "snapshot": "s", "built": "x"},
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


def test_changes_between_months(tmp_path):
    """Species that moved since last month: added, observed, identified, identified in a new state, dropped."""
    con = duckdb.connect()
    g0, g1 = GROUPS[0], GROUPS[1]
    con.sql(f"""CREATE TABLE prev AS SELECT * FROM (VALUES
        ('K1', 'Aus bus', '{g0}', ['ZSI'], false, false, []::INTEGER[]),
        ('K2', 'Bus cus', '{g0}', ['GBIF'], true, false, []::INTEGER[]),
        ('K3', 'Cus dus', '{g1}', ['GBIF'], true, true, [32]),
        ('K4', 'Dus eus', '{g1}', ['GBIF'], true, true, [32]),
        (NULL, 'Old name', '{g1}', ['ZSI'], false, false, []::INTEGER[]))
        t(key, name, "group", sources, observed, identified, states_identified)""")  # as in master.parquet
    cols = "key, name, gi, sources, observed, identified, states_identified"
    prev = tmp_path / "prev.parquet"
    con.sql(f"COPY prev TO '{prev}' (FORMAT parquet)")
    con.sql(f"""CREATE TABLE master AS SELECT * FROM (VALUES
        ('K1', 'Aus bus', 0, ['ZSI', 'iNaturalist'], true, false, []::INTEGER[]),
        ('K2', 'Bus cus', 0, ['GBIF', 'iNaturalist'], true, true, [29]),
        ('K3', 'Cus dus', 1, ['GBIF'], true, true, [29, 32]),
        ('K4', 'Dus eus', 1, ['GBIF'], true, true, [32]),
        ('K5', 'Eus fus', 1, ['BSI'], false, false, []::INTEGER[])) t({cols})""")
    ch = master.changes(con, prev, "2026-10", "2026-11", n_groups=2)
    assert ch["from"] == "2026-10" and ch["to"] == "2026-11"
    assert ch["counts"] == {"identified": 1, "state": 1, "observed": 1, "documented": 1, "dropped": 1}
    # per group: [added, newly observed, newly identified, identified in a new state]
    assert ch["groups"] == [[0, 1, 1, 0], [1, 0, 0, 1]]
    assert sorted(ch["rows"]) == sorted([
        ["identified", "K2", "Bus cus", 0, [29], ["iNaturalist"]],
        ["observed", "K1", "Aus bus", 0, [], ["iNaturalist"]],
        ["state", "K3", "Cus dus", 1, [29], []],
        ["documented", "K5", "Eus fus", 1, [], ["BSI"]],
        ["dropped", "", "Old name", 1, [], []]])
    assert master.changes(con, None, None, "2026-11", n_groups=2) == {"from": None, "to": "2026-11"}


def test_first_month_has_no_changes(built):
    assert json.loads((built["out"] / "changes.json").read_text()) == {"from": None, "to": "2026-10"}


def test_previous_month():
    assert master.previous_month("2026-11") == "2026-10" and master.previous_month("2027-01") == "2026-12"
