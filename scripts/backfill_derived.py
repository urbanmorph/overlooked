"""Add page files that a later code version derives, to an already published snapshot.

Only new files are written; existing files in the snapshot are never changed. The new files are
computed from the snapshot's own published Parquet files, so they hold nothing the snapshot did not.

Usage: .venv/bin/python scripts/backfill_derived.py <run_id> [--publish]
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import districts, gbif, r2, site_data  # noqa: E402
from pipeline.places import load_districts  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run_id")
    p.add_argument("--publish", action="store_true")
    a = p.parse_args()
    gbif.session()  # loads .env locally
    s3 = r2.client()
    prefix = f"snapshots/{a.run_id}/"
    work = ROOT / "data" / "backfill" / a.run_id
    work.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    for t in ("ledger", "species", "species_decade"):
        f = work / f"{t}.parquet"
        if not f.exists():
            s3.download_file(r2.bucket(), prefix + f"{t}.parquet", str(f))
        con.sql(f"CREATE TABLE {t} AS SELECT * FROM '{f}'")
    districts.ensure("overlooked-india")
    load_districts(con, str(districts.PATH))
    summary = r2.get_json(s3, prefix + "summary.json")
    out = work / "out"
    site_data.build(con, out, {"run_id": a.run_id})  # recreates tables sp, gidx, lg; files here are not uploaded
    n = site_data.species_shards(con, out)
    new = sorted((out / "species").glob("*.json"))
    if not r2.exists(s3, prefix + "changes.json"):
        site_data.changes_json(con, out, None, None, summary)
        new.append(out / "changes.json")
    print(f"{n} species in {len(new)} new files")
    if a.publish:
        sent = 0
        for f in new:
            key = prefix + f.relative_to(out).as_posix()
            if r2.exists(s3, key):
                continue  # never change a published file
            r2.sync_file(s3, f, key)
            sent += 1
        print(f"uploaded {sent} new files to {prefix}")


if __name__ == "__main__":
    main()
