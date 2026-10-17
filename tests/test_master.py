"""Master list: matching, flags, labels and the site files, on small synthetic inputs."""

import json

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
    wcvp = write(con, """SELECT * FROM (VALUES ('Cus dus', 'Orchidaceae', 'Cus', true), ('Wus vus', 'Orchidaceae', 'Wus', false))
        t(species, family, genus, endemic_india)""", tmp_path / "wcvp.parquet")
    dist = write(con, """SELECT * FROM (VALUES (101, 32, 'ERNAKULAM', 'KERALA'), (201, 29, 'MYSURU', 'KARNATAKA'))
        t(dist_lgd, state_lgd, dtname, stname)""", tmp_path / "districts.parquet")
    inat_doc = {"complete": True, "lists": {"32": {"research": [[1, "Aus bus", "Aves", 3]], "needs_id": []},
                                            "29": {"research": [], "needs_id": [[2, "Zus zus", "Aves", 1]]}}}
    ns_doc = layer_newspecies.compact([{"name": "Gus hus", "year": 2020, "sources": ["Plazi"], "journal": "J",
                                         "state": "", "link": "https://x/1", "group": "Birds", "key": "K4",
                                         "matched_by": "exact name", "status": "none", "latest_after": None,
                                         "any_record": False}])
    return {"paths": {"species": sp, "species_decade": dec, "ledger": led, "unlocated": None, "candidates": None},
            "inputs": {"zsi": zsi, "wcvp": wcvp, "bsi": None, "inat": inat_doc, "newspecies": ns_doc},
            "districts": dist}


class Resp:
    def __init__(self, data):
        self.data, self.ok = data, True

    def json(self):
        return self.data


class FakeGbif:
    """GBIF v2 match: 'Wus vus' matches K5; everything else has no exact match."""

    def __init__(self):
        self.headers, self.asked = {}, []

    def get(self, url, params=None, **kw):
        self.asked.append(params["scientificName"])
        if params["scientificName"] == "Wus vus":
            return Resp({"usage": {"key": "K5", "name": "Wus vus L.", "canonicalName": "Wus vus"},
                         "classification": [{"rank": "KINGDOM", "name": "Plantae"}, {"rank": "PHYLUM", "name": "Tracheophyta"},
                                            {"rank": "FAMILY", "name": "Orchidaceae"}],
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
    assert t == {"documented": 9, "observed": 5, "identified": 4}
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
    assert r["Cus dus"]["sources"] == ["WCVP", "GBIF", "IUCN"] and r["Cus dus"]["labels"] == ["sp", "end"]
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
    assert built["http"].asked == ["Zus zus", "Wus vus"]     # iNaturalist first; ZSI names are not asked again


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
    assert http.asked == [] and s["names_pending_match"] == 2
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
