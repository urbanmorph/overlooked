"""IUCN Red List API v4 (env IUCN_TOKEN): the latest global assessment of every assessed species of the India list,
with what the gaps need: year published, population trend (the Prestonian gap), threats and habitats (IUCN
classification codes), and India's entry in the assessment's countries (native or introduced, present, endemic).

Three stages, each resumable:
  1. India's list: countries/IN, latest global assessments (about 116 pages of 100).
  2. Names of the list with an IUCN category that India's list does not have, by name (taxa/scientific_name):
     assessed, but IUCN does not map the species to India.
  3. Each assessment in full (assessment/{id}). An assessment never changes once published, so a new Red List
     version reads stages 1 and 2 again and keeps every assessment already fetched.

Caching: everything in one JSON store (data/cache/iucn_api/store.json), saved every SAVE_EVERY seconds, at a time
limit and on any failure, and copied to R2 cache/iucn_api/ (private: the site never serves cache/). Idempotent: a run
with the same Red List version and names asks the API only for its version.

Output: iucn_detail.parquet, one row per species name of the list with an assessment.

Monthly on GitHub Actions (.github/workflows/iucn.yml); by hand:
Usage: .venv/bin/python -m pipeline.iucn_api [--master data/layers/master/<period>/master.parquet] [--minutes 120] [--local]
"""

import argparse
import json
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://api.iucnredlist.org/api/v4/"
CACHE = ROOT / "data" / "cache" / "iucn_api"
R2_PREFIX = "cache/iucn_api/"
PAUSE = 0.25          # seconds between requests: about 4 a second at most
BACKOFF = 2.0         # first wait after a server error or a dropped connection; doubles each try
SAVE_EVERY = 600      # seconds between saves of the store
GLOBAL = "1"          # IUCN scope code of a global assessment


class ApiDown(RuntimeError):
    """The API did not answer after every try."""


class Api:
    """A polite client: a pause between requests, Retry-After on 429, backoff on 5xx and dropped connections.
    get() returns the parsed body, (body, total pages) for a paged answer, or None for 404."""

    def __init__(self, token, session=None, tries=6):
        self.session, self.tries = session or requests.Session(), tries
        self.session.headers.update({"Authorization": f"Bearer {token}",
                                     "User-Agent": "Overlooked/1.0 (https://overlooked-india.pages.dev)"})
        self.count = 0

    def get(self, path, params=None):
        for attempt in range(self.tries):
            if PAUSE:
                time.sleep(PAUSE)
            wait = BACKOFF * 2 ** attempt
            try:
                r = self.session.get(BASE + path, params=params, timeout=60)
            except requests.RequestException:
                time.sleep(wait)
                continue
            self.count += 1
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After") or wait))
                continue
            if r.status_code >= 500:
                time.sleep(wait)
                continue
            r.raise_for_status()   # 401 and other client errors: stop, nothing to retry
            pages = r.headers.get("total-pages")
            return (r.json(), int(pages)) if pages else r.json()
        raise ApiDown(path)


class Store:
    """The run's state and answers in one JSON file; upload(path) copies it to durable storage."""

    def __init__(self, path: Path, upload=None):
        self.path, self.upload, self.saved_at = path, upload, time.monotonic()
        self.data = json.loads(path.read_text()) if path.exists() else {}
        for k in ("pages", "names", "assessments"):
            self.data.setdefault(k, {})

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, separators=(",", ":")))
        tmp.replace(self.path)
        if self.upload:
            self.upload(self.path)
        self.saved_at = time.monotonic()

    def maybe_save(self):
        if time.monotonic() - self.saved_at > SAVE_EVERY:
            self.save()


def compact(a, country="IN"):
    """What the gaps need from a full assessment."""
    here = next((loc for loc in a.get("locations") or [] if loc.get("code") == country), None)
    en = lambda x: ((x or {}).get("description") or {}).get("en")
    return {
        "id": a["assessment_id"], "taxon_id": a.get("sis_taxon_id"), "name": (a.get("taxon") or {}).get("scientific_name"),
        "category": (a.get("red_list_category") or {}).get("code"), "criteria": a.get("criteria"),
        "year": int(a["year_published"]) if a.get("year_published") else None, "trend": en(a.get("population_trend")),
        "possibly_extinct": bool(a.get("possibly_extinct")), "possibly_extinct_in_the_wild": bool(a.get("possibly_extinct_in_the_wild")),
        "threats": [[t.get("code"), t.get("timing"), t.get("scope"), t.get("severity")] for t in a.get("threats") or []],
        "habitats": [[h.get("code"), h.get("majorImportance"), h.get("suitability")] for h in a.get("habitats") or []],
        "systems": [en(s) for s in a.get("systems") or []],
        "india": None if here is None else {"origin": here.get("origin"), "presence": here.get("presence"),
                                            "endemic": bool(here.get("is_endemic"))},
        "url": a.get("url"),
        # IUCN asks that an assessment be cited like a journal paper: its authors (the assessors) and year.
        "citation": a.get("citation"),
        "assessors": next((c.get("full") for c in a.get("credits") or [] if c.get("credit_type_name") == "assessor"), None),
    }


def latest_global(assessments):
    """The id of the latest global assessment in a list, or None."""
    return next((x["assessment_id"] for x in assessments or []
                 if x.get("latest") and any(s.get("code") == GLOBAL for s in x.get("scopes") or [])), None)


def harvest(api, store, names, deadline=None, log=print):
    """Run the three stages for these names (the list's species with an IUCN category). True when complete; False
    when the time limit stopped it (the store keeps the progress, and the next run continues)."""
    d = store.data
    version = api.get("information/red_list_version")["red_list_version"]
    if d.get("version") != version:
        log(f"Red List version {version} (store: {d.get('version')}): reading India's list and the names again")
        d.update(version=version, pages={}, names={}, india_done=False)
    late = lambda: deadline is not None and time.monotonic() > deadline
    try:
        # 1. India's list.
        page, total = 1, d.get("total_pages")
        while not d.get("india_done"):
            if late():
                return False
            if str(page) not in d["pages"]:
                body, total = api.get("countries/IN", {"page": page, "latest": "true", "scope_code": GLOBAL})
                d["pages"][str(page)] = [[x["taxon_scientific_name"], x["assessment_id"]] for x in body["assessments"]
                                         if x.get("latest") and any(s.get("code") == GLOBAL for s in x.get("scopes") or [])]
                d["total_pages"] = total
                store.maybe_save()
            page += 1
            d["india_done"] = page > (total or d.get("total_pages") or 0)
        india = {n: i for rows in d["pages"].values() for n, i in rows}
        d["india"] = india
        # 2. The other names, one lookup each.
        todo = [n for n in names if n not in india and n not in d["names"]]
        for k, name in enumerate(todo, 1):
            if late():
                return False
            genus, _, species = name.partition(" ")
            found = api.get("taxa/scientific_name", {"genus_name": genus, "species_name": species})
            d["names"][name] = latest_global((found or {}).get("assessments"))
            store.maybe_save()
            if k % 250 == 0:
                log(f"names: {k} of {len(todo)} looked up")
        # 3. Every assessment in full.
        ids = sorted({str(i) for i in [*india.values(), *d["names"].values()] if i is not None} - set(d["assessments"]))
        for k, aid in enumerate(ids, 1):
            if late():
                return False
            full = api.get(f"assessment/{aid}")
            if full is not None:
                d["assessments"][aid] = compact(full)
            store.maybe_save()
            if k % 250 == 0:
                log(f"assessments: {k} of {len(ids)} fetched")
        return True
    finally:
        store.save()


def rows(store):
    """One row per name of the list with an assessment: the name as the list has it."""
    d, out = store.data, []
    india = d.get("india") or {}
    for name, aid in [*india.items(), *d.get("names", {}).items()]:
        a = d["assessments"].get(str(aid)) if aid is not None else None
        if not a:
            continue
        here = a["india"] or {}
        out.append({"name": name, "assessment_id": a["id"], "taxon_id": a["taxon_id"], "category": a["category"],
                    "criteria": a["criteria"], "year": a["year"], "trend": a["trend"],
                    "possibly_extinct": a["possibly_extinct"], "possibly_extinct_in_the_wild": a["possibly_extinct_in_the_wild"],
                    "threats": [t[0] for t in a["threats"]], "habitats": [h[0] for h in a["habitats"]],
                    "in_india_list": name in india, "india_origin": here.get("origin"),
                    "india_presence": here.get("presence"), "india_endemic": here.get("endemic"), "url": a["url"],
                    "citation": a.get("citation"), "assessors": a.get("assessors")})
    return out


def master_path(s3, layers=ROOT / "data" / "layers" / "master", cache=CACHE):
    """The newest local master.parquet, else the published one that R2's layers/master/latest.json names (on Actions
    there is no local build). None when there is neither."""
    from pipeline import r2
    local = sorted(layers.glob("*/master.parquet"))
    if local:
        return local[-1]
    latest = r2.get_json(s3, "layers/master/latest.json") if s3 else None
    if not latest or not latest.get("base"):
        return None
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / f"master_{latest['base'].strip('/').replace('/', '_')}.parquet"   # one file per build: never stale
    r2.restore(s3, latest["base"] + "master.parquet", dest)
    return dest


def main():
    import duckdb
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
    p = argparse.ArgumentParser()
    p.add_argument("--master", help="master.parquet of the list (default: the newest local build, else R2's)")
    p.add_argument("--minutes", type=float, help="stop after this many minutes; the next run continues")
    p.add_argument("--local", action="store_true", help="keep the store on this machine only (no copy to R2)")
    a = p.parse_args()
    s3 = upload = None
    if os.environ.get("R2_ENDPOINT") and not a.local:
        from pipeline import r2
        s3 = r2.client()
        r2.restore(s3, R2_PREFIX + "store.json", CACHE / "store.json")
        upload = lambda path: r2.sync_file(s3, path, R2_PREFIX + path.name, immutable=False)
    master = Path(a.master) if a.master else master_path(s3)
    if master is None:
        raise SystemExit("no master list: build one, or give --master")
    names = sorted({n for (n,) in duckdb.sql(f"SELECT name FROM '{master}' WHERE iucn <> 'NE'").fetchall()})
    print(f"{len(names)} assessed species on the list ({master})", flush=True)
    store = Store(CACHE / "store.json", upload)
    deadline = time.monotonic() + a.minutes * 60 if a.minutes else None
    api = Api(os.environ["IUCN_TOKEN"])
    done = harvest(api, store, names, deadline, log=lambda m: print(m, flush=True))
    out = rows(store)
    print(f"{'complete' if done else 'stopped at the time limit'}: {len(out)} species with an assessment; "
          f"{api.count} requests this run", flush=True)
    if out:
        import pyarrow as pa
        import pyarrow.parquet as pq
        path = CACHE / "iucn_detail.parquet"
        pq.write_table(pa.Table.from_pylist(out), path, compression="zstd")
        if s3:
            from pipeline import r2
            r2.sync_file(s3, path, R2_PREFIX + path.name, immutable=False)


if __name__ == "__main__":
    main()
