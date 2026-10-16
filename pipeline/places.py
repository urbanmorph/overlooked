"""Place rounded points in LGD districts.

A point inside a district polygon takes that district. District outlines are simplified, so
points on the shore or around islands can fall just outside: a point within NEAR_KM of a district
takes the nearest one and is flagged. Points further out are offshore (NULL district).
"""

import duckdb

NEAR_KM = 5
# Rough degrees for the search box; distances are then measured in metres on the sphere.
NEAR_DEG = NEAR_KM / 100


def load_districts(con: duckdb.DuckDBPyConnection, districts_path: str):
    """Create table districts. Two districts have no LGD code (both 0 in the source):
    Muzaffarabad and Mirpur get -1 and -2 so every district has its own code."""
    con.sql("INSTALL spatial; LOAD spatial")
    con.sql(f"""
        CREATE OR REPLACE TABLE districts AS
        SELECT CASE WHEN dist_lgd = 0 AND dtname = 'Muzaffarabad' THEN -1
                    WHEN dist_lgd = 0 AND dtname = 'Mirpur' THEN -2
                    ELSE dist_lgd END AS dist_lgd,
               state_lgd, dtname, stname, geometry
        FROM '{districts_path}'
    """)
    dupes = con.sql("SELECT count(*) - count(DISTINCT dist_lgd) FROM districts").fetchone()[0]
    if dupes:
        raise ValueError(f"{dupes} duplicate district codes in {districts_path}")


def place_points(con: duckdb.DuckDBPyConnection, points_rel: str, districts_path: str):
    """Create table point_district (lat, lon, dist_lgd, state_lgd, how) for the distinct
    (lat, lon) pairs in points_rel. how is 'inside', 'near' or 'offshore'."""
    load_districts(con, districts_path)
    con.sql(f"CREATE OR REPLACE TABLE upts AS SELECT DISTINCT lat, lon FROM {points_rel} WHERE lat IS NOT NULL")
    con.sql("""
        CREATE OR REPLACE TABLE inside AS
        SELECT u.lat, u.lon, min(d.dist_lgd) AS dist_lgd
        FROM upts u JOIN districts d ON ST_Contains(d.geometry, ST_Point(u.lon, u.lat))
        GROUP BY u.lat, u.lon
    """)
    con.sql(f"""
        CREATE OR REPLACE TABLE near AS
        WITH rest AS (SELECT lat, lon FROM upts ANTI JOIN inside USING (lat, lon))
        SELECT r.lat, r.lon,
               arg_min(d.dist_lgd, ST_Distance_Sphere(ST_Point(r.lat, r.lon),
                       ST_FlipCoordinates(ST_ClosestPoint(d.geometry, ST_Point(r.lon, r.lat))))) AS dist_lgd,
               min(ST_Distance_Sphere(ST_Point(r.lat, r.lon),
                       ST_FlipCoordinates(ST_ClosestPoint(d.geometry, ST_Point(r.lon, r.lat))))) AS metres
        FROM rest r JOIN districts d
          ON ST_DWithin(d.geometry, ST_Point(r.lon, r.lat), {NEAR_DEG})
        GROUP BY r.lat, r.lon
    """)
    con.sql(f"""
        CREATE OR REPLACE TABLE point_district AS
        SELECT u.lat, u.lon,
               coalesce(i.dist_lgd, CASE WHEN n.metres <= {NEAR_KM * 1000} THEN n.dist_lgd END) AS dist_lgd,
               CASE WHEN i.dist_lgd IS NOT NULL THEN 'inside'
                    WHEN n.metres <= {NEAR_KM * 1000} THEN 'near'
                    ELSE 'offshore' END AS how
        FROM upts u
        LEFT JOIN inside i USING (lat, lon)
        LEFT JOIN near n USING (lat, lon)
    """)
    con.sql("""
        CREATE OR REPLACE TABLE point_district AS
        SELECT p.*, d.state_lgd FROM point_district p LEFT JOIN districts d USING (dist_lgd)
    """)
