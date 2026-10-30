"""The Bibliography of South Asian Ornithology, compiled by Aasheesh Pittie (southasiaornith.in): papers per bird
name. The bibliography is a public Zotero group (api.zotero.org/groups/5518417), about 41,000 papers since 1713, each
tagged with the species it treats ("BUBO BENGALENSIS") among places and topics.

Terms: no licence is stated; Zotero claims no ownership of library content. The owner approved using counts and years
per bird with credit to Aasheesh Pittie (30 October 2026). We publish only those counts and years, never the records.

Fetch: the Zotero web API, 100 items a request. The first pass reads the whole library (about 660 requests, notes and
attachments included, then left out); later passes ask only for items changed since the library version of the last
pass, and for items deleted since then. The API's Backoff and Retry-After headers are obeyed. The state (library
version, items, and the position of a pass that stopped) is saved every 10 minutes and on exit, locally and in R2
cache/zotero/ (never served), so a stopped run continues and a run with no changes asks two short questions.

Output: zotero_species.csv: name (from a two- or three-word tag, as a binomial), papers, first_year, latest_year. Tags
that are not species (places such as "SRI LANKA") come through too; the master list keeps only names it can match to
a bird.

Usage: .venv/bin/python -m pipeline.zotero [--publish] [--minutes N]
"""

import csv
import json
import re
import time
from pathlib import Path

from pipeline.util import log

ROOT = Path(__file__).resolve().parent.parent
GROUP = 5518417
API = f"https://api.zotero.org/groups/{GROUP}"
CACHE = ROOT / "data" / "cache" / "zotero"
R2_DIR = "cache/zotero/"
TABLE = "zotero_species.csv"
PAGE = 100
SAVE_EVERY = 600     # seconds
TRIES = 4
SKIP = {"note", "attachment", "annotation"}
TAG = re.compile(r"[A-Z]+(?:-[A-Z]+)? [A-Z]+(?:-[A-Z]+)?(?: [A-Z]+(?:-[A-Z]+)?)?")
YEAR = re.compile(r"\b(1[6-9]\d\d|20\d\d)\b")


def names_of(tags):
    """Binomials (or trinomials) from the tags that look like species names."""
    return [t.capitalize() for t in tags if TAG.fullmatch(t)]


def get(http, url, params):
    """One API request; Backoff and Retry-After are obeyed, and a failed request is asked again, waiting longer."""
    import requests
    for i in range(TRIES):
        try:
            r = http.get(url, params=params, timeout=120)
            wait = r.headers.get("Retry-After") if getattr(r, "status_code", 200) in (429, 503) else None
            if wait:
                time.sleep(int(wait))
                continue
            r.raise_for_status()
            if r.headers.get("Backoff"):
                time.sleep(int(r.headers["Backoff"]))
            return r
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.HTTPError):
            if i == TRIES - 1:
                raise
            time.sleep(15 * (i + 1))
    raise RuntimeError(f"{url}: no answer after {TRIES} tries")


def sync(http, state, page=PAGE, deadline=None, pages=None, save=None):
    """Bring state ({version, items: {key: [year, tags]}, pending?}) up to the library's version. True when done;
    False when the deadline (time.monotonic()) or `pages` stopped it (state.pending says where to go on)."""
    since = state.get("version", 0)
    if "pending" not in state:
        if since:
            r = get(http, f"{API}/deleted", {"since": since})
            for k in r.json().get("items", []):
                state.setdefault("items", {}).pop(k, None)
        state["pending"] = {"since": since, "start": 0, "version": None}
    p, done, saved = state["pending"], 0, time.monotonic()
    while True:
        if (deadline is not None and time.monotonic() >= deadline) or (pages is not None and done >= pages):
            log(f"zotero: stopped at item {p['start']}; the next run continues")
            return False
        r = get(http, f"{API}/items", {"since": p["since"], "start": p["start"], "limit": page, "format": "json"})
        p["version"] = p["version"] or int(r.headers.get("Last-Modified-Version", 0))
        rows = r.json()
        for it in rows:
            d = it["data"]
            if d.get("itemType") in SKIP or d.get("parentItem"):
                continue
            year = YEAR.search(d.get("date") or "")
            state.setdefault("items", {})[it["key"]] = [int(year[1]) if year else None, [t["tag"] for t in d.get("tags", [])]]
        p["start"] += len(rows)
        done += 1
        if p["start"] % (page * 50) == 0:
            log(f"zotero: {p['start']} of {r.headers.get('Total-Results', '?')} items read")
        if save and time.monotonic() - saved >= SAVE_EVERY:
            save()
            saved = time.monotonic()
        if len(rows) < page:
            state["version"] = p["version"]
            del state["pending"]
            return True


def write_table(state, path: Path):
    """name, papers, first_year, latest_year for each name tag."""
    agg = {}
    for year, tags in state.get("items", {}).values():
        for n in set(names_of(tags)):
            a = agg.setdefault(n, [0, None, None])
            a[0] += 1
            if year:
                a[1] = year if a[1] is None else min(a[1], year)
                a[2] = year if a[2] is None else max(a[2], year)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with tmp.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "papers", "first_year", "latest_year"])
        w.writerows([n, *a] for n, a in sorted(agg.items()))
    tmp.replace(path)
    return path


def refresh(http, s3, cache: Path = CACHE, deadline=None):
    """The table, from the saved state (local, else R2's) brought up to date; with s3, state and table kept in R2.
    Returns the table path (a partial first pass still writes what it has read)."""
    from pipeline import r2
    cache.mkdir(parents=True, exist_ok=True)
    local = cache / "state.json"
    state = json.loads(local.read_text()) if local.exists() else (r2.get_json(s3, R2_DIR + "state.json") if s3 else None) or {}

    def save():
        tmp = local.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, separators=(",", ":")))
        tmp.replace(local)
        if s3:
            r2.sync_file(s3, local, R2_DIR + local.name, immutable=False)

    try:
        complete = sync(http, state, deadline=deadline, save=save)
    finally:
        save()
    table = write_table(state, cache / TABLE)
    log(f"zotero: {len(state.get('items', {}))} papers{'' if complete else ' so far'}, library version {state.get('version')}")
    if s3:
        r2.sync_file(s3, table, R2_DIR + TABLE, immutable=False)
    return table


def main():
    import argparse

    import requests

    from pipeline import health
    a = argparse.ArgumentParser()
    a.add_argument("--publish", action="store_true", help="read and keep the state and table in R2 (cache/zotero/)")
    a.add_argument("--minutes", type=float, help="stop after this time; the next run continues")
    args = a.parse_args()
    http = requests.Session()
    http.headers["User-Agent"] = health.ua()
    s3 = None
    if args.publish:
        from dotenv import load_dotenv

        from pipeline import r2
        load_dotenv(ROOT / ".env", override=True)
        s3 = r2.client()
    refresh(http, s3, deadline=time.monotonic() + args.minutes * 60 if args.minutes else None)


if __name__ == "__main__":
    main()
