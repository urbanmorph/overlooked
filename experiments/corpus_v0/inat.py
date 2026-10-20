"""Read-only iNaturalist API client for corpus v0: observations by id, 200 per request.

Polite by construction: at least 1.1 s between requests, a persisted daily count that stops at 8,500
(the limit asked is under 9,000 a day), User-Agent from pipeline.health.ua(), and backoff on 429 or 5xx.
Nothing is ever posted.

Cache: one JSON line per observation (slimmed) in the given .jsonl file, appended and flushed after every
request, so a stopped run continues and a rerun asks only for ids not in the file. Ids the API does not
return (deleted or made private) are written as {"id": .., "missing": true}.
"""

import json
import time
from datetime import date
from pathlib import Path

import requests
from lib import DATA, atomic_write_json, log, read_json, ua

API = "https://api.inaturalist.org/v1/observations"
GAP_S = 1.1
DAILY_CAP = 8500
BATCH = 200
COUNTER = DATA / "inat_requests.json"
_last = [0.0]


def _count():
    c = read_json(COUNTER, {})
    today = date.today().isoformat()
    if c.get(today, 0) >= DAILY_CAP:
        raise SystemExit(f"iNaturalist daily request cap reached ({DAILY_CAP}); run again tomorrow")
    c[today] = c.get(today, 0) + 1
    atomic_write_json(COUNTER, c)


def _get(http, params):
    for attempt, backoff in enumerate((0, 30, 60, 120, 300)):
        time.sleep(max(0.0, GAP_S - (time.time() - _last[0])) + backoff)
        _count()
        _last[0] = time.time()
        try:
            r = http.get(API, params=params, timeout=120)
        except requests.RequestException as e:
            log(f"  iNat: {type(e).__name__}; retry {attempt + 1}")
            continue
        if r.status_code == 429 or r.status_code >= 500:
            log(f"  iNat: HTTP {r.status_code}; retry {attempt + 1}")
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("iNaturalist: gave up after retries")


def _taxon(t):
    if not t:
        return None
    keep = ("id", "name", "rank", "min_species_taxon_id", "ancestor_ids")
    return {k: t.get(k) for k in keep}


def slim(o):
    return {
        "id": o["id"],
        "created_at": o.get("created_at"),
        "quality_grade": o.get("quality_grade"),
        "user": {k: (o.get("user") or {}).get(k) for k in ("id", "login", "name")},
        "taxon": _taxon(o.get("taxon")),
        "community_taxon_id": o.get("community_taxon_id"),
        "identifications": [
            {
                "created_at": i.get("created_at"),
                "current": i.get("current"),
                "disagreement": i.get("disagreement"),
                "hidden": i.get("hidden"),
                "user": {"id": (i.get("user") or {}).get("id")},
                "taxon": _taxon(i.get("taxon")),
            }
            for i in o.get("identifications") or []
        ],
        "photos": [
            {"id": p.get("id"), "license_code": p.get("license_code"), "url": p.get("url")}
            for p in (o.get("photos") or [])[:1]
        ],
    }


def load(cache: Path):
    out = {}
    if cache.exists():
        with cache.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    o = json.loads(line)
                    out[o["id"]] = o
    return out


def fetch(ids, cache: Path):
    """Observations by id (slimmed dicts), from the cache or the API."""
    have = load(cache)
    todo = sorted({int(i) for i in ids} - set(have))
    log(f"iNat: {len(have):,} cached, {len(todo):,} to fetch in {-(-len(todo) // BATCH)} requests")
    if todo:
        with requests.Session() as http, cache.open("a") as f:
            http.headers["User-Agent"] = ua()
            for n, i in enumerate(range(0, len(todo), BATCH), 1):
                chunk = todo[i : i + BATCH]
                js = _get(http, {"id": ",".join(map(str, chunk)), "per_page": BATCH})
                got = {o["id"]: slim(o) for o in js.get("results", [])}
                for oid in chunk:
                    o = got.get(oid, {"id": oid, "missing": True})
                    have[oid] = o
                    f.write(json.dumps(o) + "\n")
                f.flush()
                if n % 10 == 0 or i + BATCH >= len(todo):
                    log(f"  iNat: {min(i + BATCH, len(todo)):,}/{len(todo):,} fetched")
    return {int(i): have[int(i)] for i in ids}


def search(params):
    """One observation search (read only), with the same spacing, daily cap and retries as fetch()."""
    with requests.Session() as http:
        http.headers["User-Agent"] = ua()
        return _get(http, params)
