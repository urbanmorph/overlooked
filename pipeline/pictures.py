"""Pictures for the species page: one photo per species with its credit and licence, and an English common name.

Order: a photo from India (the shortlist's corpus: research-grade iNaturalist observations from India on GBIF, one per
species, corpus.csv), else the first iNaturalist taxon photo with a Creative Commons licence, else the Wikimedia
Commons image Wikidata gives (P18). "All rights reserved" photos are never used; CC BY-NC is (the owner approved it on
31 October 2026: Overlooked is non-commercial, and the credit and licence go with each photo). We link to the images;
we do not copy them. The common name: iNaturalist's English name, else Wikidata's (the taxon common name, else the label
when it is not the Latin name).

- Wikidata (CC0), by Catalogue of Life ID (P10585), else by scientific name (P225) when the name is on one item only:
  the Commons image (P18), the iNaturalist taxon (P3151), the English taxon common name (P1843), else the English
  label. Batches of BATCH; a key asked in the last MAX_AGE_DAYS days is not asked again.
- iNaturalist API, taxa by id, INAT_BATCH a request, one request a second.
- Wikimedia Commons API, imageinfo, COMMONS_BATCH files a request: the thumbnail, the file page, the author, the
  licence. Asked only for species with no other photo.

Cache: one JSON store (data/cache/pictures/store.json and R2 cache/pictures/, never served), saved every SAVE_EVERY
seconds and on exit, so a stopped run continues and a second run asks only what is new or old. The corpus table is
made once on the machine that has the corpus (--corpus) and kept in R2.

Output: pictures.parquet (key, url, page, by, licence, source, common): the species with a photo or a common name.

Usage: .venv/bin/python -m pipeline.pictures [--publish] [--minutes N] [--corpus]
"""

import csv
import html
import json
import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import unquote

from pipeline.evidence import ask
from pipeline.util import log

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "pictures"
R2_DIR = "cache/pictures/"
STORE, TABLE, CORPUS = "store.json", "pictures.parquet", "corpus.csv"
CORPUS_DIR = ROOT / "data" / "corpus_v0"
INAT = "https://api.inaturalist.org/v1/taxa/"
COMMONS = "https://commons.wikimedia.org/w/api.php"
BATCH, INAT_BATCH, COMMONS_BATCH = 400, 30, 50
TRIES = 4
PAUSE = 1.0          # seconds between requests to one service
MAX_AGE_DAYS = 90
VERSION = 3          # of the Wikidata query; a store from another version asks Wikidata again
SAVE_EVERY = 600     # seconds
THUMB = 640          # pixels wide, the Commons thumbnail
CC = {"cc0": "CC0", "cc-by": "CC BY", "cc-by-sa": "CC BY-SA", "cc-by-nc": "CC BY-NC", "cc-by-nc-sa": "CC BY-NC-SA",
      "cc-by-nd": "CC BY-ND", "cc-by-nc-nd": "CC BY-NC-ND"}
LICENCE_URL = re.compile(r"creativecommons\.org/(?:licenses|publicdomain)/([a-z-]+)/([\d.]+)")


def fetch(http, url, params=None, tries=TRIES):
    """GET with retries: a dropped connection, a cut-off response, a timeout, a busy (429) or failing (5xx) server is
    asked again, waiting longer each time."""
    import requests
    for i in range(tries):
        try:
            r = http.get(url, params=params, timeout=120)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.exceptions.HTTPError(f"{r.status_code} from {url}")
            r.raise_for_status()
            return r
        except (requests.exceptions.HTTPError, requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError) as e:
            if i == tries - 1:
                raise
            log(f"pictures: {e}; asking again")
            time.sleep(30 * (i + 1))


def clean_credit(text):
    """The author as plain text: tags and entities gone, "Unknown author" dropped, Commons' "The original uploader was
    X at ..." as X, at most 80 characters."""
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(text or ""))).strip()
    if "unknown author" in t.lower():
        return ""
    m = re.match(r"The original uploader was (.+?) at ", t)
    t = m[1] if m else t
    return t if len(t) <= 80 else t[:79].rstrip() + "…"


def inat_photo(taxon):
    """[url, page, by, licence, source] of the taxon's first photo with a Creative Commons licence, else None."""
    for tp in taxon.get("taxon_photos") or []:
        p = tp.get("photo") or {}
        if p.get("license_code") in CC and p.get("medium_url"):
            by = re.sub(r"^\(c\)\s*", "", p.get("attribution") or "").split(",")[0]
            return [p["medium_url"], f"https://www.inaturalist.org/photos/{p['id']}", clean_credit(by), CC[p["license_code"]], "iNaturalist"]
    return None


def wikidata_batch(http, values, prop="P10585"):
    """{value: [Commons file or None, iNaturalist taxon id or None, English label or None]} for the values Wikidata
    has under this property: Catalogue of Life IDs (P10585), or scientific names (P225), where a name on more than one
    item (a homonym) is left out."""
    q = f"""SELECT ?v ?item ?img ?inat ?en ?cn ?tn WHERE {{
              VALUES ?v {{ {" ".join(json.dumps(v) for v in values)} }}
              ?item wdt:{prop} ?v .
              OPTIONAL {{ ?item wdt:P18 ?img }} OPTIONAL {{ ?item wdt:P3151 ?inat }}
              OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
              OPTIONAL {{ ?item wdt:P1843 ?cn FILTER(LANG(?cn) = "en") }} OPTIONAL {{ ?item wdt:P225 ?tn }} }}"""
    out, items, common, latin = {}, {}, {}, {}
    for b in ask(http, q):
        v = b["v"]["value"]
        items.setdefault(v, set()).add(b["item"]["value"])
        cur = out.setdefault(v, [None, None, None])
        if "img" in b and not cur[0]:
            cur[0] = "File:" + unquote(b["img"]["value"].rsplit("/", 1)[1])
        if "inat" in b and not cur[1]:
            cur[1] = b["inat"]["value"]
        if "en" in b and not cur[2]:
            cur[2] = b["en"]["value"]
        if "cn" in b:
            common.setdefault(v, b["cn"]["value"])
        if "tn" in b:
            latin.setdefault(v, set()).add(b["tn"]["value"].lower())
    for v, x in out.items():
        if v in common:
            x[2] = common[v]                                  # the taxon common name before the label
        elif x[2] and x[2].lower() in latin.get(v, ()):
            x[2] = None                                       # a label that is the item's scientific name
    return {v: x for v, x in out.items() if len(items[v]) == 1}


def wikidata_of(store, key):
    """[date, file, taxon, label]: by the Catalogue of Life ID, else by the scientific name."""
    wd = store["wikidata"].get(key)
    return wd if wd and any(wd[1:]) else store["byname"].get(key) or wd or [None] * 4


def commons_batch(http, files):
    """{file: [thumbnail url, file page, by, licence, source]} from Commons' imageinfo."""
    r = fetch(http, COMMONS, {"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|extmetadata",
                              "iiurlwidth": THUMB, "titles": "|".join(files)})
    out = {}
    for page in (r.json().get("query") or {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            continue
        m = info.get("extmetadata") or {}
        out[page["title"]] = [info.get("thumburl") or info.get("url"), info.get("descriptionurl"),
                              clean_credit((m.get("Artist") or {}).get("value")), (m.get("LicenseShortName") or {}).get("value") or "",
                              "Wikimedia Commons"]
    return out


def corpus_table(corpus: Path, photos: Path, out: Path):
    """corpus.csv: one photo per species from the shortlist's corpus (research-grade iNaturalist observations from
    India): name, url, page (the observation), by, licence. The first photo of the lowest GBIF record."""
    import duckdb
    rows = duckdb.sql(f"""
        SELECT c.species, arg_min(p.open_url, (gbifID::BIGINT, p.position)), arg_min(c.obs_id, (gbifID::BIGINT, p.position)),
               arg_min(p.rightsHolder, (gbifID::BIGINT, p.position)), arg_min(p.license, (gbifID::BIGINT, p.position))
        FROM '{corpus}' c JOIN '{photos}' p USING (gbifID)
        WHERE p.open_url IS NOT NULL AND p.license LIKE '%creativecommons.org%' GROUP BY c.species ORDER BY c.species""").fetchall()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "url", "page", "by", "licence"])
        for name, url, obs, by, lic in rows:
            m = LICENCE_URL.search(lic)
            label = ("CC0" if m[1] == "zero" else "CC " + m[1].upper().replace("-", " ").replace("BY ", "BY-").replace(" ", "-")) + f" {m[2]}"
            w.writerow([name, url, f"https://www.inaturalist.org/observations/{obs}", clean_credit(by), label])
    return out


def stale(entry, day):
    return entry is None or (day - date.fromisoformat(entry[0])).days > MAX_AGE_DAYS


def harvest(http, store, names, need_commons, today, deadline=None, save=None):
    """Bring the store up to date for these {key: name}: Wikidata by Catalogue of Life ID, then by scientific name for
    the keys it did not find, then iNaturalist for the taxa it names, then Commons for the files of species
    `need_commons` says lack a photo. True when complete, False when the deadline stopped it."""
    day, saved = date.fromisoformat(today), time.monotonic()
    late = lambda: deadline is not None and time.monotonic() >= deadline

    def tick():
        nonlocal saved
        if save and time.monotonic() - saved >= SAVE_EVERY:
            save()
            saved = time.monotonic()

    wd, byname, inat, commons = store["wikidata"], store["byname"], store["inat"], store["commons"]
    for kind, done, todo in [("keys", wd, lambda: [k for k in names if stale(wd.get(k), day)]),
                             ("names", byname, lambda: [k for k in names if not any(wd[k][1:]) and stale(byname.get(k), day)])]:
        todo = todo()
        for i in range(0, len(todo), BATCH):
            if late():
                return False
            part = todo[i:i + BATCH]
            found = wikidata_batch(http, part) if kind == "keys" else wikidata_batch(http, [names[k] for k in part], "P225")
            done.update({k: [today, *found.get(k if kind == "keys" else names[k], [None, None, None])] for k in part})
            if i // BATCH % 20 == 0:
                log(f"pictures: wikidata by {kind} {min(i + BATCH, len(todo))} of {len(todo)}")
            tick()
            time.sleep(PAUSE)
    found = {k: wikidata_of(store, k) for k in names}
    taxa = sorted({w[2] for w in found.values() if w[2]} - {t for t, e in inat.items() if not stale(e, day)})
    for i in range(0, len(taxa), INAT_BATCH):
        if late():
            return False
        part = taxa[i:i + INAT_BATCH]
        r = fetch(http, INAT + ",".join(part), {"locale": "en"})
        got = {str(t["id"]): t for t in r.json().get("results", [])}
        inat.update({t: [today, inat_photo(got[t]) if t in got else None, (got.get(t) or {}).get("preferred_common_name")] for t in part})
        if i // INAT_BATCH % 100 == 0:
            log(f"pictures: inaturalist {min(i + INAT_BATCH, len(taxa))} of {len(taxa)} taxa")
        tick()
        time.sleep(PAUSE)
    files = sorted({w[1] for k, w in found.items() if w[1] and need_commons(k)} - {f for f, e in commons.items() if not stale(e, day)})
    for i in range(0, len(files), COMMONS_BATCH):
        if late():
            return False
        part = files[i:i + COMMONS_BATCH]
        got = commons_batch(http, part)
        commons.update({f: [today, got.get(f)] for f in part})
        tick()
        time.sleep(PAUSE)
    return True


def choose(key, name, store, corpus):
    """[url, page, by, licence, source, common] for one species, or None when there is neither a photo nor a name."""
    _, file, taxon, label = wikidata_of(store, key)
    t = store["inat"].get(taxon) if taxon else None
    india = corpus.get(name)
    photo = ([*india, "iNaturalist (India)"] if india else (t[1] if t and t[1] else None)
             or ((store["commons"].get(file) or [None, None])[1] if file else None))
    if photo and photo[4] == "Wikimedia Commons" and photo[0]:
        photo = [photo[0].split("?")[0], *photo[1:]]       # Commons adds tracking parameters to its thumbnails
    common = (t[2] if t else None) or (label if label and label.lower() != name.lower() else None)
    if not photo and not common:
        return None
    return [*(photo or [None] * 5), common]


def write_table(rows, store, corpus, path: Path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    out = []
    for key, name in rows:
        c = choose(key, name, store, corpus)
        if c:
            out.append(dict(zip(["key", "url", "page", "by", "licence", "source", "common"], [key, *c])))
    cols = ["key", "url", "page", "by", "licence", "source", "common"]
    table = pa.Table.from_pylist(out, schema=pa.schema([(c, pa.string()) for c in cols]))
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")
    return path


def refresh(http, s3, rows, corpus_csv: Path | None, cache: Path = CACHE, deadline=None, today=None):
    """pictures.parquet for these (key, name) rows, from the store (local, else R2's) brought up to date."""
    from pipeline import r2
    cache.mkdir(parents=True, exist_ok=True)
    today = today or date.today().isoformat()
    local = cache / STORE
    store = (json.loads(local.read_text()) if local.exists() else (r2.get_json(s3, R2_DIR + STORE) if s3 else None)) \
        or {}
    old = store.get("version") != VERSION
    store = {"version": VERSION, **{s: {} if old and s in ("wikidata", "byname") else store.get(s, {})
                                    for s in ("wikidata", "byname", "inat", "commons")}}
    corpus = {}
    if corpus_csv and corpus_csv.exists():
        with corpus_csv.open() as f:
            corpus = {r["name"]: [r["url"], r["page"], r["by"], r["licence"]] for r in csv.DictReader(f)}
    names = dict(rows)

    def need_commons(k):
        t = wikidata_of(store, k)[2]
        return names[k] not in corpus and not (store["inat"].get(t) or [None, None])[1]

    def save():
        tmp = local.with_suffix(".tmp")
        tmp.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")))
        tmp.replace(local)
        if s3:
            r2.sync_file(s3, local, R2_DIR + STORE, immutable=False)

    try:
        done = harvest(http, store, names, need_commons, today, deadline, save)
    finally:
        save()
    table = write_table(rows, store, corpus, cache / TABLE)
    log(f"pictures: {'complete' if done else 'stopped at the time limit; the next run continues'}")
    if s3:
        r2.sync_file(s3, table, R2_DIR + TABLE, immutable=False)
    return table


def main():
    import argparse

    import duckdb
    import requests

    from pipeline import health, iucn_api
    a = argparse.ArgumentParser()
    a.add_argument("--publish", action="store_true", help="read and keep the store and table in R2 (cache/pictures/)")
    a.add_argument("--minutes", type=float, help="stop after this time; the next run continues")
    a.add_argument("--corpus", action="store_true", help="make corpus.csv from data/corpus_v0 (the machine that has it)")
    args = a.parse_args()
    http = requests.Session()
    http.headers["User-Agent"] = health.ua()
    s3 = None
    if args.publish:
        from dotenv import load_dotenv

        from pipeline import r2
        load_dotenv(ROOT / ".env", override=True)
        s3 = r2.client()
    corpus = CACHE / CORPUS
    if args.corpus:
        corpus_table(CORPUS_DIR / "corpus.parquet", CORPUS_DIR / "photos.parquet", corpus)
        if s3:
            r2.sync_file(s3, corpus, R2_DIR + CORPUS, immutable=False)
    elif s3 and not corpus.exists():
        r2.restore(s3, R2_DIR + CORPUS, corpus)
    master = iucn_api.master_path(s3)
    rows = duckdb.sql(f"SELECT key, name FROM '{master}' WHERE key IS NOT NULL ORDER BY key").fetchall()
    refresh(http, s3, rows, corpus, deadline=time.monotonic() + args.minutes * 60 if args.minutes else None)


if __name__ == "__main__":
    main()
