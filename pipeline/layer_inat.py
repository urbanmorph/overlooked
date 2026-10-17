"""Monthly iNaturalist layer (module 5), published next to the GBIF snapshot.

1. Restore the iNaturalist cache from R2 (cache/inat/), so a run continues where the last one stopped.
2. Backlog by state and group, and active identifiers (once a month).
3. Direct check of the species that are quiet in the latest published snapshot, oldest first,
   within the daily request budget.
4. Write layers/inat/<month>/{backlog,quiet}.json and layers/inat/latest.json to R2, and save the cache.

Safe to run again: finished parts are skipped, and the quiet check continues from its cache.

Usage: python -m pipeline.layer_inat [--publish] [--budget 9000]
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline import inat

ROOT = Path(__file__).resolve().parent.parent


def sync_cache(s3, direction):
    from pipeline import r2
    names = ["places.json", "taxa.json", "backlog_{m}.json", "backlog_rows_{m}.json", "quiet_{m}.json"]
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
    p.add_argument("--quiet-file", help="local ledger/india.json to use instead of the published one")
    a = p.parse_args()
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    s3 = None
    if a.publish:
        from dotenv import load_dotenv
        from pipeline import r2
        load_dotenv(ROOT / ".env", override=True)  # local runs; in Actions the secrets are set directly
        s3 = r2.client()
        sync_cache(s3, "down")

    def checkpoint(c):
        print(f"{datetime.now(timezone.utc):%H:%M} {c.used} requests; saving the cache", flush=True)
        if s3:
            sync_cache(s3, "up")

    client = inat.Client(a.budget, a.minutes, checkpoint)
    try:
        run(a, month, client, s3)
    finally:
        if s3:  # keep the work done, also when the run fails
            sync_cache(s3, "up")


def run(a, month, client, s3):
    from pipeline import r2

    # Backlog and identifiers, once a month.
    bl = inat.cached(f"backlog_{month}.json")
    try:
        if not bl:
            places = inat.places(client)
            ids = [inat.INDIA] + [v["place_id"] for v in places.values() if v["place_id"]]
            bl = {"as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "places": places,
                  "backlog": inat.backlog(client, ids, month=month), "identifiers": inat.identifiers(client)}
            inat.store(f"backlog_{month}.json", bl)
    except inat.Budget as e:
        print(f"backlog stopped: {e}; the next run continues")
        bl = None

    # Direct check of quiet species from the latest published snapshot (oldest latest record first).
    if a.quiet_file:
        rows = json.loads(Path(a.quiet_file).read_text())["rows"]
        run_id = "local"
    else:
        latest = r2.get_json(s3, "latest.json") if s3 else None
        if not latest:
            print("no published snapshot yet; skipping the quiet check")
            rows, run_id = [], None
        else:
            rows = r2.get_json(s3, latest["base"] + "ledger/india.json")["rows"]
            run_id = latest["run_id"]
    species = [{"key": r[0], "name": r[1]} for r in sorted(rows, key=lambda r: (r[5] or 0)) if r[1]]
    quiet = inat.quiet_check(client, species, month) if species else {}
    complete = len(quiet) >= len(species)

    out = inat.LAYERS / month
    out.mkdir(parents=True, exist_ok=True)
    if bl:
        (out / "backlog.json").write_text(json.dumps(bl, separators=(",", ":"), ensure_ascii=False))
    # Small file for the ledger page: only species with an observation in India.
    # [latest date, quality grade, open licence (1/0), observations in India]
    open_lic = {"cc0", "cc-by", "cc-by-nc"}
    flags = {k: [v["latest"], v["quality"], int((v.get("licence") or "") in open_lic), v["total"]]
             for k, v in quiet.items() if v.get("total")}
    (out / "quiet_flags.json").write_text(json.dumps({"snapshot": run_id, "species": flags}, separators=(",", ":")))
    (out / "quiet.json").write_text(json.dumps({"snapshot": run_id, "checked": len(quiet), "of": len(species),
                                                "complete": complete, "species": quiet},
                                               separators=(",", ":"), ensure_ascii=False))
    info = {"month": month, "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "backlog": f"layers/inat/{month}/backlog.json" if bl else None,
            "quiet": f"layers/inat/{month}/quiet.json", "quiet_flags": f"layers/inat/{month}/quiet_flags.json",
            "quiet_complete": complete, "quiet_checked": len(quiet), "quiet_of": len(species), "snapshot": run_id,
            "requests": client.used}
    if s3:
        for f in out.iterdir():
            r2.sync_file(s3, f, f"layers/inat/{month}/{f.name}", immutable=False)
        r2.put_json(s3, info, "layers/inat/latest.json")
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
