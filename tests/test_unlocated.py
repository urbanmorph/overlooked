"""Genus in query U, and records without coordinates (query L)."""

import csv
import json

import duckdb
import pytest

from pipeline import checks, gbif

U_HEAD_OLD = "kingdom\tphylum\tclass\torder\tfamily\ttaxonrank\tlat\tlon\tfirst_year\tlast_year\tn_records\n"
U_HEAD = "kingdom\tphylum\tclass\torder\tfamily\tgenus\ttaxonrank\tlat\tlon\tfirst_year\tlast_year\tn_records\n"
ORCH = "Plantae\tTracheophyta\tLiliopsida\tAsparagales\tOrchidaceae"


@pytest.fixture
def districts(tmp_path):
    """Three square districts: 101 and 102 in state 32 (lon 76-78), 201 in state 29 (lon 74-75)."""
    path = tmp_path / "districts.parquet"
    con = duckdb.connect()
    con.sql("INSTALL spatial; LOAD spatial")
    con.sql(f"""
        COPY (
          SELECT 101 AS dist_lgd, 32 AS state_lgd, 'West' AS dtname, 'KERALA' AS stname, ST_MakeEnvelope(76, 10, 77, 11) AS geometry
          UNION ALL SELECT 102, 32, 'East', 'KERALA', ST_MakeEnvelope(77, 10, 78, 11)
          UNION ALL SELECT 201, 29, 'Far', 'KARNATAKA', ST_MakeEnvelope(74, 12, 75, 13)
        ) TO '{path}' (FORMAT parquet)
    """)
    return path


# 1. Genus in query U

def test_unresolved_keeps_genus(districts, tmp_path):
    from pipeline import unresolved
    tsv = tmp_path / "u.tsv"
    tsv.write_text(U_HEAD + f"{ORCH}\tDendrobium\tGENUS\t10.5\t76.5\t1950\t2020\t4\n"
                   + f"{ORCH}\t\tFAMILY\t10.5\t76.5\t1950\t1960\t2\n")
    con = duckdb.connect()
    assert unresolved.build(con, tsv, str(districts)) == 6
    rows = con.sql("SELECT genus, taxonrank, n_records, n_records_since_1980 FROM unresolved ORDER BY 2 DESC").fetchall()
    assert rows == [("Dendrobium", "genus", 4, 4), (None, "family", 2, 0)]


def test_unresolved_reads_old_files_without_genus(districts, tmp_path):
    from pipeline import unresolved
    tsv = tmp_path / "u.tsv"
    tsv.write_text(U_HEAD_OLD + f"{ORCH}\tGENUS\t10.5\t76.5\t1950\t2020\t4\n")
    con = duckdb.connect()
    assert unresolved.build(con, tsv, str(districts)) == 4
    assert con.sql("SELECT genus, taxonrank FROM unresolved").fetchall() == [(None, "genus")]


# 2. "May be an overlooked species"

def _ledger(con, rows, species):
    con.sql("CREATE OR REPLACE TABLE ledger (species_key VARCHAR, district_lgd INT, state_lgd INT, first_year INT, last_year INT, n_records BIGINT)")
    if rows:
        con.executemany("INSERT INTO ledger VALUES (?, ?, ?, ?, ?, ?)", rows)
    con.sql("""CREATE OR REPLACE TABLE species (species_key VARCHAR, name VARCHAR, kingdom VARCHAR, phylum VARCHAR,
               class VARCHAR, "order" VARCHAR, family VARCHAR, genus VARCHAR)""")
    if species:
        con.executemany("INSERT INTO species VALUES (?, ?, ?, ?, ?, ?, ?, ?)", species)


ORCHID = ("Plantae", "Tracheophyta", "Liliopsida", "Asparagales", "Orchidaceae")
FERN = ("Plantae", "Tracheophyta", "Polypodiopsida", "Polypodiales", "Pteridaceae")


# 3. Query L

def test_unlocated_query_filters():
    sql = gbif.build_sql("unlocated_cube")
    assert "hascoordinate = FALSE" in sql and "stateprovince" in sql and "datasetkey NOT IN ('" in sql
    assert "level1name" not in sql
    kerala = gbif.build_sql("unlocated_cube", "Kerala")
    assert "stateprovince = 'Kerala'" in kerala and "level1name" not in kerala
    assert "level1name = 'Kerala'" in gbif.build_sql("ledger_cube", "Kerala")


def test_query_l_runs_last():
    from pipeline.run import QUERIES
    assert QUERIES[-1] == "unlocated_cube" and QUERIES[:3] == ["ledger_cube", "species_history", "unresolved_cube"]


# 4. State names

@pytest.mark.parametrize("text, lgd", [
    ("Assam", 18), ("Jammu & Kashmir", 1), ("Jammu and Kashmir State", 1), ("Jammu-Kashmir", 1),
    ("Orissa", 21), ("Pondicherry", 34), ("Uttaranchal", 5), ("Uttarakhand/Uttaranchal", 5),
    ("Andaman & Nicobar Islands", 35), ("Union Territory of Andaman and Nicobar Islands", 35), ("Andaman Is.", 35),
    ("NCT of Delhi", 7), ("Delhi, Capital Territory of", 7), ("State of Tamil Nadu", 33), ("TamilNadu", 33),
    ("Tamil Nādu", 33), ("État du Tamil Nadu", 33), ("Meghalaya (梅加拉亞邦)", 17), ("Karnataka (Mysore)", 29),
    ("Mysore (Karnataka)", 29), ("Burdwan dist., West Bengal", 19), ("[Himachal Pradesh]", 2), ("Pun jab", 3),
    ("Ladakh", 37), ("Telangana", 36), ("Dadra and Nagar Haveli and Daman and Diu", 38),
    ("Bombay", None), ("Madras", None), ("Bengal", None), ("[Not Stated]", None), ("", None), (None, None),
    ("Kerala, Tamil Nadu", None), ("Punjab [Haryana]", None),   # two states: left unplaced
    ("Mysore", None), ("Mysore State", 29), ("Madras State", 33), ("Bihar State of", 10), ("NEFA", 12),
])
def test_state_names(text, lgd):
    from pipeline import unlocated
    assert unlocated.state_of(text, unlocated.load_state_names()) == lgd


def test_state_names_table_is_consistent():
    from pipeline import unlocated
    rows = list(csv.DictReader(unlocated.STATE_NAMES.open()))
    keys = {}
    for r in rows:
        k = unlocated.key(r["name"])
        assert keys.setdefault(k, r["state_lgd"]) == r["state_lgd"], r["name"]
    assert {int(r["state_lgd"]) for r in rows} == {*range(1, 25), *range(27, 39)}


# 5. Outputs

L_HEAD = ("specieskey\tspecies\tgenus\ttaxonrank\tkingdom\tphylum\tclass\torder\tfamily\tstateprovince\tdatasetkey"
          "\tbasisofrecord\tfirst_year\tlast_year\tn_records\n")


def test_unlocated_tables_and_json(tmp_path):
    from pipeline import site_data, unlocated
    tsv = tmp_path / "l.tsv"
    tsv.write_text(L_HEAD
                   + f"D1\tDendrobium one\tDendrobium\tSPECIES\t{ORCH}\tKerala\tds1\tPRESERVED_SPECIMEN\t1900\t1950\t5\n"
                   + f"X9\tDendrobium nine\tDendrobium\tSPECIES\t{ORCH}\tOrissa\tds2\tPRESERVED_SPECIMEN\t1890\t1890\t2\n"
                   + f"OLD\tDendrobium nine\tDendrobium\tSPECIES\t{ORCH}\tBombay\tds1\tPRESERVED_SPECIMEN\t1880\t1880\t1\n"
                   + f"\t\tDendrobium\tGENUS\t{ORCH}\t\tds1\tPRESERVED_SPECIMEN\t\t\t3\n")
    con = duckdb.connect()
    _ledger(con, [("D1", 101, 32, 1900, 2020, 1)], [("D1", "Dendrobium one", *ORCHID, "Dendrobium")])
    con.sql("CREATE TABLE key_map AS SELECT 'OLD' AS species_key, 'X9' AS canonical")
    assert unlocated.build(con, tsv) == 11
    rows = con.sql("SELECT species_key, state_lgd, n_records FROM unlocated ORDER BY n_records DESC").fetchall()
    assert rows == [("D1", 32, 5), (None, None, 3), ("X9", 21, 2), ("X9", None, 1)]
    obj = site_data.unlocated_json(con, tmp_path, titles=lambda keys: {"ds1": "Herbarium one"})
    saved = json.loads((tmp_path / "unlocated.json").read_text())
    assert saved == obj
    assert saved["india"] == {"r": [11, 11], "s": [2, 2]}
    assert saved["states"]["none"] == {"r": [4, 4], "s": [1, 1]}
    assert saved["states"]["21"]["r"][0] == 2
    assert saved["holders"][0] == ["ds1", "Herbarium one", 9, 2]
    assert saved["holders"][1] == ["ds2", None, 2, 1]
    assert saved["state_holders"]["32"] == [["ds1", 5]]
    assert saved["only_unlocated"]["g"] == [1, 1]
    assert saved["only_unlocated"]["rows"] == [["X9", "Dendrobium nine", 0, 3, 1880, 1890, 1]]


def test_dataset_titles_cached_and_retried(tmp_path):
    from pipeline import unlocated
    from tests.test_restart import FakeHttp, FakeResponse
    cache = tmp_path / "titles.json"
    http = FakeHttp(FakeResponse(data={"title": "Herbarium one"}))
    assert unlocated.dataset_titles(http, ["ds1"], cache, gap=0) == {"ds1": "Herbarium one"}
    assert unlocated.dataset_titles(http, ["ds1"], cache, gap=0) == {"ds1": "Herbarium one"}
    assert len(http.calls) == 1                       # second call came from the cache

    class Down(FakeHttp):
        def get(self, url, **kw):
            raise unlocated.requests.ConnectionError("down")
    assert unlocated.dataset_titles(Down(None), ["ds2"], cache, gap=0) == {"ds2": None}
    assert "ds2" not in json.loads(cache.read_text())  # a failure is tried again next time


# 6. Checks

def test_checks_new_outputs():
    manifest = {"downloads": [{"key": "k", "doi": "10.15468/dl.x"}]}
    base = {"ledger_rows": 1000, "districts": 10, "species": 100}
    assert not checks.run(base, manifest)                                  # old snapshot: not built, not checked
    assert checks.run({**base, "unlocated_records": 0}, manifest)          # built but empty
    now = {**base, "unlocated_records": 1000}
    assert not checks.run(now, manifest, {"species": 100, "ledger_rows": 1000})   # previous month lacks them
    assert checks.run(now, manifest, {**base, "unlocated_records": 700})
    assert not checks.run(now, manifest, {**base, "unlocated_records": 900})
