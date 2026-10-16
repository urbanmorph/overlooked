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
