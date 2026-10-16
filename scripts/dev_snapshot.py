"""Development snapshot from the fnf point download, laid out like R2, for building the site locally.

Not for publishing: birds and mammals are missing from this download, and it is not a monthly run.

Usage: .venv/bin/python scripts/dev_snapshot.py
Output: data/publish-dev/ (serve with scripts/serve.py)
"""

import json
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import boundaries, ledger, site_data  # noqa: E402
from pipeline.districts import PATH as DISTRICTS  # noqa: E402

POINTS = ROOT / "data/fnf/gbif_points_2026-10-13/0023211-260928105237408.csv"
EXCLUDED = ROOT / "pipeline/ref/excluded_datasets.csv"
PUB = ROOT / "data/publish-dev"
RUN = "dev-fnf"


def main():
    t = time.time()
    out = PUB / "snapshots" / RUN
    con = duckdb.connect()
    con.sql(f"""
        CREATE TABLE pts AS
        SELECT speciesKey AS specieskey, species AS name, kingdom, phylum, class, "order", family,
               "year", round(decimalLatitude, 3) AS lat, round(decimalLongitude, 3) AS lon
        FROM read_csv('{POINTS}', delim = '\t', header = true, quote = '', sample_size = -1, ignore_errors = true)
        WHERE speciesKey IS NOT NULL AND decimalLatitude IS NOT NULL AND occurrenceStatus = 'PRESENT'
          AND basisOfRecord NOT IN ('FOSSIL_SPECIMEN', 'LIVING_SPECIMEN')
          AND (coordinateUncertaintyInMeters IS NULL OR coordinateUncertaintyInMeters <= 25000)
          AND datasetKey NOT IN (SELECT datasetKey FROM read_csv('{EXCLUDED}'))
    """)
    con.sql("""CREATE TABLE cube AS SELECT specieskey, lat, lon, min("year")::INT AS first_year,
               max("year")::INT AS last_year, count(*) AS n_records FROM pts GROUP BY ALL""")
    con.sql("""CREATE TABLE species AS SELECT specieskey AS species_key, any_value(name) AS name, any_value(kingdom) AS kingdom,
               any_value(phylum) AS phylum, any_value(class) AS class, any_value("order") AS "order",
               any_value(family) AS family FROM pts GROUP BY specieskey""")
    stats = ledger.build(con, out, "fnf point download, doi:10.15468/dl.w34hz8", DISTRICTS)
    con.sql(f"COPY species TO '{out / 'species.parquet'}' (FORMAT parquet, COMPRESSION zstd)")
    meta = {
        "run_id": RUN,
        "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dev": True,
        "taxon_ids": "gbif",
        "dev_note": "Development data: fnf download of 13 October 2026. Birds and mammals are not included.",
        "dois": ["10.15468/dl.w34hz8"],
        "gbif_snapshot": "2026-10-13",
        "col_release": "COL26.9 XR (25 September 2026)",
    }
    summary = site_data.build(con, out, meta)
    (out / "manifest.json").write_text(json.dumps({"run_id": RUN, "stats": stats, **meta}, indent=1))
    bdir = PUB / "boundaries" / "lgd-2026-10"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "districts_map.json").write_text(json.dumps(boundaries.build(), separators=(",", ":")))
    latest = {"run_id": RUN, "built": meta["built"], "summary": f"snapshots/{RUN}/summary.json",
              "manifest": f"snapshots/{RUN}/manifest.json", "boundaries": "boundaries/lgd-2026-10/districts_map.json",
              "base": f"snapshots/{RUN}/"}
    (PUB / "latest.json").write_text(json.dumps(latest, indent=1))
    print(json.dumps({k: summary[k] for k in ("species", "records", "districts_with_records", "quiet_species")}),
          f"{time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
