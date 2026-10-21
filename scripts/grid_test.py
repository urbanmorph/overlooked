"""Grid test: does placing records by grid cell centre give the same ledger as exact points?

Uses the fnf point download (13 Oct 2026, doi:10.15468/dl.w34hz8; India, birds and mammals
excluded) with the same filters as query A. For EQDGC levels 5, 6 and 7 it compares:
  - records placed in a different district by cell centre than by exact point
  - ledger rows (species x district) gained or lost
  - latest year changed in rows both methods share
In the north-east quadrant, an EQDGC cell at level L is floor(x * 2^L) / 2^L.

Usage: .venv/bin/python scripts/grid_test.py
"""

import json
import time
from pathlib import Path

import duckdb

from pipeline.util import first, value

ROOT = Path(__file__).resolve().parent.parent
POINTS = ROOT / "data/fnf/gbif_points_2026-10-13/0023211-260928105237408.csv"
EXCLUDED = ROOT / "pipeline/ref/excluded_datasets.csv"
DISTRICTS = ROOT / "data/ref/LGD_Districts.parquet"
OUT = ROOT / "data/build/grid_test"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(OUT / "grid_test.duckdb"))
    con.sql("INSTALL spatial; LOAD spatial; SET threads = 8")
    t = time.time()
    con.sql(f"""
        CREATE OR REPLACE TABLE pts AS
        SELECT speciesKey AS species_key, "year", basisOfRecord AS basis,
               round(decimalLatitude, 5) AS lat, round(decimalLongitude, 5) AS lon
        FROM read_csv('{POINTS}', delim = '\t', header = true, quote = '', all_varchar = false,
                      sample_size = -1, ignore_errors = true)
        WHERE speciesKey IS NOT NULL AND decimalLatitude IS NOT NULL
          AND occurrenceStatus = 'PRESENT'
          AND basisOfRecord NOT IN ('FOSSIL_SPECIMEN', 'LIVING_SPECIMEN')
          AND (coordinateUncertaintyInMeters IS NULL OR coordinateUncertaintyInMeters <= 25000)
          AND datasetKey NOT IN (SELECT datasetKey FROM read_csv('{EXCLUDED}'))
    """)
    n = first(con, "SELECT count(*), count(DISTINCT (lat, lon)) FROM pts")
    print(f"records {n[0]:,}, distinct points {n[1]:,} ({time.time() - t:.0f}s)")

    con.sql(f"CREATE OR REPLACE TABLE d AS SELECT dist_lgd, geometry FROM '{DISTRICTS}'")
    # Exact point -> district, once per distinct coordinate.
    t = time.time()
    con.sql("""
        CREATE OR REPLACE TABLE pt_district AS
        WITH u AS (SELECT DISTINCT lat, lon FROM pts)
        SELECT u.lat, u.lon, min(d.dist_lgd) AS dist_lgd
        FROM u LEFT JOIN d ON ST_Contains(d.geometry, ST_Point(u.lon, u.lat))
        GROUP BY u.lat, u.lon
    """)
    print(f"points placed ({time.time() - t:.0f}s)")

    results = {}
    for level in (5, 6, 7):
        k = 2 ** level
        t = time.time()
        con.sql(f"""
            CREATE OR REPLACE TABLE cell_district AS
            WITH c AS (SELECT DISTINCT floor(lon * {k}) AS cx, floor(lat * {k}) AS cy FROM pts)
            SELECT c.cx, c.cy, min(d.dist_lgd) AS dist_lgd
            FROM c LEFT JOIN d ON ST_Contains(d.geometry, ST_Point((c.cx + 0.5) / {k}, (c.cy + 0.5) / {k}))
            GROUP BY c.cx, c.cy
        """)
        con.sql(f"""
            CREATE OR REPLACE TABLE placed AS
            SELECT p.species_key, p."year", pd.dist_lgd AS by_point, cd.dist_lgd AS by_cell
            FROM pts p
            JOIN pt_district pd USING (lat, lon)
            JOIN cell_district cd ON cd.cx = floor(p.lon * {k}) AND cd.cy = floor(p.lat * {k})
        """)
        r = first(con, """
            SELECT count(*) AS records,
                   count(*) FILTER (WHERE by_point IS NOT NULL AND by_cell IS NOT NULL AND by_point <> by_cell) AS other_district,
                   count(*) FILTER (WHERE by_point IS NOT NULL AND by_cell IS NULL) AS lost_to_sea,
                   count(*) FILTER (WHERE by_point IS NULL AND by_cell IS NOT NULL) AS gained_from_sea,
                   count(*) FILTER (WHERE by_point IS NULL AND by_cell IS NULL) AS outside_both
            FROM placed
        """)
        ledgers = first(con, """
            WITH a AS (SELECT species_key, by_point AS dist, max("year") AS last_year FROM placed
                       WHERE by_point IS NOT NULL GROUP BY ALL),
                 b AS (SELECT species_key, by_cell AS dist, max("year") AS last_year FROM placed
                       WHERE by_cell IS NOT NULL GROUP BY ALL)
            SELECT (SELECT count(*) FROM a),
                   (SELECT count(*) FROM b),
                   (SELECT count(*) FROM a ANTI JOIN b USING (species_key, dist)),
                   (SELECT count(*) FROM b ANTI JOIN a USING (species_key, dist)),
                   (SELECT count(*) FROM a JOIN b USING (species_key, dist)
                    WHERE a.last_year IS DISTINCT FROM b.last_year),
                   (SELECT count(*) FROM a JOIN b USING (species_key, dist)
                    WHERE (a.last_year < 1980) IS DISTINCT FROM (b.last_year < 1980))
        """)
        cube_rows = value(con, f"SELECT count(*) FROM (SELECT DISTINCT species_key, floor(lon * {k}), floor(lat * {k}) FROM pts)")
        res = {
            "cell_km_approx": round(111 / k, 2),
            "records": r[0],
            "other_district_pct": round(100 * r[1] / r[0], 3),
            "lost_to_sea_pct": round(100 * r[2] / r[0], 3),
            "gained_from_sea_pct": round(100 * r[3] / r[0], 3),
            "outside_both_pct": round(100 * r[4] / r[0], 3),
            "ledger_rows_by_point": ledgers[0],
            "ledger_rows_by_cell": ledgers[1],
            "rows_only_by_point_pct": round(100 * ledgers[2] / ledgers[0], 3),
            "rows_only_by_cell_pct": round(100 * ledgers[3] / ledgers[0], 3),
            "shared_rows_last_year_differs": ledgers[4],
            "shared_rows_quiet_flag_differs": ledgers[5],
            "cube_rows_species_x_cell": cube_rows,
        }
        results[f"level_{level}"] = res
        print(f"level {level} ({time.time() - t:.0f}s):", json.dumps(res))
    (OUT / "results.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
