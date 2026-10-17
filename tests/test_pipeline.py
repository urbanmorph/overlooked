import json

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


def test_unsurveyed_groups_are_not_counted_as_quiet(tmp_path):
    from pipeline import site_data
    con = duckdb.connect()
    # District 101: one fern recorded in 1950 only, ferns never recorded there since 1980 (unsurveyed);
    # one orchid last seen 1950 while another orchid was seen in 2020 (quiet, counted).
    con.sql("""CREATE TABLE ledger AS SELECT * FROM (VALUES
        ('F1', 101, 32, 1950, 1950, 1), ('O1', 101, 32, 1950, 1950, 1), ('O2', 101, 32, 2020, 2020, 1))
        t(species_key, district_lgd, state_lgd, first_year, last_year, n_records)""")
    con.sql("""CREATE TABLE species AS SELECT * FROM (VALUES
        ('F1', 'Fern one', 'Plantae', 'Tracheophyta', 'Polypodiopsida', 'Polypodiales', 'Pteridaceae'),
        ('O1', 'Orchid one', 'Plantae', 'Tracheophyta', 'Liliopsida', 'Asparagales', 'Orchidaceae'),
        ('O2', 'Orchid two', 'Plantae', 'Tracheophyta', 'Liliopsida', 'Asparagales', 'Orchidaceae'))
        t(species_key, name, kingdom, phylum, class, "order", family)""")
    con.sql("CREATE TABLE districts AS SELECT 101 AS dist_lgd")
    summary = site_data.build(con, tmp_path, {"run_id": "t"})
    d = json.loads((tmp_path / "map_stats.json").read_text())["districts"]["101"]
    assert d["q"][0][0] == 1   # only the orchid counts as quiet since 1980
    assert d["u"][0][0] == 1   # the fern is set apart
    assert summary["districts_with_quiet"]["1980"] == 1


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


def test_change_feed(tmp_path):
    from pipeline import changes
    con = duckdb.connect()
    # Last month: orchid A quiet in 101 (1950) while orchid B active there (2015); C only in state 32;
    # D last seen 1997 (not yet 30 years); E in 102; F under an old key renamed this month.
    con.sql("""CREATE TABLE p AS SELECT * FROM (VALUES
        ('A', 101, 32, 1900, 1950, 1), ('B', 101, 32, 2015, 2015, 1), ('C', 101, 32, 2010, 2010, 1),
        ('D', 101, 32, 1990, 1996, 1), ('E', 102, 32, 2000, 2000, 1), ('F_old', 101, 32, 2001, 2001, 1))
        t(species_key, district_lgd, state_lgd, first_year, last_year, n_records)""")
    con.sql(f"COPY p TO '{tmp_path / 'pl.parquet'}' (FORMAT parquet)")
    con.sql("""CREATE TABLE ps AS SELECT * FROM (VALUES ('A','Orchid a'),('B','Orchid b'),('C','Orchid c'),
        ('D','Orchid d'),('E','Orchid e'),('F_old','Orchid f')) t(species_key, name)""")
    con.sql(f"COPY ps TO '{tmp_path / 'ps.parquet'}' (FORMAT parquet)")
    # This month: A recorded again (2026); C now also in state 29; D unchanged but a year passed;
    # E withdrawn; F under a new key.
    con.sql("""CREATE TABLE ledger AS SELECT * FROM (VALUES
        ('A', 101, 32, 1900, 2026, 2), ('B', 101, 32, 2015, 2015, 1), ('C', 101, 32, 2010, 2010, 1),
        ('C', 201, 29, 2019, 2019, 1), ('D', 101, 32, 1990, 1996, 1), ('F_new', 101, 32, 2001, 2001, 1))
        t(species_key, district_lgd, state_lgd, first_year, last_year, n_records)""")
    con.sql("""CREATE TABLE species AS SELECT * FROM (VALUES ('A','Orchid a'),('B','Orchid b'),('C','Orchid c'),
        ('D','Orchid d'),('F_new','Orchid f')) t(species_key, name)""")
    con.sql("CREATE TABLE sp AS SELECT species_key, name, 'Plants: orchids' AS grp FROM species")
    counts = changes.build(con, tmp_path / "pl.parquet", tmp_path / "ps.parquet", prev_year=2026, this_year=2027)
    got = {(r[0], r[1]) for r in con.sql("SELECT change, species_key FROM changes").fetchall()}
    assert ("recorded_again", "A") in got
    assert ("first_in_state", "C") in got
    assert ("now_quiet", "D") in got           # 1996 < 2027 - 30, and was not before
    assert ("withdrawn", "E") in got
    assert not any(k in ("F_old", "F_new") for _, k in got)   # renamed key matched by name: no change
    assert con.sql("SELECT reason FROM changes WHERE species_key = 'A'").fetchone()[0] == "new record"
    assert counts == {c: n for c, n in con.sql("SELECT change, count(*) FROM changes GROUP BY 1").fetchall()}


def test_new_species_names():
    from pipeline.layer_newspecies import binomial, merge, SP_NOV
    assert binomial("Cycas dharmrajii L.J.Singh") == "Cycas dharmrajii"
    assert binomial("CYCAS") is None and binomial("the species") is None
    assert SP_NOV.match("sp. nov.") and SP_NOV.match("nov.sp") and not SP_NOV.match("comb. nov.")
    m = merge([{"name": "A b", "year": 2019, "source": "Plazi", "journal": "Zootaxa", "state": "", "link": "p"},
               {"name": "A b", "year": 2018, "source": "BSI Plant Discoveries", "journal": "", "state": "Kerala", "link": "b"}])
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
