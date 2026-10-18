"""Monthly iNaturalist layer: the species lists the master list reads.

1. Restore the iNaturalist cache from R2 (cache/inat/), so a run continues where the last one stopped.
2. Map each state to an iNaturalist place (cached for good).
3. Per state and for India: species research grade and needs ID, genera of observations named only to genus,
   and counts of observations named only above genus per iconic group. About 1,400 requests a month.
4. Write layers/inat/<month>/{species,genus,coarse}_counts.json and layers/inat/latest.json to R2, and save
   the cache.

Safe to run again: finished parts are skipped, and a stopped part continues from its cache.

Usage: python -m pipeline.layer_inat [--publish] [--budget 9000] [--minutes 240]
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline import inat

ROOT = Path(__file__).resolve().parent.parent
DAILY = 9000  # iNaturalist asks for under 10,000 requests a day, across all runs


def budget_left(budget, day):
    """Requests this run may send: its own budget, less what earlier runs used on the same UTC day."""
    used = (inat.cached("usage.json") or {}).get(day, 0)
    return max(0, min(budget, DAILY - used))


def record_usage(day, n):
    usage = inat.cached("usage.json") or {}
    usage = {day: usage.get(day, 0) + n}  # only today is needed
    inat.store("usage.json", usage)


def sync_cache(s3, direction):
    from pipeline import r2
    names = ["usage.json", "places.json", "species_counts_{m}.json", "genus_counts_{m}.json", "coarse_counts_{m}.json"]
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    for n in (x.format(m=month) for x in names):
        local, key = inat.CACHE / n, f"cache/inat/{n}"
        if direction == "down":
            obj = r2.get_json(s3, key)
            if obj is not None:
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_text(json.dumps(obj, ensure_ascii=False))
        elif local.exists():
            r2.sync_file(s3, local, key, immutable=False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--publish", action="store_true")
    p.add_argument("--budget", type=int, default=9000)
    p.add_argument("--minutes", type=int, help="stop cleanly and publish after this many minutes")
    a = p.parse_args()
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    s3 = None
    if a.publish:
        from dotenv import load_dotenv
        from pipeline import r2
        load_dotenv(ROOT / ".env", override=True)  # local runs; in Actions the secrets are set directly
        s3 = r2.client()
        sync_cache(s3, "down")

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    recorded = 0

    def save(c):
        nonlocal recorded
        record_usage(day, c.used - recorded)
        recorded = c.used
        if s3:
            sync_cache(s3, "up")

    def checkpoint(c):
        print(f"{datetime.now(timezone.utc):%H:%M} {c.used} requests; saving the cache", flush=True)
        save(c)

    budget = budget_left(a.budget, day)
    print(f"budget for this run: {budget} requests", flush=True)
    client = inat.Client(budget, a.minutes, checkpoint)
    try:
        run(a, month, client, s3)
    finally:
        save(client)  # keep the work done and the day's count, also when the run fails


def run(a, month, client, s3):
    from pipeline import r2
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        areas = inat.species_places(inat.places(client))
        inat.species_counts(client, areas, month)
        inat.genus_counts(client, areas, month)
        inat.coarse_counts(client, areas, month)
    except inat.Budget as e:
        print(f"stopped: {e}; the next run continues")
    areas = inat.species_places(inat.cached("places.json") or {})
    docs = {"species_counts": inat.species_doc(inat.cached(f"species_counts_{month}.json") or {}, areas, today),
            "genus_counts": inat.genus_doc(inat.cached(f"genus_counts_{month}.json") or {}, areas, today),
            "coarse_counts": inat.coarse_doc(inat.cached(f"coarse_counts_{month}.json") or {}, areas, today)}
    out = inat.LAYERS / month
    out.mkdir(parents=True, exist_ok=True)
    info = {"month": month, "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "requests": client.used}
    for name, doc in docs.items():
        has = doc.get("lists") or any((doc.get("counts") or {}).values())
        if has:
            (out / f"{name}.json").write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))
        info[name] = f"layers/inat/{month}/{name}.json" if has else None
        info[f"{name}_complete"] = doc["complete"]
    if s3:
        for f in out.iterdir():
            r2.sync_file(s3, f, f"layers/inat/{month}/{f.name}", immutable=False)
        r2.put_json(s3, info, "layers/inat/latest.json")
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
