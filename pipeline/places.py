"""Place rounded points in LGD districts.

A point inside a district polygon takes that district. District outlines are simplified, so
points on the shore or around islands can fall just outside: a point within NEAR_KM of a district
takes the nearest one and is flagged. Points further out are offshore (NULL district).
"""

import duckdb

from pipeline.util import value

NEAR_KM = 5
# Rough degrees for the search box; distances are then measured in metres on the sphere.
NEAR_DEG = NEAR_KM / 100


def load_districts(con: duckdb.DuckDBPyConnection, districts_path: str):
    """Create table districts. Two districts have no LGD code (both 0 in the source):
    Muzaffarabad and Mirpur get -1 and -2 so every district has its own code."""
    con.sql("INSTALL spatial; LOAD spatial")
    con.sql("SET geometry_always_xy = true")  # points are (lon, lat); duckdb 2.0 needs this said, 2.1 makes it default
    con.sql(f"""
        CREATE OR REPLACE TABLE districts AS
        SELECT CASE WHEN dist_lgd = 0 AND dtname = 'Muzaffarabad' THEN -1
                    WHEN dist_lgd = 0 AND dtname = 'Mirpur' THEN -2
                    ELSE dist_lgd END AS dist_lgd,
               state_lgd, dtname, stname, geometry
        FROM '{districts_path}'
    """)
    dupes = value(con, "SELECT count(*) - count(DISTINCT dist_lgd) FROM districts")
    if dupes:
        raise ValueError(f"{dupes} duplicate district codes in {districts_path}")


def place_in(con: duckdb.DuckDBPyConnection, upts: str, polygons: str, code: str, out: str):
    """Create table out (lat, lon, <code>, how) for the points of table upts (distinct lat, lon): the code of the
    polygon of table polygons (<code>, geometry) that holds the point, else of the nearest one within NEAR_KM ('near'),
    else NULL ('offshore')."""
    con.sql(f"""
        CREATE OR REPLACE TABLE _inside AS
        SELECT u.lat, u.lon, min(p.{code}) AS code
        FROM {upts} u JOIN {polygons} p ON ST_Contains(p.geometry, ST_Point(u.lon, u.lat))
        GROUP BY u.lat, u.lon
    """)
    con.sql(f"""
        CREATE OR REPLACE TABLE _near AS
        WITH rest AS (SELECT lat, lon FROM {upts} ANTI JOIN _inside USING (lat, lon))
        SELECT r.lat, r.lon,
               arg_min(p.{code}, ST_Distance_Sphere(ST_Point(r.lon, r.lat),
                       ST_ClosestPoint(p.geometry, ST_Point(r.lon, r.lat)))) AS code,
               min(ST_Distance_Sphere(ST_Point(r.lon, r.lat),
                       ST_ClosestPoint(p.geometry, ST_Point(r.lon, r.lat)))) AS metres
        FROM rest r JOIN {polygons} p
          ON ST_DWithin(p.geometry, ST_Point(r.lon, r.lat), {NEAR_DEG})
        GROUP BY r.lat, r.lon
    """)
    con.sql(f"""
        CREATE OR REPLACE TABLE {out} AS
        SELECT u.lat, u.lon,
               coalesce(i.code, CASE WHEN n.metres <= {NEAR_KM * 1000} THEN n.code END) AS {code},
               CASE WHEN i.code IS NOT NULL THEN 'inside'
                    WHEN n.metres <= {NEAR_KM * 1000} THEN 'near'
                    ELSE 'offshore' END AS how
        FROM {upts} u
        LEFT JOIN _inside i USING (lat, lon)
        LEFT JOIN _near n USING (lat, lon)
    """)
    con.sql("DROP TABLE _inside; DROP TABLE _near")


def place_points(con: duckdb.DuckDBPyConnection, points_rel: str, districts_path: str):
    """Create table point_district (lat, lon, dist_lgd, how, state_lgd) for the distinct (lat, lon) pairs in
    points_rel. how is 'inside', 'near' or 'offshore'."""
    load_districts(con, districts_path)
    con.sql(f"CREATE OR REPLACE TABLE upts AS SELECT DISTINCT lat, lon FROM {points_rel} WHERE lat IS NOT NULL")
    place_in(con, "upts", "districts", "dist_lgd", "point_district")
    con.sql("""
        CREATE OR REPLACE TABLE point_district AS
        SELECT p.*, d.state_lgd FROM point_district p LEFT JOIN districts d USING (dist_lgd)
    """)
