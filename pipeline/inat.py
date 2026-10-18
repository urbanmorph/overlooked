"""iNaturalist species lists for the master list: per state, species research grade and needs ID, genera of
observations named only to genus, and counts of observations named only above genus.

iNaturalist asks for at most 60 requests a minute and under 10,000 a day, and for no scraping.
We send one request at a time, about 1.1 s apart, with a budget per run, and cache every answer.
A run that hits its budget or time limit stops cleanly; the next run continues where it stopped.
Run through pipeline.layer_inat.
"""

import json
import time
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
# iNaturalist's iconic groups.
GROUPS = ["Plantae", "Insecta", "Aves", "Fungi", "Arachnida", "Mollusca", "Reptilia", "Amphibia",
          "Mammalia", "Actinopterygii", "Animalia", "Chromista", "Protozoa"]


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


QUALITIES = ("research", "needs_id")
PER_PAGE = 500


def species_places(places):
    """[(area code, place id)]: each state with an iNaturalist place, then India (species with no state place)."""
    return [(code, v["place_id"]) for code, v in sorted(places.items(), key=lambda kv: int(kv[0])) if v["place_id"]] + \
        [("india", str(INDIA))]


def page_through(client, d, save, **params):
    """Fetch observations/species_counts pages into d ({page, total, rows}) from where it stopped, saving
    after every page. Rows: [taxon id, name, iconic group, observations]."""
    while d["total"] is None or d["page"] * PER_PAGE < d["total"]:
        res = client.get("observations/species_counts", per_page=PER_PAGE, page=d["page"] + 1, **params)
        d["rows"] += [[r["taxon"]["id"], r["taxon"]["name"], r["taxon"].get("iconic_taxon_name"), r["count"]]
                      for r in res["results"]]
        d["page"], d["total"] = d["page"] + 1, res["total_results"]
        save()
        if not res["results"]:
            break


def species_counts(client, areas, month):
    """Species observed in each area, research grade and needs ID separately (observations/species_counts,
    taxa at species rank or below). Saved after every page in species_counts_<month>.json, so a stopped run
    continues at the next page. Raises Budget when the request budget or time limit is reached."""
    name = f"species_counts_{month}.json"
    done = cached(name) or {}
    for code, pid in areas:
        for q in QUALITIES:
            d = done.setdefault(f"{code}|{q}", {"place_id": str(pid), "page": 0, "total": None, "rows": []})
            page_through(client, d, lambda: store(name, done), place_id=pid, quality_grade=q, hrank="species")
    return done


def genus_counts(client, areas, month):
    """Genera of the needs-ID observations named only to genus, per area (observations/species_counts with
    rank=genus). Saved after every page in genus_counts_<month>.json; a stopped run continues."""
    name = f"genus_counts_{month}.json"
    done = cached(name) or {}
    for code, pid in areas:
        d = done.setdefault(code, {"place_id": str(pid), "page": 0, "total": None, "rows": []})
        page_through(client, d, lambda: store(name, done), place_id=pid, quality_grade="needs_id", rank="genus")
    return done


def genus_doc(done, areas, as_of):
    """Layer file: per area, rows [genus taxon id, genus, iconic group, observations]."""
    lists = {}
    for code, _ in areas:
        if code in done:
            seen = {}
            for row in done[code]["rows"]:  # counts can shift between pages; keep one row per taxon
                seen.setdefault(row[0], row)
            lists[code] = list(seen.values())
    complete = all((d := done.get(c)) and d["total"] is not None and d["page"] * PER_PAGE >= d["total"] for c, _ in areas)
    return {"as_of": as_of, "complete": complete, "places": dict(areas), "lists": lists}


def coarse_counts(client, areas, month, groups=GROUPS):
    """Needs-ID observations named only above genus (subtribe or higher), per area and iconic group: one
    count request each. Saved after every answer in coarse_counts_<month>.json; a stopped run continues."""
    name = f"coarse_counts_{month}.json"
    done = cached(name) or {}
    for code, pid in areas:
        for g in groups:
            if f"{code}|{g}" in done:
                continue
            res = client.get("observations", place_id=pid, quality_grade="needs_id", lrank="subtribe",
                             iconic_taxa=g, per_page=0)
            done[f"{code}|{g}"] = res["total_results"]
            store(name, done)
    return done


def coarse_doc(done, areas, as_of, groups=GROUPS):
    counts = {code: {g: done[f"{code}|{g}"] for g in groups if f"{code}|{g}" in done} for code, _ in areas}
    complete = all(f"{c}|{g}" in done for c, _ in areas for g in groups)
    return {"as_of": as_of, "complete": complete, "places": dict(areas), "counts": counts}


def species_doc(done, areas, as_of):
    """Layer file: per area and quality, rows [taxon id, name, iconic group, observations]. complete is
    true when every area and quality was fetched to the last page."""
    lists = {}
    for code, _ in areas:
        for q in QUALITIES:
            d = done.get(f"{code}|{q}")
            if d:
                seen = {}
                for row in d["rows"]:  # counts can shift between pages; keep one row per taxon
                    seen.setdefault(row[0], row)
                lists.setdefault(code, {})[q] = list(seen.values())
    complete = all((d := done.get(f"{c}|{q}")) and d["total"] is not None and d["page"] * PER_PAGE >= d["total"]
                   for c, _ in areas for q in QUALITIES)
    return {"as_of": as_of, "complete": complete, "places": dict(areas), "lists": lists}
