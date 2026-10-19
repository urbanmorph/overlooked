import duckdb
import pytest

from pipeline import checks, gbif, ledger


@pytest.fixture
def districts(tmp_path):
    """Two square districts side by side: 101 covers lon 76-77, 102 covers lon 77-78 (lat 10-11)."""
    path = tmp_path / "districts.parquet"
    con = duckdb.connect()
    con.sql("INSTALL spatial; LOAD spatial")
    con.sql(f"""
        COPY (
          SELECT 101 AS dist_lgd, 32 AS state_lgd, 'West' AS dtname, 'KERALA' AS stname,
                 ST_MakeEnvelope(76, 10, 77, 11) AS geometry
          UNION ALL
          SELECT 102, 32, 'East', 'KERALA', ST_MakeEnvelope(77, 10, 78, 11)
        ) TO '{path}' (FORMAT parquet)
    """)
    return path


def test_build_sql_fills_filters():
    sql = gbif.build_sql("ledger_cube", "Kerala")
    assert "{" not in sql and "}" not in sql
    assert "level1name = 'Kerala'" in sql
    assert "ROUND(decimallatitude, 3)" in sql
    assert "--" not in sql


def test_build_sql_national_has_no_region():
    assert "level1name" not in gbif.build_sql("ledger_cube")


def test_ledger_places_points(districts, tmp_path):
    con = duckdb.connect()
    con.sql("""
        CREATE TABLE cube AS SELECT * FROM (VALUES
          (1, 10.5, 76.5, 1900, 1950, 3),   -- inside West, quiet since 1980
          (1, 10.5, 77.5, 2001, 2020, 2),   -- inside East
          (2, 10.5, 75.98, 1990, 1990, 1),  -- about 2 km west of West: near shore
          (3, 10.5, 74.0, 2000, 2000, 5),   -- far out at sea: offshore
          (4, 10.5, 76.6, NULL, NULL, 4)    -- no year
        ) t(specieskey, lat, lon, first_year, last_year, n_records)
    """)
    stats = ledger.build(con, tmp_path / "out", "test", districts)
    rows = {(r[0], r[1]): r for r in con.sql("SELECT * FROM ledger").fetchall()}
    assert set(rows) == {(1, 101), (1, 102), (2, 101), (4, 101)}
    assert rows[(1, 101)][4] == 1950
    assert rows[(2, 101)][6] == 1          # near-shore records counted
    assert rows[(4, 101)][4] is None       # no year stays unknown
    assert stats["records_offshore"] == 5
    assert stats["records_near_shore"] == 1
    assert stats["records_no_year"] == 4


def test_checks_flag_big_change():
    summary = {"ledger_rows": 1000, "districts": 10, "species": 130}
    manifest = {"downloads": [{"key": "k", "doi": "10.15468/dl.x"}]}
    assert checks.run(summary, manifest, {"species": 100, "ledger_rows": 1000})
    assert not checks.run(summary, manifest, {"species": 120, "ledger_rows": 1000})


def test_checks_need_doi():
    summary = {"ledger_rows": 1, "districts": 1, "species": 1}
    assert checks.run(summary, {"downloads": [{"key": "k", "doi": None}]})


def test_names_from_history(tmp_path):
    from pipeline import names
    tsv = tmp_path / "h.tsv"
    tsv.write_text("specieskey\tkingdom\tphylum\tclass\torder\tfamily\tgenus\tspecies\tdecade\tbasisofrecord\tn_records\n"
                   "5VKF2\tAnimalia\tChordata\tAves\tPasseriformes\tMotacillidae\tAnthus\tAnthus nilghiriensis\t2010\tHUMAN_OBSERVATION\t7\n"
                   "5VKF2\tAnimalia\tChordata\tAves\tPasseriformes\tMotacillidae\tAnthus\tAnthus nilghiriensis\t1990\tPRESERVED_SPECIMEN\t2\n")
    con = duckdb.connect()
    names.load_history(con, tsv)
    assert con.sql("SELECT name FROM species").fetchall() == [("Anthus nilghiriensis",)]
    assert con.sql("SELECT sum(n_records) FROM species_decade").fetchone()[0] == 9


def test_inputs_fingerprint_is_stable_and_sensitive():
    from pipeline.run import inputs_fingerprint
    state = {"downloads": {"species_history": {"key": "b"}, "ledger_cube": {"key": "a"}}}
    same = {"downloads": {"ledger_cube": {"key": "a"}, "species_history": {"key": "b"}}}
    other = {"downloads": {"ledger_cube": {"key": "a2"}, "species_history": {"key": "b"}}}
    bnd = {"sha256": "x" * 64}
    assert inputs_fingerprint(state, bnd) == inputs_fingerprint(same, bnd)
    assert inputs_fingerprint(state, bnd) != inputs_fingerprint(other, bnd)
    assert inputs_fingerprint(state, bnd) != inputs_fingerprint(state, {"sha256": "y" * 64})


def test_health_changed():
    from pipeline.health import changed
    now = {"sources": {"kew": {"fingerprint": {"ETag": "1"}}}}
    assert changed(now, None, "kew")
    assert not changed(now, {"sources": {"kew": {"fingerprint": {"ETag": "1"}}}}, "kew")
    assert changed(now, {"sources": {"kew": {"fingerprint": {"ETag": "0"}}}}, "kew")


def test_unresolved_records_placed_by_group_and_rank(districts, tmp_path):
    from pipeline import unresolved
    tsv = tmp_path / "u.tsv"
    tsv.write_text("kingdom\tphylum\tclass\torder\tfamily\ttaxonrank\tlat\tlon\tfirst_year\tlast_year\tn_records\n"
                   "Animalia\tArthropoda\tInsecta\tColeoptera\tCarabidae\tGENUS\t10.5\t76.5\t2001\t2020\t4\n"
                   "Animalia\tArthropoda\tInsecta\tColeoptera\t\tORDER\t10.5\t77.5\t2010\t2010\t1\n"
                   "Plantae\tTracheophyta\t\t\t\tPHYLUM\t10.5\t74.0\t2010\t2010\t9\n")
    con = duckdb.connect()
    total = unresolved.build(con, tsv, str(districts))
    rows = con.sql("SELECT district_lgd, grp, taxonrank, n_records FROM unresolved ORDER BY 1").fetchall()
    assert total == 5                       # the offshore plant record is left out
    assert rows == [(101, "Insects: beetles", "genus", 4), (102, "Insects: beetles", "order", 1)]


def test_new_species_names():
    from pipeline.layer_newspecies import binomial, merge, SP_NOV
    assert binomial("Cycas dharmrajii L.J.Singh") == "Cycas dharmrajii"
    assert binomial("CYCAS") is None and binomial("the species") is None
    assert SP_NOV.match("sp. nov.") and SP_NOV.match("nov.sp") and not SP_NOV.match("comb. nov.")
    m = merge([{"name": "Aa bb", "year": 2019, "source": "Plazi", "journal": "Zootaxa", "state": "", "link": "p"},
               {"name": "Aa bb", "year": 2018, "source": "BSI Plant Discoveries", "journal": "", "state": "Kerala", "link": "b"}])
    assert len(m) == 1 and m[0]["year"] == 2018 and m[0]["sources"] == ["Plazi", "BSI Plant Discoveries"] and m[0]["state"] == "Kerala"


def test_duplicate_keys_for_one_name_are_merged(districts, tmp_path):
    """COL can give one species two keys with the same classification; records under both count as one."""
    from pipeline import names
    head = "specieskey\tkingdom\tphylum\tclass\torder\tfamily\tgenus\tspecies\tdecade\tbasisofrecord\tn_records\n"
    row = "\tAnimalia\tChordata\tAves\tColumbiformes\tColumbidae\tColumba\tColumba elphinstonii\t"
    tsv = tmp_path / "h.tsv"
    tsv.write_text(head + "XBFD" + row + "2020\tHUMAN_OBSERVATION\t1700\n" + "VN78J" + row + "1940\tPRESERVED_SPECIMEN\t2\n"
                   # a homonym in another kingdom stays separate
                   + "PL1\tPlantae\tTracheophyta\tMagnoliopsida\tX\tY\tColumba\tColumba elphinstonii\t1950\tPRESERVED_SPECIMEN\t1\n")
    con = duckdb.connect()
    names.load_history(con, tsv)
    assert names.merge_duplicates(con) == 1
    assert sorted(con.sql("SELECT species_key FROM species").fetchall()) == [("PL1",), ("XBFD",)]
    assert con.sql("SELECT sum(n_records) FROM species_decade WHERE species_key = 'XBFD'").fetchone()[0] == 1702
    cube = tmp_path / "c.tsv"
    cube.write_text("specieskey\tlat\tlon\tfirst_year\tlast_year\tn_records\n"
                    "VN78J\t10.5\t76.5\t1938\t1947\t2\nXBFD\t10.5\t76.5\t1990\t2026\t1700\n")
    ledger.load_cube(con, cube)
    ledger.build(con, tmp_path / "out", "test", districts)
    assert con.sql("SELECT species_key, first_year, last_year, n_records FROM ledger").fetchall() == [("XBFD", 1938, 2026, 1702)]


DNA = "d8cd16ba-bb74-4420-821e-083f2bac17c2"      # INSDC Sequences
HOST = "393b8c26-e4e0-4dd0-a218-93fc074ebf4e"     # INSDC Host Organism Sequences


def test_sequence_datasets_scope():
    """Host-organism sequences are left out everywhere; sequences with no coordinates are left out of query L
    (with coordinates they count, as in query A), and query A keeps a latest year without them."""
    for q in ("ledger_cube", "species_history", "unresolved_cube", "unlocated_cube"):
        assert HOST in gbif.build_sql(q)
    assert DNA not in gbif.build_sql("unlocated_cube").split("NOT IN")[1]
    assert f"hascoordinate = TRUE OR datasetkey NOT IN ('{DNA}')" in gbif.build_sql("unlocated_cube")
    assert DNA not in gbif.build_sql("ledger_cube").split("NOT IN")[1]
    assert "last_year_not_dna" in gbif.build_sql("ledger_cube")


def test_latest_record_from_dna_is_marked(districts, tmp_path):
    cube = tmp_path / "c.tsv"
    cube.write_text("specieskey\tlat\tlon\tfirst_year\tlast_year\tn_records\tlast_year_not_dna\n"
                    "S1\t10.5\t76.5\t1950\t2019\t3\t1950\n"      # latest record is a DNA sequence
                    "S2\t10.5\t76.5\t1960\t2001\t2\t2001\n")     # latest record is not
    con = duckdb.connect()
    ledger.load_cube(con, cube)
    ledger.build(con, tmp_path / "out", "test", districts)
    got = dict(con.sql("SELECT species_key, last_year_not_dna FROM ledger").fetchall())
    assert got == {"S1": 1950, "S2": 2001}


def test_old_cube_without_dna_column(districts, tmp_path):
    cube = tmp_path / "c.tsv"
    cube.write_text("specieskey\tlat\tlon\tfirst_year\tlast_year\tn_records\nS1\t10.5\t76.5\t1950\t2019\t3\n")
    con = duckdb.connect()
    ledger.load_cube(con, cube)
    ledger.build(con, tmp_path / "out", "test", districts)
    assert con.sql("SELECT last_year, last_year_not_dna FROM ledger").fetchall() == [(2019, 2019)]


def test_rights_travel_with_the_data():
    """PDGI: attribution, licence and a disclaimer ride inside every published summary."""
    from pipeline import site_data
    r = site_data.RIGHTS
    assert r["licence"].startswith("CC BY 4.0") and "Sathya Sankaran" in r["licence"]
    assert "Botanical Survey of India" in r["attribution"] and "Zoological Survey of India" in r["attribution"]
    assert "not an official" in r["disclaimer"]


def test_new_species_window_is_one_constant():
    from pipeline import layer_newspecies
    assert layer_newspecies.FIRST_YEAR == gbif.NEW_SPECIES_FROM == 2007
    for q in ("recent_history", "verbatim_names"):
        assert '"year" >= 2007' in gbif.build_sql(q)


def test_ensure_fetches_a_download_once(tmp_path, monkeypatch):
    monkeypatch.setattr(gbif, "RAW", tmp_path)
    got = []
    monkeypatch.setattr(gbif, "fetch", lambda http, meta: got.append(meta["key"]))
    gbif.ensure(None, {"key": "k", "size": 3})
    (tmp_path / "k.zip").write_bytes(b"abc")
    gbif.ensure(None, {"key": "k", "size": 3})        # complete: not fetched again
    gbif.ensure(None, {"key": "k", "size": 9})        # cut short: fetched again
    gbif.ensure(None, {"key": "k"})                   # GBIF gives no size: the file is kept
    assert got == ["k", "k"]


def test_no_unused_placeholders_in_queries():
    for q in (gbif.QUERIES).glob("*.sql"):
        assert "{excluded_unlocated}" not in q.read_text()
