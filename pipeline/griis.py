"""Introduced species of India from the Global Register of Introduced and Invasive Species - India (GRIIS India,
CC BY 4.0, published on GBIF, dataset b09c3987-af9a-4658-9bfd-19cf712ac3d1): the canonical names of its species-rank
entries (2,167 on 26 Nov 2026, plants and animals).

The master list uses it as a flag, never a filter (25 Nov 2026): a species GRIIS lists carries the label 'int'
(introduced in India), shown on its page and in the agent server, where a place's headline threatened and endemic
counts leave it out and count it apart. A variety or subspecies GRIIS lists does not mark its species.

Read through GBIF's species API, a few pages at each master run. Kept in R2 cache/master/griis_india.parquet (uploaded
only when it changed); a run that cannot reach GBIF uses that copy, else the last local one.
"""

from pathlib import Path

import duckdb

from pipeline.util import log

DATASET = "b09c3987-af9a-4658-9bfd-19cf712ac3d1"
API = "https://api.gbif.org/v1/species/search"
R2_KEY = "cache/master/griis_india.parquet"
LIMIT = 1000
PAGES_MAX = 50


def names(http):
    """The species-rank canonical names, every page."""
    out, offset = set(), 0
    for _ in range(PAGES_MAX):
        r = http.get(API, params={"datasetKey": DATASET, "limit": LIMIT, "offset": offset}, timeout=120)
        r.raise_for_status()
        page = r.json()
        out |= {x["canonicalName"] for x in page.get("results", []) if x.get("rank") == "SPECIES" and x.get("canonicalName")}
        if page.get("endOfRecords", True):
            return sorted(out)
        offset += LIMIT
    raise RuntimeError(f"GRIIS India: more than {PAGES_MAX} pages")


def refresh(http, s3, cache: Path):
    """The names table, read from GBIF and kept in R2. When GBIF cannot be reached: R2's copy, else the last local
    one. None when there is neither."""
    from pipeline import r2
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / Path(R2_KEY).name
    try:
        got = names(http)
    except Exception as e:  # noqa: BLE001 - any failure: use the copy kept before
        log(f"GRIIS India: GBIF not reached ({e}); using the copy kept before")
        return r2.fetch(s3, R2_KEY, dest) if s3 else (dest if dest.exists() else None)
    part = dest.with_suffix(".part")
    duckdb.execute(f"COPY (SELECT unnest(?::VARCHAR[]) AS name ORDER BY 1) TO '{part}' (FORMAT parquet)", [got])
    part.replace(dest)
    log(f"GRIIS India: {len(got):,} species")
    if s3:
        r2.sync_file(s3, dest, R2_KEY, immutable=False)
    return dest
