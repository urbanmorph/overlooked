"""Description years for the master list: the year each species was first described.

Sources (the master list takes the first that has a year, see master.described):
  1. the new-species layer: the year of the paper (Plazi, BSI Plant Discoveries, ZSI Animal Discoveries)
  2. Catalogue of Life (XR) authorship, by key: "Swinhoe, 1890"; "(Fabricius, 1775)" is the original
     description, in another genus. Botanical authorships seldom give a year ("(L.) DC.").
  3. ZSI checklist authority, by name (zoological, with the year)
  4. Kew WCVP, by name: the year the basionym was published, else the name's own year ("Bambusa bambos (L.) Voss"
     was published in 1895, but Linnaeus described the species as Arundo bambos in 1753)

This module fetches 2 and 4: one bulk file each, downloaded only when a new release is out (Catalogue of
Life: the dataset key of the latest XR on ChecklistBank; WCVP: the file's ETag), reduced to a small parquet,
and kept in R2 cache/described/ with their versions in described.json.

Usage: python -m pipeline.described [--force]
"""

import argparse
import json
import os
import re
import shutil
import zipfile
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "described"
COL_DATASET = "https://api.checklistbank.org/dataset/3LXR"
COL_EXPORT = "https://api.checklistbank.org/dataset/3LXR/export.zip?format=ColDP"
WCVP_URL = "https://sftp.kew.org/pub/data-repositories/WCVP/wcvp.zip"
R2_PREFIX = "cache/described/"
FILES = {"col": "col_years.parquet", "wcvp": "wcvp_years.parquet"}
META = "described.json"

# A year from Linnaeus (1753) to the 2030s. RE2 (DuckDB) and Python read it the same way.
YEAR = r"\b(17[5-9][0-9]|18[0-9][0-9]|19[0-9][0-9]|20[0-3][0-9])\b"


def year_of(text):
    """The first year in an authorship or a citation, or None. A year still to come is a typo."""
    m = re.search(YEAR, text or "")
    return int(m.group(1)) if m and int(m.group(1)) <= date.today().year else None


def year_sql(col):
    y = f"TRY_CAST(nullif(regexp_extract({col}, '{YEAR}', 1), '') AS INTEGER)"
    return f"CASE WHEN {y} <= year(current_date) THEN {y} END"


def extract(zpath: Path, member, folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        return Path(z.extract(member, folder))


def col_years(zpath: Path, out: Path):
    """Catalogue of Life ColDP export -> parquet (id, year, authority) of accepted species."""
    tsv = extract(zpath, "NameUsage.tsv", out.parent / "col_tmp")
    try:
        duckdb.sql(f"""COPY (
            SELECT "col:ID" AS id, {year_sql('"col:authorship"')} AS year, nullif("col:authorship", '') AS authority
            FROM read_csv('{tsv}', delim = '\t', quote = '', escape = '', header = true, all_varchar = true)
            WHERE "col:rank" = 'species' AND "col:status" IN ('accepted', 'provisionally accepted')
            ORDER BY id) TO '{out}' (FORMAT parquet, COMPRESSION zstd)""")
    finally:
        shutil.rmtree(tsv.parent, ignore_errors=True)
    return out


def wcvp_years(zpath: Path, out: Path):
    """Kew WCVP names -> parquet (name, year, authority) of species names, accepted and synonyms. The year is
    the basionym's, else the name's own; where two names are spelt the same, the accepted one is kept."""
    csv = extract(zpath, "wcvp_names.csv", out.parent / "wcvp_tmp")
    try:
        duckdb.sql(f"""COPY (
            WITH n AS (SELECT * FROM read_csv('{csv}', delim = '|', quote = '', escape = '', header = true,
                                              all_varchar = true))
            SELECT n.taxon_name AS name,
                   arg_min(coalesce({year_sql('b.first_published')}, {year_sql('n.first_published')}),
                           (n.taxon_status <> 'Accepted')::INT) AS year,
                   arg_min(nullif(n.taxon_authors, ''), (n.taxon_status <> 'Accepted')::INT) AS authority
            FROM n LEFT JOIN n b ON b.plant_name_id = n.basionym_plant_name_id
            WHERE n.taxon_rank = 'Species' GROUP BY n.taxon_name ORDER BY name
            ) TO '{out}' (FORMAT parquet, COMPRESSION zstd)""")
    finally:
        shutil.rmtree(csv.parent, ignore_errors=True)
    return out


def download(http, url, dest: Path):
    """Stream url to dest (through a .part file), with a progress line every 50 MB."""
    part = dest.with_suffix(".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    got, step = 0, 50 << 20
    with http.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if got // step > (got - len(chunk)) // step:
                    print(f"  {dest.name}: {got >> 20} MB", flush=True)
    part.replace(dest)
    return dest


def versions(http):
    """The newest release of each source: {"col": {"key", "alias"}, "wcvp": {"etag"}}; None where it does not answer."""
    out = {}
    try:
        d = http.get(COL_DATASET, timeout=60).json()
        out["col"] = {"key": d["key"], "alias": d.get("alias")}
    except Exception as e:  # noqa: BLE001 - any failure keeps the cached copy
        print(f"Catalogue of Life not reachable ({type(e).__name__}); keeping the cached copy", flush=True)
    try:
        h = http.head(WCVP_URL, timeout=60, allow_redirects=True).headers
        out["wcvp"] = {"etag": h.get("ETag") or h.get("Last-Modified")}
    except Exception as e:  # noqa: BLE001
        print(f"WCVP not reachable ({type(e).__name__}); keeping the cached copy", flush=True)
    return out


def sync(http, s3, force=False):
    """Bring both parquet files up to date. Returns {"col": path or None, "wcvp": path or None}."""
    from pipeline import r2
    CACHE.mkdir(parents=True, exist_ok=True)
    meta_path = CACHE / META
    meta = (json.loads(meta_path.read_text()) if meta_path.exists()
            else (r2.get_json(s3, R2_PREFIX + META) if s3 else None) or {})
    latest = versions(http)
    build = {"col": (COL_EXPORT, col_years), "wcvp": (WCVP_URL, wcvp_years)}
    paths = {}
    for src, (url, reduce) in build.items():
        local = CACHE / FILES[src]
        if not local.exists() and s3 and meta.get(src) and r2.exists(s3, R2_PREFIX + FILES[src]):
            s3.download_file(r2.bucket(), R2_PREFIX + FILES[src], str(local))
        new = latest.get(src)
        if local.exists() and not force and (new is None or meta.get(src) == new):
            paths[src] = local
            continue
        if new is None:
            paths[src] = None
            continue
        print(f"{src}: new release {new}; downloading", flush=True)
        zpath = download(http, url, CACHE / f"{src}.zip")
        reduce(zpath, local)
        zpath.unlink()
        meta[src] = new
        meta_path.write_text(json.dumps(meta, indent=1))
        if s3:
            r2.sync_file(s3, local, R2_PREFIX + FILES[src], immutable=False)
            r2.put_json(s3, meta, R2_PREFIX + META)
        n = duckdb.sql(f"SELECT count(*), count(year) FROM '{local}'").fetchone()
        print(f"{src}: {n[0]} species names, {n[1]} with a year", flush=True)
        paths[src] = local
    return paths


def main():
    import requests
    from dotenv import load_dotenv
    from pipeline import health
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="download and rebuild even if the releases are unchanged")
    a = p.parse_args()
    load_dotenv(ROOT / ".env", override=True)
    s3 = None
    if os.environ.get("R2_ENDPOINT"):
        from pipeline import r2
        s3 = r2.client()
    http = requests.Session()
    http.headers["User-Agent"] = health.ua()
    print(json.dumps({k: str(v) for k, v in sync(http, s3, a.force).items()}))


if __name__ == "__main__":
    main()
