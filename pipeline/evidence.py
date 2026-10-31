"""Evidence per species, for the gaps: type specimens and photos from India and DNA barcodes from anywhere (GBIF),
barcodes from India (BOLD), and names in Indian languages (Wikidata).

- GBIF occurrence search, facet counts per species (Catalogue of Life keys, the master list's own: checklistKey
  COL_XR), about 10 requests: records from India with a type status (TYPE_STATUSES: not "NotAType"), records from
  India with a photo (mediaType StillImage), and records anywhere in the International Barcode of Life dataset
  (BOLD's public barcodes on GBIF). GBIF terms; counts only.
- BOLD Systems portal: one summary request, the species with a public barcode record from India, by name.
  Counts only, credited to BOLD.
- Wikidata (CC0), by Catalogue of Life ID (P10585): labels and common names (P1843) in Indian languages (LANGS). A
  label that is the scientific name is left out. Batches of BATCH keys; a key asked in the last MAX_AGE_DAYS days
  is not asked again.

Cache: data/cache/evidence/ and R2 cache/evidence/ (never served). The GBIF and BOLD counts are kept per week (a
second run in the same week asks nothing); the Wikidata answers are saved about every 10 minutes and on exit, so a
stopped run continues.

Output: species.parquet (key, types, photos, barcodes, names [{lang, name}]) and bold_india.csv (name, n).

Usage: .venv/bin/python -m pipeline.evidence [--publish] [--minutes N]   (keys: the published master list)
"""

import csv
import json
import re
import time
from datetime import date
from pathlib import Path

from pipeline.util import log, period

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "evidence"
R2_DIR = "cache/evidence/"
COL_XR = "7ddf754f-d193-4cc9-b351-99906754a03b"        # Catalogue of Life eXtended Release, as a GBIF checklist
IBOL = "d8cd16ba-bb74-4420-821e-083f2bac17c2"          # International Barcode of Life project (iBOL) on GBIF
SEARCH = "https://api.gbif.org/v1/occurrence/search"
BOLD = "https://portal.boldsystems.org/api/summary"
SPARQL = "https://query.wikidata.org/sparql"
TYPE_STATUSES = ("Type", "OriginalMaterial", "Holotype", "Paratype", "Syntype", "Isotype", "Lectotype", "Isosyntype",
                 "Isolectotype", "Paralectotype", "Neotype", "Plastotype", "Cotype", "Allotype", "Iconotype",
                 "TypeStrain", "TypeSeries", "Epitype", "Paraneotype", "Isoneotype", "Extype", "Isoparatype",
                 "Isoepitype", "Hapantotype", "Plastosyntype", "Exholotype", "Allolectotype", "Plastoholotype",
                 "Plastoparatype")
# The 22 languages of the Eighth Schedule, Goan Konkani, Mizo, Tulu and Bhojpuri.
LANGS = ("as", "bn", "brx", "doi", "gu", "hi", "kn", "ks", "kok", "gom", "mai", "ml", "mni", "mr", "ne", "or", "pa",
         "sa", "sat", "sd", "ta", "te", "ur", "lus", "tcy", "bho")
BATCH = 500
TRIES = 4
PAUSE = 1.0          # seconds between batches
MAX_AGE_DAYS = 90
SAVE_EVERY = 600     # seconds
PAGE = 100_000
SPECIES_NAME = re.compile(r"[A-Z][a-z]+ [a-z][a-z-]+( [a-z][a-z-]+)?")


def facet_counts(http, filters, page=PAGE):
    """{species key: records} for an occurrence search, read from its species facet, page by page."""
    out, offset = {}, 0
    while True:
        params = [*filters, ("checklistKey", COL_XR), ("limit", 0), ("facet", "speciesKey"),
                  ("facetLimit", page), ("facetOffset", offset)]
        r = http.get(SEARCH, params=params, timeout=600)
        r.raise_for_status()
        counts = (r.json().get("facets") or [{}])[0].get("counts", [])
        out.update((c["name"], c["count"]) for c in counts)
        if len(counts) < page:
            return out
        offset += page


def gbif_counts(http):
    return {"types": facet_counts(http, [("country", "IN"), *(("typeStatus", t) for t in TYPE_STATUSES)]),
            "photos": facet_counts(http, [("country", "IN"), ("mediaType", "StillImage")]),
            "barcodes": facet_counts(http, [("datasetKey", IBOL)])}


def bold_names(data):
    """{name: records} for the species names (two or three words, no 'sp.') in BOLD's summary."""
    return {n: c for n, c in (data.get("species") or {}).items() if SPECIES_NAME.fullmatch(n)}


def bold_india(http):
    r = http.get(BOLD, params={"query": "geo:country/ocean:India", "fields": "species", "reduce_operation": "count"},
                 timeout=300)
    r.raise_for_status()
    return bold_names(r.json())


def ask(http, query, tries=TRIES):
    """The bindings of a SPARQL query; a server error, a timeout or a dropped connection is asked again, waiting
    longer each time (the query service is often busy)."""
    import requests
    for i in range(tries):
        try:
            r = http.post(SPARQL, data={"query": query}, headers={"Accept": "application/sparql-results+json"},
                          timeout=120)
            r.raise_for_status()
            return r.json()["results"]["bindings"]
        except (requests.exceptions.HTTPError, requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError) as e:
            if i == tries - 1:
                raise
            log(f"wikidata: {e}; asking again")
            time.sleep(30 * (i + 1))


def wikidata_batch(http, keys):
    """{key: [[lang, name], ...]} for the keys with a name in an Indian language."""
    values = " ".join(json.dumps(k) for k in keys)
    langs = ",".join(json.dumps(x) for x in LANGS)
    q = f"""SELECT ?col ?taxon (LANG(?l) AS ?lang) ?l WHERE {{
              VALUES ?col {{ {values} }}
              ?item wdt:P10585 ?col . OPTIONAL {{ ?item wdt:P225 ?taxon }}
              {{ ?item rdfs:label ?l }} UNION {{ ?item wdt:P1843 ?l }}
              FILTER(LANG(?l) IN ({langs})) }}"""
    bindings = ask(http, q)
    taxa, found = {}, {}
    for b in bindings:
        if "taxon" in b:
            taxa.setdefault(b["col"]["value"], set()).add(b["taxon"]["value"].lower())
    for b in bindings:
        key, pair = b["col"]["value"], [b["lang"]["value"], b["l"]["value"].strip()]
        if pair[1].lower() in taxa.get(key, ()) or pair in found.get(key, []):
            continue
        found.setdefault(key, []).append(pair)
    return found


def wikidata_names(http, keys, cache, today, save=None, deadline=None, batch=BATCH):
    """Ask Wikidata for the keys not in cache or asked more than MAX_AGE_DAYS ago; cache: {key: [date asked,
    names]}. True when every key is answered; False when the deadline (time.monotonic()) or a service that stays
    down stopped it."""
    import requests
    day = date.fromisoformat(today)
    todo = [k for k in keys if k not in cache or (day - date.fromisoformat(cache[k][0])).days > MAX_AGE_DAYS]
    saved = time.monotonic()
    for i in range(0, len(todo), batch):
        if deadline is not None and time.monotonic() >= deadline:
            log(f"wikidata: stopped at the time limit, {len(todo) - i} keys left")
            return False
        part = todo[i:i + batch]
        try:
            found = wikidata_batch(http, part)
        except requests.exceptions.RequestException as e:
            log(f"wikidata: stopped ({e}); {len(todo) - i} keys left for the next run")
            if save:
                save()
            return False
        cache.update({k: [today, found.get(k, [])] for k in part})
        if i // batch % 20 == 0:
            log(f"wikidata: {min(i + batch, len(todo))} of {len(todo)} keys asked")
        if save and (time.monotonic() - saved >= SAVE_EVERY or i + batch >= len(todo)):
            save()
            saved = time.monotonic()
        time.sleep(PAUSE)
    return True


def write_table(counts, names, path: Path):
    """species.parquet: one row per key with any evidence (a count or a name)."""
    import duckdb
    rows = {}
    for kind in ("types", "photos", "barcodes"):
        for k, n in counts.get(kind, {}).items():
            rows.setdefault(k, {})[kind] = n
    for k, (_, found) in names.items():
        if found:
            rows.setdefault(k, {})["names"] = [{"lang": a, "name": b} for a, b in found]
    con = duckdb.connect()
    con.sql("CREATE TABLE t (key VARCHAR, types BIGINT, photos BIGINT, barcodes BIGINT, "
            "names STRUCT(lang VARCHAR, name VARCHAR)[])")
    con.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?)",
                    [(k, r.get("types"), r.get("photos"), r.get("barcodes"), r.get("names")) for k, r in sorted(rows.items())])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    con.sql(f"COPY t TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)")
    tmp.replace(path)
    return path


def write_bold(names, path: Path):
    tmp = path.with_suffix(".part")
    with tmp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "n"])
        w.writerows(sorted(names.items()))
    tmp.replace(path)
    return path


def refresh(http, s3, keys, cache: Path = CACHE, deadline=None, today=None):
    """Both tables for the keys, from this week's counts and the Wikidata cache (local, else R2's copy); asks only
    what is missing. Returns (species.parquet, bold_india.csv)."""
    from pipeline import r2
    cache.mkdir(parents=True, exist_ok=True)
    today = today or date.today().isoformat()

    def load(name):
        p = cache / name
        if p.exists():
            return json.loads(p.read_text())
        obj = r2.get_json(s3, R2_DIR + name) if s3 else None
        if obj is not None:
            p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        return obj

    def keep(name, obj):
        p = cache / name
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        tmp.replace(p)
        if s3:
            r2.sync_file(s3, p, R2_DIR + name, immutable=False)

    week = period()
    counts = load("counts.json")
    if not counts or counts.get("period") != week:
        counts = {"period": week, **gbif_counts(http), "bold": bold_india(http)}
        keep("counts.json", counts)
        log(f"evidence: {len(counts['types'])} species with a type specimen from India, {len(counts['photos'])} with "
            f"a photo, {len(counts['barcodes'])} with a barcode anywhere, {len(counts['bold'])} names on BOLD from India")
    names = load("wikidata.json") or {}
    try:
        wikidata_names(http, keys, names, today, save=lambda: keep("wikidata.json", names), deadline=deadline)
    finally:
        keep("wikidata.json", names)
    log(f"evidence: {sum(1 for _, f in names.values() if f)} of {len(names)} species with a name in an Indian language")
    table = write_table(counts, names, cache / "species.parquet")
    bold = write_bold(counts["bold"], cache / "bold_india.csv")
    if s3:
        for p in (table, bold):
            r2.sync_file(s3, p, R2_DIR + p.name, immutable=False)
    return table, bold


def master_keys(s3, local=ROOT / "data" / "layers" / "master"):
    """The species keys of the latest published master list (R2), else of the newest local one."""
    import duckdb

    from pipeline import r2
    path = None
    if s3:
        base = (r2.get_json(s3, "layers/master/latest.json") or {}).get("base")
        if base:
            path = CACHE / "master.parquet"
            CACHE.mkdir(parents=True, exist_ok=True)
            s3.download_file(r2.bucket(), base + "master.parquet", str(path))
    if path is None:
        found = sorted(local.glob("*/master.parquet"))
        path = found[-1] if found else None
    if path is None:
        raise SystemExit("no master list to take the keys from")
    return [k for (k,) in duckdb.sql(f"SELECT DISTINCT key FROM '{path}' WHERE key IS NOT NULL ORDER BY 1").fetchall()]


def main():
    import argparse

    import requests

    from pipeline import health
    a = argparse.ArgumentParser()
    a.add_argument("--publish", action="store_true", help="read and keep the cache in R2 (cache/evidence/)")
    a.add_argument("--minutes", type=float, help="stop the Wikidata requests after this time; the next run continues")
    args = a.parse_args()
    http = requests.Session()
    http.headers["User-Agent"] = health.ua()
    s3 = None
    if args.publish:
        from dotenv import load_dotenv

        from pipeline import r2
        load_dotenv(ROOT / ".env", override=True)
        s3 = r2.client()
    deadline = time.monotonic() + args.minutes * 60 if args.minutes else None
    refresh(http, s3, master_keys(s3), deadline=deadline)


if __name__ == "__main__":
    main()
