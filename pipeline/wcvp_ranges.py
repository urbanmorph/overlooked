"""Native ranges of vascular plants from Kew's World Checklist of Vascular Plants (WCVP, CC BY 4.0): for every
species-rank name, accepted or a synonym, its accepted species, whether Kew gives that species a range, the
botanical regions of India (TDWG level 3) where it is native or introduced, and whether it is native in India or a
region next to it (near_india).

The master list uses it as a flag, never a filter (25 Nov 2026): a plant on a district's or a state's list whose
region Kew does not list as native for the species carries kew_not_native. A name Kew does not know, or a species Kew
gives no range, gets no flag.

Regions of India: IND (the mainland), ASS (Assam and the North-East), WHM (West Himalaya), EHM (East Himalaya),
AND (Andamans), NCB (Nicobars), LDV (Lakshadweep). A location Kew marks doubtful counts as native; an extinct one
too (it is still the species' range).

Cache and idempotency: Kew's zip is kept in data/cache/master/ and in R2 cache/master/wcvp.zip (never served), and
downloaded only when neither has it; the table is rebuilt only when the zip changes (its sha256 is kept beside it).

Usage: .venv/bin/python -m pipeline.wcvp_ranges [--publish]
"""

import argparse
import shutil
import zipfile
from pathlib import Path

import duckdb

from pipeline import r2, util
from pipeline.util import log

ROOT = Path(__file__).resolve().parent.parent
URL = "https://sftp.kew.org/pub/data-repositories/WCVP/wcvp.zip"
CACHE = ROOT / "data" / "cache" / "master"
ZIP_KEY, TABLE_KEY = "cache/master/wcvp.zip", "cache/master/wcvp_ranges.parquet"
# The table's layout: a new one rebuilds the table from the same zip.
LAYOUT = 2
INDIA = ["IND", "ASS", "WHM", "EHM", "AND", "NCB", "LDV"]
# Regions next to India: a species native there and recorded in India may be wild at the edge of its range, before
# Kew lists India. Pakistan, Afghanistan, Nepal, Tibet, Yunnan (China South-Central), Bangladesh, Myanmar, Sri Lanka,
# the Maldives; Thailand and Sumatra for the Andaman and Nicobar Islands.
NEAR = INDIA + ["PAK", "AFG", "NEP", "TIB", "CHC", "BAN", "MYA", "SRL", "MDV", "THA", "SUM"]


def build(zip_path: Path, out: Path):
    """The ranges table from Kew's zip, written whole; nothing is done when out was built from this same zip."""
    stamp = out.with_name(out.name + ".sha256")
    digest = f"{r2.sha256(zip_path)} layout {LAYOUT}"
    if out.exists() and stamp.exists() and stamp.read_text() == digest:
        return out
    tmp = out.parent / f"{out.stem}_unzip"
    with zipfile.ZipFile(zip_path) as z:
        names = {Path(n).name: n for n in z.namelist()}
        for f in ("wcvp_names.csv", "wcvp_distribution.csv"):
            z.extract(names[f], tmp)
    read = lambda f: f"read_csv('{tmp / names[f]}', delim = '|', header = true, quote = '', all_varchar = true)"
    india, near = (", ".join(f"'{a}'" for a in x) for x in (INDIA, NEAR))
    con = duckdb.connect()
    part = out.with_suffix(".part")
    con.sql(f"""
        COPY (
            WITH n AS (SELECT plant_name_id, taxon_rank, taxon_status, taxon_name,
                              coalesce(nullif(accepted_plant_name_id, ''), plant_name_id) AS acc_id
                       FROM {read("wcvp_names.csv")}),
            d AS (SELECT plant_name_id, area_code_l3 AS area, introduced = '1' AS introduced
                  FROM {read("wcvp_distribution.csv")} WHERE area_code_l3 IS NOT NULL),
            r AS (SELECT plant_name_id,
                         coalesce(list(DISTINCT area ORDER BY area) FILTER (WHERE NOT introduced AND area IN ({india})), [])
                             AS india_native,
                         coalesce(list(DISTINCT area ORDER BY area) FILTER (WHERE introduced AND area IN ({india})), [])
                             AS india_introduced,
                         bool_or(NOT introduced AND area IN ({near})) AS near_india
                  FROM d GROUP BY 1)
            SELECT DISTINCT s.taxon_name AS name, a.taxon_name AS accepted, r.plant_name_id IS NOT NULL AS has_range,
                   coalesce(r.india_native, []) AS india_native, coalesce(r.india_introduced, []) AS india_introduced,
                   coalesce(r.near_india, false) AS near_india
            FROM n s JOIN n a ON a.plant_name_id = s.acc_id AND a.taxon_rank = 'Species' AND a.taxon_status = 'Accepted'
            LEFT JOIN r ON r.plant_name_id = a.plant_name_id
            WHERE s.taxon_rank = 'Species'
            ORDER BY name
        ) TO '{part}' (FORMAT parquet, COMPRESSION zstd)""")
    part.replace(out)
    stamp.write_text(digest)
    shutil.rmtree(tmp, ignore_errors=True)
    n = util.value(con, f"SELECT count(*) FROM '{out}'")
    log(f"WCVP ranges: {n:,} names")
    return out


def run(http, s3=None, cache=CACHE):
    """Kew's zip (local, else R2, else Kew), then the ranges table; with s3, both kept in R2."""
    z = r2.cached_file(s3, ZIP_KEY, cache / "wcvp.zip", lambda d: util.stream(http, URL, d, kind="zip", progress_mb=20))
    if z is None:
        raise SystemExit(f"WCVP: {URL} did not answer with a zip")
    table = build(z, cache / "wcvp_ranges.parquet")
    if s3 is not None:
        r2.sync_file(s3, table, TABLE_KEY, immutable=False)
    return table


def main():
    from pipeline import health
    a = argparse.ArgumentParser()
    a.add_argument("--publish", action="store_true", help="keep the zip and the table in R2 (cache/master/)")
    args = a.parse_args()
    s3 = None
    if args.publish:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=True)
        s3 = r2.client()
    run(health.session(), s3)


if __name__ == "__main__":
    main()
