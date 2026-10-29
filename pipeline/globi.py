"""GloBI (Global Biotic Interactions): which species have any recorded interaction, and which have one recorded in
India. The Eltonian gap (how species interact) of Hortal et al. 2015.

Source: GloBI's weekly snapshot of all its interactions (interactions.tsv.gz, about 2.7 GB), compiled from about 460
datasets, each with its own licence. We publish only our own counts per species, never the interaction rows, and
cite GloBI (Poelen, Simons and Mungall 2014, Ecological Informatics 24: 148-159) and its datasets.

Download: resumable (HTTP Range into a .part file), skipped when the snapshot's ETag is unchanged; progress lines
while it runs. In India: a point inside an LGD district (pipeline.places, with its 5 km tolerance at the coast), or,
with no point, a locality with the word India (not Indiana, Indian Head or "Indian subregion").

Output: species.parquet, one row per species name: records (interactions it is part of, as source or target),
partners (distinct partner species), types (interaction types), records_india, datasets (distinct source datasets).

Usage: .venv/bin/python -m pipeline.globi [--minutes 120]
"""

import argparse
import json
import time
from pathlib import Path

import duckdb
import requests

from pipeline import places

ROOT = Path(__file__).resolve().parent.parent
URL = "https://depot.globalbioticinteractions.org/snapshot/target/data/tsv/interactions.tsv.gz"
CACHE = ROOT / "data" / "cache" / "globi"
CHUNK = 8 << 20                      # bytes per write
LOG_EVERY = 256 << 20                # a progress line every 256 MB
BOX = (5.0, 38.0, 67.0, 99.0)        # lat min, lat max, lon min, lon max: points worth placing in districts


def download(http, dest: Path, url=URL, deadline=None, log=print):
    """Fetch url to dest unless dest holds the same snapshot (ETag). Resumes a .part file of the same ETag.
    True when a new snapshot was downloaded, False when there was nothing to do. A dropped connection or the time
    limit leaves the .part file for the next run."""
    head = http.head(url, timeout=60, allow_redirects=True)
    head.raise_for_status()
    etag, length = head.headers.get("ETag"), int(head.headers.get("Content-Length") or 0)
    meta, part, part_meta = Path(f"{dest}.json"), Path(f"{dest}.part"), Path(f"{dest}.part.json")
    if dest.exists() and meta.exists() and json.loads(meta.read_text()).get("etag") == etag:
        return False
    if not (part.exists() and part_meta.exists() and json.loads(part_meta.read_text()).get("etag") == etag):
        part.unlink(missing_ok=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part_meta.write_text(json.dumps({"etag": etag, "length": length}))
    start = part.stat().st_size if part.exists() else 0
    with http.get(url, headers={"Range": f"bytes={start}-"} if start else {}, stream=True, timeout=120) as r:
        r.raise_for_status()
        if start and r.status_code != 206:      # the server ignored the range: start again
            start = 0
        with open(part, "ab" if start else "wb") as f:
            got, logged = start, start
            for chunk in r.iter_content(CHUNK):
                f.write(chunk)
                got += len(chunk)
                if got - logged >= LOG_EVERY:
                    log(f"GloBI snapshot: {got >> 20} of {length >> 20} MB")
                    logged = got
                if deadline is not None and time.monotonic() > deadline:
                    log(f"time limit: {got >> 20} MB kept in {part.name}; the next run continues")
                    return None
    if length and part.stat().st_size != length:
        raise OSError(f"{part.name}: {part.stat().st_size} bytes, expected {length}; the next run continues")
    part.replace(dest)
    part_meta.unlink(missing_ok=True)
    meta.write_text(json.dumps({"etag": etag, "length": length, "url": url}))
    return True


def species_table(con, tsv: Path, districts_path, out: Path):
    """One row per species name from both sides of each interaction (see the module docstring)."""
    con.sql(f"""
        CREATE OR REPLACE TABLE gi AS
        SELECT nullif(trim(sourceTaxonSpeciesName), '') AS s, nullif(trim(targetTaxonSpeciesName), '') AS t,
               interactionTypeName AS type, TRY_CAST(decimalLatitude AS DOUBLE) AS lat,
               TRY_CAST(decimalLongitude AS DOUBLE) AS lon, localityName AS locality, sourceNamespace AS ns
        FROM read_csv('{tsv}', delim = '\t', header = true, quote = '', escape = '', all_varchar = true,
                      ignore_errors = true, null_padding = true)
        WHERE coalesce(sourceTaxonSpeciesName, '') <> '' OR coalesce(targetTaxonSpeciesName, '') <> ''""")
    lat0, lat1, lon0, lon1 = BOX
    places.place_points(con, f"(SELECT lat, lon FROM gi WHERE lat BETWEEN {lat0} AND {lat1} AND lon BETWEEN {lon0} AND {lon1})",
                        str(districts_path))
    con.sql(f"""
        COPY (
            WITH r AS (
                SELECT g.*, p.dist_lgd IS NOT NULL
                            -- the word India: not Indiana, Indian Head or the Indian subregion
                            OR (g.lat IS NULL AND regexp_matches(coalesce(g.locality, ''), '(?i)\\bindia\\b')) AS india
                FROM gi g LEFT JOIN point_district p ON p.lat = g.lat AND p.lon = g.lon),
            e AS (SELECT s AS name, t AS partner, type, india, ns FROM r WHERE s IS NOT NULL
                  UNION ALL SELECT t, s, type, india, ns FROM r WHERE t IS NOT NULL)
            SELECT name, count(*) AS records, count(DISTINCT partner) AS partners,
                   list(DISTINCT type ORDER BY type) AS types, count(*) FILTER (WHERE india) AS records_india,
                   count(DISTINCT ns) AS datasets
            FROM e GROUP BY name ORDER BY name)
        TO '{out}' (FORMAT parquet, COMPRESSION zstd)""")
    return out


def main():
    from pipeline import districts, health
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, help="stop the download after this many minutes; the next run continues")
    a = p.parse_args()
    http = requests.Session()
    http.headers["User-Agent"] = health.ua()
    deadline = time.monotonic() + a.minutes * 60 if a.minutes else None
    tsv, out = CACHE / "interactions.tsv.gz", CACHE / "species.parquet"
    got = download(http, tsv, deadline=deadline, log=lambda m: print(m, flush=True))
    if got is None:
        return
    if got or not out.exists():
        districts.ensure(health.ua())
        t = time.monotonic()
        species_table(duckdb.connect(), tsv, districts.PATH, out)
        n, india = duckdb.sql(f"SELECT count(*), count(*) FILTER (WHERE records_india > 0) FROM '{out}'").fetchone()
        print(f"{n} species with a recorded interaction, {india} with one in India ({time.monotonic() - t:.0f} s)", flush=True)
    else:
        print("GloBI snapshot unchanged; species table up to date", flush=True)


if __name__ == "__main__":
    main()
