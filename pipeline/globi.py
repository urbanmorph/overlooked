"""GloBI (Global Biotic Interactions): which species have any recorded interaction, and which have one recorded in
India. The Eltonian gap (how species interact) of Hortal et al. 2015.

Source: GloBI's weekly snapshot of all its interactions (interactions.tsv.gz, about 2.7 GB), compiled from about 460
datasets, each with its own licence. We publish our own counts per species and, on species pages, the names of a
species' partners by kind of link (owner's decision, 30 October 2026), never the interaction rows, and cite GloBI
(Poelen, Simons and Mungall 2014, Ecological Informatics 24: 148-159) and its datasets.

Download: resumable (HTTP Range into a .part file), skipped when the snapshot's ETag is unchanged; progress lines
while it runs. In India: a point inside an LGD district (pipeline.places, with its 5 km tolerance at the coast), or,
with no point, a locality with the word India (not Indiana, Indian Head or "Indian subregion").

Output: species.parquet, one row per species name: records (interactions it is part of, as source or target),
partners (distinct partner species), types (interaction types), records_india, datasets (distinct source datasets).
edges.parquet, one row per species, partner and interaction type: outgoing (what the species does to the partner, or
false: what the partner does to it), the partner's kingdom and class (as GloBI gives them), records, records_india.

Weekly on GitHub Actions (globi.yml, --publish): the snapshot's ETag is kept in R2 next to the table
(cache/globi/meta.json, cache/globi/species.parquet; R2's cache/ is never served), so a week with no new snapshot
downloads nothing. The 2.7 GB snapshot itself is never stored in R2.

Usage: .venv/bin/python -m pipeline.globi [--minutes 120] [--publish]
"""

import argparse
import json
import time
from pathlib import Path

import duckdb
import requests

from pipeline import places
from pipeline.util import first

ROOT = Path(__file__).resolve().parent.parent
URL = "https://depot.globalbioticinteractions.org/snapshot/target/data/tsv/interactions.tsv.gz"
CACHE = ROOT / "data" / "cache" / "globi"
R2_PREFIX = "cache/globi/"
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


def species_table(con, tsv: Path, districts_path, out: Path, edges: Path | None = None):
    """One row per species name from both sides of each interaction (see the module docstring); with edges, also the
    partner table."""
    con.sql(f"""
        CREATE OR REPLACE TABLE gi AS
        SELECT nullif(trim(sourceTaxonSpeciesName), '') AS s, nullif(trim(targetTaxonSpeciesName), '') AS t,
               interactionTypeName AS type, TRY_CAST(decimalLatitude AS DOUBLE) AS lat,
               TRY_CAST(decimalLongitude AS DOUBLE) AS lon, localityName AS locality, sourceNamespace AS ns,
               nullif(sourceTaxonKingdomName, '') AS sk, nullif(sourceTaxonClassName, '') AS sc,
               nullif(targetTaxonKingdomName, '') AS tk, nullif(targetTaxonClassName, '') AS tc
        FROM read_csv('{tsv}', delim = '\t', header = true, quote = '', escape = '', all_varchar = true,
                      ignore_errors = true, null_padding = true)
        WHERE coalesce(sourceTaxonSpeciesName, '') <> '' OR coalesce(targetTaxonSpeciesName, '') <> ''""")
    lat0, lat1, lon0, lon1 = BOX
    places.place_points(con, f"(SELECT lat, lon FROM gi WHERE lat BETWEEN {lat0} AND {lat1} AND lon BETWEEN {lon0} AND {lon1})",
                        str(districts_path))
    con.sql("""
        CREATE OR REPLACE VIEW r AS
        SELECT g.*, p.dist_lgd IS NOT NULL
                    -- the word India: not Indiana, Indian Head or the Indian subregion
                    OR (g.lat IS NULL AND regexp_matches(coalesce(g.locality, ''), '(?i)\\bindia\\b')) AS india
        FROM gi g LEFT JOIN point_district p ON p.lat = g.lat AND p.lon = g.lon""")
    # Both sides of each interaction: what a species does (outgoing), and what is done to it.
    con.sql("""CREATE OR REPLACE VIEW e AS
               SELECT s AS name, t AS partner, type, india, ns, true AS outgoing, tk AS pkingdom, tc AS pclass
               FROM r WHERE s IS NOT NULL
               UNION ALL SELECT t, s, type, india, ns, false, sk, sc FROM r WHERE t IS NOT NULL""")
    con.sql(f"""
        COPY (
            SELECT name, count(*) AS records, count(DISTINCT partner) AS partners,
                   list(DISTINCT type ORDER BY type) AS types, count(*) FILTER (WHERE india) AS records_india,
                   count(DISTINCT ns) AS datasets
            FROM e GROUP BY name ORDER BY name)
        TO '{out}' (FORMAT parquet, COMPRESSION zstd)""")
    if edges:
        con.sql(f"""
            COPY (SELECT name, partner, type, outgoing, any_value(pkingdom) AS pkingdom, any_value(pclass) AS pclass,
                         count(*) AS records, count(*) FILTER (WHERE india) AS records_india
                  FROM e WHERE partner IS NOT NULL AND partner <> name GROUP BY ALL ORDER BY name, partner, type)
            TO '{edges}' (FORMAT parquet, COMPRESSION zstd)""")
    return out


def refresh(http, s3, cache: Path, districts_path, deadline=None, log=print):
    """The species table in R2 for the current snapshot. "unchanged" when R2 already has it (nothing downloaded),
    "published" when it was built and uploaded, "stopped" at the time limit (the .part file stays)."""
    from pipeline import r2
    head = http.head(URL, timeout=60, allow_redirects=True)
    head.raise_for_status()
    etag = head.headers.get("ETag")
    if ((r2.get_json(s3, R2_PREFIX + "meta.json") or {}).get("etag") == etag
            and all(r2.exists(s3, R2_PREFIX + n) for n in ("species.parquet", "edges.parquet"))):
        return "unchanged"
    tsv, out, edges = cache / "interactions.tsv.gz", cache / "species.parquet", cache / "edges.parquet"
    if download(http, tsv, deadline=deadline, log=log) is None:
        return "stopped"
    species_table(duckdb.connect(), tsv, districts_path, out, edges)
    for p in (out, edges):
        r2.sync_file(s3, p, R2_PREFIX + p.name, immutable=False)
    r2.put_json(s3, {"etag": etag, "url": URL}, R2_PREFIX + "meta.json")   # last: it marks the table as current
    return "published"


def main():
    from pipeline import districts, health
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, help="stop the download after this many minutes; the next run continues")
    p.add_argument("--publish", action="store_true", help="keep the species table in R2 (cache/globi/)")
    a = p.parse_args()
    http = requests.Session()
    http.headers["User-Agent"] = health.ua()
    deadline = time.monotonic() + a.minutes * 60 if a.minutes else None
    if a.publish:
        from dotenv import load_dotenv

        from pipeline import r2
        load_dotenv(ROOT / ".env", override=True)
        districts.ensure(health.ua())
        print(f"GloBI: {refresh(http, r2.client(), CACHE, districts.PATH, deadline, log=lambda m: print(m, flush=True))}", flush=True)
        return
    tsv, out = CACHE / "interactions.tsv.gz", CACHE / "species.parquet"
    got = download(http, tsv, deadline=deadline, log=lambda m: print(m, flush=True))
    if got is None:
        return
    if got or not out.exists():
        districts.ensure(health.ua())
        t = time.monotonic()
        species_table(duckdb.connect(), tsv, districts.PATH, out)
        n, india = first(duckdb.connect(), f"SELECT count(*), count(*) FILTER (WHERE records_india > 0) FROM '{out}'")
        print(f"{n} species with a recorded interaction, {india} with one in India ({time.monotonic() - t:.0f} s)", flush=True)
    else:
        print("GloBI snapshot unchanged; species table up to date", flush=True)


if __name__ == "__main__":
    main()
