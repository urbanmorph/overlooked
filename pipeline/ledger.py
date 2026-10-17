"""Build the ledger (species x LGD district) from a query A download.

species_key is a Catalogue of Life (XR) taxon ID, a short text code such as 5VKF2: GBIF SQL
downloads use the COL taxonomy (checked 16 October 2026).

Usage:
    .venv/bin/python -m pipeline.ledger <download key> [--out data/build/<key>]
"""

import argparse
import json
import zipfile
from pathlib import Path

import duckdb

from pipeline.places import place_points

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DISTRICTS = ROOT / "data" / "ref" / "LGD_Districts.parquet"


def unpack(key):
    dest = RAW / key
    if not dest.exists():
        with zipfile.ZipFile(RAW / f"{key}.zip") as z:
            z.extractall(dest)
    files = [p for p in dest.iterdir() if p.is_file()]
    if len(files) != 1:
        raise RuntimeError(f"expected one file in {dest}, found {[p.name for p in files]}")
    return files[0]


def load_cube(con, tsv):
    con.sql(f"""
        CREATE OR REPLACE TABLE cube AS
        SELECT * FROM read_csv('{tsv}', delim = '\t', header = true,
            columns = {{'specieskey': 'VARCHAR', 'lat': 'DOUBLE', 'lon': 'DOUBLE', 'first_year': 'INTEGER',
                        'last_year': 'INTEGER', 'n_records': 'BIGINT'}})
    """)
    # Merged duplicate keys (names.merge_duplicates), when that step has run.
    if con.sql("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'key_map'").fetchone()[0]:
        con.sql("UPDATE cube SET specieskey = m.canonical FROM key_map m WHERE cube.specieskey = m.species_key")


def build(con, out: Path, label: str, districts: Path = DISTRICTS):
    """Build from table cube (specieskey, lat, lon, first_year, last_year, n_records)."""
    out.mkdir(parents=True, exist_ok=True)
    place_points(con, "cube", str(districts))
    con.sql("""
        CREATE OR REPLACE TABLE ledger AS
        SELECT q.specieskey AS species_key, p.dist_lgd AS district_lgd, p.state_lgd,
               min(q.first_year) AS first_year, max(q.last_year) AS last_year,
               sum(q.n_records) AS n_records,
               coalesce(sum(q.n_records) FILTER (WHERE p.how = 'near'), 0) AS n_records_near_shore
        FROM cube q JOIN point_district p USING (lat, lon)
        WHERE p.dist_lgd IS NOT NULL
        GROUP BY ALL
        ORDER BY state_lgd, district_lgd, species_key
    """)
    path = out / "ledger.parquet"
    con.sql(f"COPY ledger TO '{path}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100000)")

    one = lambda s: con.sql(s).fetchone()[0]
    by_how = dict(con.sql("""SELECT how, sum(n_records) FROM cube JOIN point_district USING (lat, lon)
                             GROUP BY how""").fetchall())
    stats = {
        "source": label,
        "cube_rows": one("SELECT count(*) FROM cube"),
        "records": one("SELECT sum(n_records) FROM cube"),
        "records_no_year": one("SELECT coalesce(sum(n_records), 0) FROM cube WHERE last_year IS NULL"),
        "species": one("SELECT count(DISTINCT specieskey) FROM cube"),
        "points": one("SELECT count(*) FROM point_district"),
        "records_inside": by_how.get("inside", 0),
        "records_near_shore": by_how.get("near", 0),
        "records_offshore": by_how.get("offshore", 0),
        "ledger_rows": one("SELECT count(*) FROM ledger"),
        "districts": one("SELECT count(DISTINCT district_lgd) FROM ledger"),
        "ledger_bytes": path.stat().st_size,
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=1))
    con.sql("""
        CREATE OR REPLACE TABLE by_district AS
        SELECT l.district_lgd, any_value(d.dtname) AS district, any_value(d.stname) AS state,
               count(*) AS species, sum(n_records) AS records,
               count(*) FILTER (WHERE last_year < 1980) AS quiet_since_1980
        FROM ledger l JOIN districts d ON d.dist_lgd = l.district_lgd
        GROUP BY ALL ORDER BY records DESC
    """)
    con.sql(f"COPY by_district TO '{out / 'by_district.csv'}' (HEADER)")
    return stats


def main():
    p = argparse.ArgumentParser()
    p.add_argument("key")
    p.add_argument("--out")
    a = p.parse_args()
    out = Path(a.out) if a.out else ROOT / "data" / "build" / a.key
    con = duckdb.connect()
    load_cube(con, unpack(a.key))
    stats = build(con, out, f"GBIF download {a.key}")
    print(json.dumps(stats, indent=1))
    print(con.sql("SELECT * FROM by_district").fetchall())


if __name__ == "__main__":
    main()
