"""New-species layer: which GBIF records count as a record after the description (same rules as the master list)."""

import duckdb

from pipeline import gbif
from pipeline import layer_newspecies as ns


def test_sequences_with_no_coordinates_do_not_count():
    # (year, basis, records, sequence_only): INSDC sequences with no coordinates are not observations.
    rows = [(2019, "MATERIAL_SAMPLE", 36, True), (2020, "MATERIAL_CITATION", 2, False)]
    assert ns.after(rows) == (0, 2, None)
    assert ns.after(rows + [(2021, "PRESERVED_SPECIMEN", 1, False)]) == (1, 2, 2021)


def test_queries_y_and_v_flag_sequences_with_no_coordinates():
    for q in ns.QUERIES:
        sql = gbif.build_sql(q)
        assert "hascoordinate" in sql and "AS sequence_only" in sql and "d8cd16ba-bb74-4420-821e-083f2bac17c2" in sql


def test_names_as_published_match_whole_words():
    con = duckdb.connect()
    con.sql("""CREATE TABLE v AS SELECT * FROM (VALUES
        ('Cryptocephalus sehestedti', 2020, 'PRESERVED_SPECIMEN', 3, false),
        ('Choroterpes latus Kluge, 2023', 2023, 'MATERIAL_SAMPLE', 2, false),
        ('Choroterpes latusoides', 2023, 'MATERIAL_SAMPLE', 9, false),
        ('Choroterpes latus', 2010, 'OCCURRENCE', 1, false))
        AS t(v_scientificname, "year", basisofrecord, n_records, sequence_only)""")
    assert ns.verbatim_rows(con, "Choroterpes latus", 2020) == [(2023, "MATERIAL_SAMPLE", 2, False)]
    assert ns.verbatim_rows(con, "Cryptocephalus s", 2018) == []


def test_merge_drops_names_with_a_one_letter_epithet():
    n = {"name": "Cryptocephalus s", "year": 2018, "source": "ZSI Animal Discoveries", "journal": "", "state": "", "link": "x"}
    assert ns.merge([n, dict(n, name="Ia io")]) == [dict(n, name="Ia io", sources=["ZSI Animal Discoveries"])]


def test_a_new_query_text_downloads_again():
    state = {"downloads": {q: {"key": "k", "status": "SUCCEEDED"} for q in ns.QUERIES}, "names": [1], "done": "y"}
    assert ns.check_queries(state) is True
    assert all(d == {"status": "WAITING"} for d in state["downloads"].values())
    assert state["names"] == [1] and "done" not in state       # names stay; the match runs again
    assert ns.check_queries(state) is False
