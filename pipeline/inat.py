"""Module 5: iNaturalist identification backlog, and a direct check of quiet species.

iNaturalist asks for at most 60 requests a minute and under 10,000 a day, and for no scraping.
We send one request at a time, about 1.1 s apart, with a budget per run (default 9,000), and cache
every answer. A run that hits its budget stops cleanly; the next run continues where it stopped.

Usage:
    python -m pipeline.inat places
    python -m pipeline.inat backlog [--places India,Kerala] [--groups Insecta,Plantae]
    python -m pipeline.inat quiet <species.json> [--limit 50]
Output goes to data/layers/inat/<date>/.
"""

import argparse
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from pipeline import health

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.inaturalist.org/v1"
CACHE = ROOT / "data" / "cache" / "inat"
LAYERS = ROOT / "data" / "layers" / "inat"
INDIA = 6681
GAP = 1.1
CHECKPOINT = 600  # seconds
# iNaturalist's iconic groups; "unknown" means no taxon at all.
GROUPS = ["Plantae", "Insecta", "Aves", "Fungi", "Arachnida", "Mollusca", "Reptilia", "Amphibia",
          "Mammalia", "Actinopterygii", "Animalia", "Chromista", "Protozoa", "unknown"]


class Budget(Exception):
    pass


class Client:
    """minutes: stop cleanly after this time. checkpoint: called about every 10 minutes
    (for example to save the cache to R2), so a run that is killed loses little."""

    def __init__(self, budget=9000, minutes=None, checkpoint=None):
        self.http = requests.Session()
        self.http.headers["User-Agent"] = health.ua()
        self.budget = budget
        self.used = 0
        self.last = 0.0
        self.deadline = time.monotonic() + minutes * 60 if minutes else None
        self.checkpoint = checkpoint
        self.next_checkpoint = time.monotonic() + CHECKPOINT

    def get(self, path, **params):
        if self.used >= self.budget:
            raise Budget(f"request budget of {self.budget} used")
        if self.deadline and time.monotonic() > self.deadline:
            raise Budget(f"time limit reached after {self.used} requests")
        if self.checkpoint and time.monotonic() > self.next_checkpoint:
            self.next_checkpoint = time.monotonic() + CHECKPOINT
            self.checkpoint(self)
        for attempt in range(5):
            wait = GAP - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.used += 1
            try:
                r = self.http.get(f"{API}/{path}", params=params, timeout=60)
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(15 * (attempt + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(int(r.headers.get("Retry-After", 0)) or 30 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        raise requests.ConnectionError(f"iNaturalist did not answer after 5 tries: {path}")


def cached(name):
    p = CACHE / name
    return json.loads(p.read_text()) if p.exists() else None


def store(name, obj):
    p = CACHE / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False))


def state_names():
    """State and union territory names from the LGD boundary file."""
    import duckdb
    from pipeline import districts
    from pipeline.boundaries import title
    rows = duckdb.sql(f"SELECT DISTINCT stname, state_lgd FROM '{districts.PATH}' ORDER BY 1").fetchall()
    return [(title(n), code) for n, code in rows]


# Where iNaturalist's places do not match LGD one to one. Several ids are joined with commas
# (iNaturalist treats them as "any of"). Checked 16 October 2026.
OVERRIDES = {
    "Ladakh": ("184748", "Ladakh Union Territory"),
    "Dadra, Nagar Haveli, Daman & Diu": (None, "Dadra and Nagar Haveli + Daman and Diu"),  # ids filled below
}
DNHDD_EXTRA = "10790"  # Daman and Diu


def places(client):
    """Map each LGD state to an iNaturalist place (admin level 10 inside India). Cached for good."""
    known = cached("places.json") or {}
    for name, code in state_names():
        if str(code) in known:
            continue
        q = name.replace("&", "and").split(",")[0]
        res = client.get("places/autocomplete", q=q)["results"]
        pick = [p for p in res if p.get("admin_level") == 10 and INDIA in (p.get("ancestor_place_ids") or [])]
        pid, pname = (str(pick[0]["id"]), pick[0]["name"]) if pick else (None, None)
        if name in OVERRIDES:
            o_id, o_name = OVERRIDES[name]
            pid = o_id or (f"{pid},{DNHDD_EXTRA}" if pid else DNHDD_EXTRA)
            pname = o_name
        known[str(code)] = {"state": name, "place_id": pid, "place_name": pname}
        store("places.json", known)
    return known


def backlog(client, place_ids, groups=GROUPS, month=None):
    """Needs-ID observations by year created, and research-grade totals, per place and group.
    Each row is saved as it completes, so a stopped run continues."""
    name = f"backlog_rows_{month}.json" if month else None
    done = (cached(name) or {}) if name else {}
    for pid in place_ids:
        for g in groups:
            key = f"{pid}|{g}"
            if key in done:
                continue
            h = client.get("observations/histogram", place_id=pid, quality_grade="needs_id", iconic_taxa=g,
                           date_field="created", interval="year")["results"]["year"]
            rg = client.get("observations", place_id=pid, quality_grade="research", iconic_taxa=g, per_page=0)
            done[key] = {"place_id": pid, "group": g, "research_grade": rg["total_results"],
                         "needs_id_by_year": {k[:4]: v for k, v in h.items() if v}}
            if name:
                store(name, done)
    return [done[f"{pid}|{g}"] for pid in place_ids for g in groups]


def identifiers(client, groups=GROUPS):
    since = (date.today() - timedelta(days=365)).isoformat()
    out = []
    for g in groups:
        if g == "unknown":
            continue
        d = client.get("observations/identifiers", place_id=INDIA, iconic_taxa=g, d1=since, per_page=1)
        top = d["results"][0]["count"] if d["results"] else 0
        out.append({"group": g, "identifiers_12m": d["total_results"], "top_identifier_count": top, "since": since})
    return out


def taxon_id(client, name):
    """iNaturalist taxon for an exact species name, or None. Cached for good (including misses)."""
    cache = cached("taxa.json") or {}
    if name in cache:
        return cache[name]
    res = client.get("taxa", q=name, rank="species", per_page=5)["results"]
    hit = next((t["id"] for t in res if t.get("name", "").lower() == name.lower()), None)
    cache[name] = hit
    store("taxa.json", cache)
    return hit


def latest_in_india(client, tid):
    d = client.get("observations", taxon_id=tid, place_id=INDIA, order_by="observed_on", order="desc",
                   per_page=1, verifiable="any")
    if not d["results"]:
        return {"total": 0}
    r = d["results"][0]
    return {"total": d["total_results"], "latest": r.get("observed_on"), "quality": r.get("quality_grade"),
            "licence": r.get("license_code"), "observation": r.get("id")}


def quiet_check(client, species, month):
    """species: list of {key, name}. Results cached per month, so a stopped run continues."""
    name = f"quiet_{month}.json"
    done = cached(name) or {}
    try:
        for s in species:
            if s["key"] in done:
                continue
            tid = taxon_id(client, s["name"])
            done[s["key"]] = {"name": s["name"], "taxon_id": tid, **(latest_in_india(client, tid) if tid else {"total": None})}
            if len(done) % 25 == 0:
                store(name, done)
    except Budget as e:
        print(f"stopped: {e}; {len(done)} of {len(species)} species checked; the next run continues")
    store(name, done)
    return done


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["places", "backlog", "quiet"])
    p.add_argument("arg", nargs="?")
    p.add_argument("--places", help="comma-separated state names, or India")
    p.add_argument("--groups", help="comma-separated iconic groups")
    p.add_argument("--limit", type=int)
    p.add_argument("--budget", type=int, default=9000)
    a = p.parse_args()
    c = Client(a.budget)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = LAYERS / today
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "places":
        print(json.dumps(places(c), indent=1, ensure_ascii=False))
    elif a.cmd == "backlog":
        pl = places(c)
        wanted = a.places.split(",") if a.places else None
        ids = [INDIA] if not wanted or "India" in wanted else []
        ids += [v["place_id"] for v in pl.values() if v["place_id"] and (not wanted or v["state"] in wanted)]
        groups = a.groups.split(",") if a.groups else GROUPS
        res = {"as_of": today, "places": pl, "backlog": backlog(c, ids, groups), "identifiers": identifiers(c, groups)}
        (out / "backlog.json").write_text(json.dumps(res, separators=(",", ":"), ensure_ascii=False))
        print(f"backlog: {len(res['backlog'])} place x group rows, {c.used} requests")
    else:
        species = json.loads(Path(a.arg).read_text())[: a.limit]
        res = quiet_check(c, species, today[:7])
        (out / "quiet.json").write_text(json.dumps(res, separators=(",", ":"), ensure_ascii=False))
        print(f"quiet check: {len(res)} species, {c.used} requests")


if __name__ == "__main__":
    main()
