"""Biogeographic zones and provinces of India (Wildlife Institute of India): the fixed list and point placement."""

import duckdb
import pytest

from pipeline import biogeo


@pytest.fixture
def zones(tmp_path):
    """Two square provinces side by side: 5B covers lon 76-77, 6E covers lon 77-78 (lat 10-11)."""
    path = tmp_path / "zones.parquet"
    con = duckdb.connect()
    con.sql("INSTALL spatial; LOAD spatial")
    con.sql(f"""COPY (SELECT '5B' AS prov_code, ST_MakeEnvelope(76, 10, 77, 11) AS geometry
                      UNION ALL SELECT '6E', ST_MakeEnvelope(77, 10, 78, 11)) TO '{path}' (FORMAT parquet)""")
    return path


def test_the_list_has_ten_zones_and_26_provinces():
    assert len(biogeo.PROVINCES) == 26 and len({c for c, _, _ in biogeo.PROVINCES}) == 26
    assert len({z for _, _, z in biogeo.PROVINCES}) == 10
    assert ("5B", "Western Ghats: Mountains", "Western Ghats") in biogeo.PROVINCES


def test_points_take_the_province_they_are_in_or_one_near(zones):
    con = duckdb.connect()
    con.sql("""CREATE TABLE pts AS SELECT * FROM (VALUES
                 (10.5, 76.5),    -- inside 5B
                 (10.5, 77.5),    -- inside 6E
                 (10.5, 75.98),   -- about 2 km west of 5B: near, so 5B
                 (10.5, 74.0))    -- far out: no province
               t(lat, lon)""")
    biogeo.place(con, "pts", zones)
    got = {(float(lat), float(lon)): p for lat, lon, p in con.sql("SELECT lat, lon, prov FROM point_province").fetchall()}
    assert got == {(10.5, 76.5): "5B", (10.5, 77.5): "6E", (10.5, 75.98): "5B", (10.5, 74.0): None}


def test_the_file_matches_the_list():
    if not biogeo.PATH.exists():
        pytest.skip("the WII file is not on disk (pipeline.biogeo.ensure downloads it)")
    con = duckdb.connect()
    rows = set(con.sql(f"SELECT prov_code, biogeoprov, biogeozone FROM '{biogeo.PATH}'").fetchall())
    assert rows == set(biogeo.PROVINCES)
