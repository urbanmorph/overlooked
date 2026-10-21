"""IUCN Red List categories, without an IUCN API token.

Source: "The IUCN Red List of Threatened Species" checklist as published on GBIF (dataset
19491596-35ae-4a91-9a98-85cf505f1bd3, DOI 10.15468/0qnb58, CC BY 4.0 on GBIF). Its Darwin Core
archive holds every assessed species with its global category (distribution extension, threatStatus)
and the synonyms IUCN lists. About 21 MB; downloaded only when its ETag changes.

Creates table iucn: name (canonical "Genus epithet"), category (CR, EN, VU, NT, LC, DD, EW, EX),
accepted (true for the assessed name, false for a synonym), iucn_id, kingdom, phylum, class, "order", family.

A later IUCN API route (env IUCN_TOKEN) only has to produce the same table; see `table`.
"""

import json
import os
import zipfile
from pathlib import Path

import requests

from pipeline.util import value

ROOT = Path(__file__).resolve().parent.parent
URL = "https://hosted-datasets.gbif.org/datasets/iucn/iucn-latest.zip"
DATASET = "19491596-35ae-4a91-9a98-85cf505f1bd3"
CACHE = ROOT / "data" / "cache" / "master"
PARQUET, META = "iucn.parquet", "iucn_meta.json"

# threatStatus text -> category. Old "Lower Risk" categories map to their present equivalents.
CATEGORY = {"critically endangered": "CR", "endangered": "EN", "vulnerable": "VU", "near threatened": "NT",
            "conservation dependent": "NT", "least concern": "LC", "data deficient": "DD",
            "extinct in the wild": "EW", "extinct": "EX"}
TAXON_COLS = ["id", "scientificname", "kingdom", "phylum", "class", "order", "family", "genus", "epithet",
              "authorship", "rank", "infraspecific", "status", "accepted_id", "citation", "references"]
DIST_COLS = ["id", "countrycode", "locality", "source", "establishment", "threat", "occurrence"]


def parse(con, folder: Path, out: Path):
    """Build the iucn table from an unpacked archive and write it to out (Parquet)."""
    read = lambda f, cols: (f"read_csv('{folder / f}', delim='\t', header=false, quote='', all_varchar=true, "
                            f"names={cols})")
    con.sql("CREATE OR REPLACE MACRO initcap(s) AS upper(s[1]) || lower(s[2:])")
    cases = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in CATEGORY.items())
    con.sql(f"""
        CREATE OR REPLACE TABLE iucn AS
        WITH t AS (SELECT * FROM {read('taxon.txt', TAXON_COLS)}),
        d AS (SELECT id, CASE lower(threat) {cases} END AS category FROM {read('distribution.txt', DIST_COLS)}
              WHERE coalesce(locality, 'Global') = 'Global'),
        acc AS (SELECT t.id, t.genus || ' ' || t.epithet AS name, d.category,
                       initcap(t.kingdom) AS kingdom, initcap(t.phylum) AS phylum, initcap(t.class) AS class,
                       initcap(t."order") AS "order", initcap(t.family) AS family
                FROM t JOIN d USING (id)
                WHERE t.status = 'accepted' AND t.rank = 'species' AND t.infraspecific IS NULL AND d.category IS NOT NULL),
        syn AS (SELECT a.id, regexp_extract(s.scientificname, '^([A-Z][a-z-]+ [a-z][a-z-]+)', 1) AS name, a.category,
                       a.kingdom, a.phylum, a.class, a."order", a.family
                FROM t s JOIN acc a ON a.id = s.accepted_id
                WHERE s.status = 'synonym'
                  AND NOT regexp_matches(s.scientificname, '^[A-Z][a-z-]+ [a-z][a-z-]+ (ssp\\.|subsp\\.|var\\.|[a-z][a-z-]+( |$))'))
        SELECT DISTINCT name, category, true AS accepted, id AS iucn_id, kingdom, phylum, class, "order", family FROM acc
        UNION ALL
        SELECT DISTINCT name, category, false, id, kingdom, phylum, class, "order", family FROM syn
        WHERE name <> '' AND name NOT IN (SELECT name FROM acc)
    """)
    con.sql(f"COPY iucn TO '{out}' (FORMAT parquet, COMPRESSION zstd)")


def _remote_tag(http):
    r = http.head(URL, timeout=60, allow_redirects=True)
    r.raise_for_status()
    return r.headers.get("ETag") or r.headers.get("Last-Modified")


def from_gbif(con, http, s3=None, cache=CACHE):
    """The GBIF-hosted Red List. Kept as data/cache/master/iucn.parquet and R2 cache/master/iucn.parquet;
    the archive is downloaded again only when its ETag changes. Returns the provenance."""
    from pipeline import r2
    cache.mkdir(parents=True, exist_ok=True)
    local, meta_path = cache / PARQUET, cache / META
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
    if s3 and not meta:
        meta = r2.get_json(s3, f"cache/master/{META}")
        if meta and not local.exists():
            s3.download_file(r2.bucket(), f"cache/master/{PARQUET}", str(local))
    try:
        tag = _remote_tag(http)
    except requests.RequestException:
        tag = None  # GBIF's file host is down: keep the cached copy if there is one
    if not (meta and local.exists() and (tag is None or meta.get("etag") == tag)):
        if tag is None:
            raise RuntimeError("IUCN archive not reachable and no cached copy")
        zpath = cache / "iucn-latest.zip"
        part = zpath.with_suffix(".part")
        with http.get(URL, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(part, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        part.replace(zpath)
        folder = cache / "iucn"
        with zipfile.ZipFile(zpath) as z:
            z.extractall(folder)
        parse(con, folder, local)
        meta = {"etag": tag, "url": URL, "dataset": DATASET, "doi": "10.15468/0qnb58", "licence": "CC BY 4.0 (on GBIF)",
                "rows": value(con, "SELECT count(*) FROM iucn")}
        meta_path.write_text(json.dumps(meta, indent=1))
        if s3:
            r2.sync_file(s3, local, f"cache/master/{PARQUET}", immutable=False)
            r2.put_json(s3, meta, f"cache/master/{META}")
    else:
        meta_path.write_text(json.dumps(meta, indent=1))
        con.sql(f"CREATE OR REPLACE TABLE iucn AS SELECT * FROM '{local}'")
    return {"source": "IUCN Red List via GBIF", **meta}


def table(con, http, s3=None):
    """Create table iucn. With IUCN_TOKEN set, an API route can be added here returning the same table;
    until then the GBIF-hosted copy is used either way."""
    if os.environ.get("IUCN_TOKEN"):
        print("IUCN_TOKEN is set, but the API route is not built yet; using the Red List copy on GBIF")
    return from_gbif(con, http, s3)
