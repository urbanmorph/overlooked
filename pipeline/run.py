"""Monthly run: request the GBIF downloads, then build and publish when they are ready.

State for each run is kept in runs/<run id>.json and committed by the workflows, so a later job
can resume from the download keys.

Usage:
    python -m pipeline.run request [--state Kerala]
    python -m pipeline.run build   [--run-id 2026-11] [--publish]

A run limited to one state (a test run) gets the id <month>-<state> and is never published.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from concurrent.futures import ThreadPoolExecutor

from pipeline import boundaries as boundary_map
import hashlib

from pipeline import changes, checks, districts, gbif, health, ledger, names, site_data, unresolved

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
SNAPSHOTS = ROOT / "data" / "snapshots"
SITE_DATA = ROOT / "site" / "data"

# Query A (ledger), C (species history and names) and U (records not named to species, module 5).
# B and D were dropped: effort comes from the ledger itself, and names come with query C.
QUERIES = ["ledger_cube", "species_history", "unresolved_cube"]
DONE = "SUCCEEDED"
FAILED = ("FAILED", "KILLED", "CANCELLED", "FILE_ERASED")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_run_id(state=None):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return f"{month}-{state.lower().replace(' ', '-')}" if state else month


def load(run_id):
    path = RUNS / f"{run_id}.json"
    return json.loads(path.read_text()) if path.exists() else None


def save(state):
    RUNS.mkdir(exist_ok=True)
    (RUNS / f"{state['run_id']}.json").write_text(json.dumps(state, indent=1) + "\n")


def code_commit():
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return None


def submit_next(http, state):
    """GBIF lets one account run very few downloads at once, so queries go one after another.
    Submit the next query that has no key yet, if nothing is running. Returns True if one was submitted."""
    running = [d for d in state["downloads"].values() if d.get("key") and d["status"] not in (DONE, *FAILED)]
    if running:
        return False
    for name, d in state["downloads"].items():
        if not d.get("key"):
            key = gbif.submit(http, gbif.build_sql(name, state["region"]))
            if not key:
                print(f"{name}: GBIF is busy for this account (429); will try at the next check")
                return False
            d.update(key=key, status="PREPARING", requested=now())
            print(f"{name}: requested {key}")
            return True
    return False


def check_sources(state):
    """Check every source; stop on a critical failure. The report is kept in the run state."""
    report = health.check_all()
    state.setdefault("health", []).append(report)
    state["health"] = state["health"][-5:]
    for name in report["warnings"]:
        print(f"warning: {name} did not answer correctly; it keeps last month's data")
    if report["critical_failures"]:
        state["status_note"] = f"stopped: {report['critical_failures']} not working"
        save(state)
        sys.exit(f"run {state['run_id']}: critical sources not working: {report['critical_failures']}")
    return report


def previous_published():
    runs = sorted((json.loads(p.read_text()) for p in RUNS.glob("*.json")), key=lambda r: r.get("requested", ""))
    pubs = [r for r in runs if r.get("status") == "published" and not r.get("region")]
    return pubs[-1] if pubs else None


def gbif_unchanged_since(http, when):
    """True if GBIF reports no India record added, changed or re-processed since `when`."""
    r = http.get("https://api.gbif.org/v1/occurrence/search", timeout=60, params={
        "country": "IN", "hasCoordinate": "true", "limit": 0, "lastInterpreted": f"{when[:10]},*"})
    r.raise_for_status()
    return r.json()["count"] == 0


def request(args):
    run_id = args.run_id or default_run_id(args.state)
    if load(run_id):
        print(f"run {run_id} already requested; nothing to do")
        return
    state = {"run_id": run_id, "region": args.state, "status": "requested", "requested": now(),
             "downloads": {name: {"status": "WAITING"} for name in QUERIES}}
    check_sources(state)
    http = gbif.session()
    prev = None if args.state else previous_published()
    if prev and gbif_unchanged_since(http, prev["requested"]):
        state.update(status="unchanged", note=f"GBIF reports no change since run {prev['run_id']}; nothing to download")
        save(state)
        print(state["note"])
        return
    submit_next(http, state)
    save(state)


def previous_snapshot(run_id):
    """Download the previous published snapshot's ledger, species and summary from R2, if any."""
    if not os.environ.get("R2_ENDPOINT"):
        return None
    from pipeline import r2
    s3 = r2.client()
    latest = r2.get_json(s3, "latest.json")
    if not latest or latest["run_id"] == run_id:
        return None
    folder = ROOT / "data" / "previous" / latest["run_id"]
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("ledger.parquet", "species.parquet"):
        if not (folder / name).exists():
            s3.download_file(r2.bucket(), latest["base"] + name, str(folder / name))
    return {"ledger": folder / "ledger.parquet", "species": folder / "species.parquet",
            "summary": r2.get_json(s3, latest["summary"])}


def inputs_fingerprint(state, boundaries):
    """What a snapshot is built from. Same inputs give the same snapshot, so a rerun is a no-op."""
    keys = {n: d["key"] for n, d in sorted(state["downloads"].items())}
    blob = json.dumps({"downloads": keys, "boundaries": boundaries["sha256"]}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def build(args):
    run_id = args.run_id or default_run_id()
    state = load(run_id)
    if not state:
        print(f"no run {run_id}; nothing to do")
        return
    if state["status"] in ("published", "failed", "unchanged") or (state["status"] == "built" and not args.publish):
        print(f"run {run_id} is {state['status']}; nothing to do")
        return
    check_sources(state)
    # A run started before a query was added picks it up here, after the others.
    for name in QUERIES:
        state["downloads"].setdefault(name, {"status": "WAITING"})

    http = gbif.session()
    metas = {}
    for name, d in state["downloads"].items():
        if not d.get("key"):
            continue
        meta = http.get(f"{gbif.API}/{d['key']}", timeout=60).json()
        d["status"] = meta["status"]
        metas[name] = meta
        time.sleep(1.0)
    if not any(d["status"] in FAILED for d in state["downloads"].values()) and submit_next(http, state):
        save(state)
        print(f"run {run_id}: submitted the next download; waiting for GBIF")
        return
    if any(d["status"] in FAILED for d in state["downloads"].values()):
        state["status"] = "failed"
        save(state)
        sys.exit(f"run {run_id}: a download ended badly: {state['downloads']}")
    if not all(d["status"] == DONE for d in state["downloads"].values()):
        save(state)
        print(f"run {run_id}: waiting for GBIF: { {n: d['status'] for n, d in state['downloads'].items()} }")
        return

    for name, meta in metas.items():
        z = gbif.RAW / f"{meta['key']}.zip"
        if not (z.exists() and (not meta.get("size") or z.stat().st_size == meta["size"])):
            gbif.fetch(http, meta)
        state["downloads"][name]["doi"] = meta["doi"]

    out = SNAPSHOTS / run_id
    ua = http.headers["User-Agent"]
    boundaries = districts.ensure(ua)
    fingerprint = inputs_fingerprint(state, boundaries)
    publish = args.publish and not state["region"]
    built = out / "manifest.json"
    if built.exists() and json.loads(built.read_text()).get("inputs") == fingerprint:
        print(f"run {run_id}: already built from the same inputs ({fingerprint}); not rebuilding")
        manifest = json.loads(built.read_text())
        summary = json.loads((out / "summary.json").read_text())
        bpath = manifest["district_map"]
        bfile = SNAPSHOTS / "_shared" / bpath
        return finish(args, state, out, manifest, summary, bpath, bfile, publish)
    con = duckdb.connect()
    # Names first: duplicate keys are merged before the ledger is built.
    names.load_history(con, ledger.unpack(state["downloads"]["species_history"]["key"]))
    print(f"merged duplicate keys for {names.merge_duplicates(con)} names")
    ledger.load_cube(con, ledger.unpack(state["downloads"]["ledger_cube"]["key"]))
    stats = ledger.build(con, out, f"GBIF download {state['downloads']['ledger_cube']['key']}", districts.PATH)

    con.sql(f"COPY species TO '{out / 'species.parquet'}' (FORMAT parquet, COMPRESSION zstd)")
    con.sql(f"COPY species_decade TO '{out / 'species_decade.parquet'}' (FORMAT parquet, COMPRESSION zstd)")
    unresolved_records = None
    if "unresolved_cube" in state["downloads"]:
        unresolved_records = unresolved.build(con, ledger.unpack(state["downloads"]["unresolved_cube"]["key"]),
                                              str(districts.PATH))
        con.sql(f"COPY unresolved TO '{out / 'unresolved.parquet'}' (FORMAT parquet, COMPRESSION zstd)")

    # The district map depends only on the boundary file, so it is stored once per boundary version.
    bpath = f"boundaries/lgd-{boundaries['sha256'][:12]}/districts_map.json"
    bfile = SNAPSHOTS / "_shared" / bpath
    if not bfile.exists():
        bfile.parent.mkdir(parents=True, exist_ok=True)
        bfile.write_text(json.dumps(boundary_map.build(districts.PATH), separators=(",", ":")))

    meta = {
        "run_id": run_id,
        "built": now(),
        "taxon_ids": "col",
        "dois": [metas[n]["doi"] for n in QUERIES if n in metas],
        "gbif_snapshot": metas["ledger_cube"].get("created", "")[:10],
        "region": state["region"],
    }
    summary = site_data.build(con, out, meta)
    if unresolved_records is not None:
        site_data.unresolved_json(con, out)

    site_data.species_shards(con, out)

    # Module 2: compare with the previous published snapshot, if there is one.
    previous = previous_snapshot(run_id)
    counts = None
    if previous:
        counts = changes.build(con, previous["ledger"], previous["species"],
                               prev_year=int(previous["summary"]["built"][:4]), this_year=int(summary["built"][:4]))
        con.sql(f"COPY changes TO '{out / 'changes.parquet'}' (FORMAT parquet, COMPRESSION zstd)")
    site_data.changes_json(con, out, counts, previous["summary"] if previous else None, summary)
    summary["changes"] = counts
    summary["previous_run"] = previous["summary"]["run_id"] if previous else None
    summary.update({"districts": stats["districts"], "ledger_rows": stats["ledger_rows"],
                    "unresolved_records": unresolved_records})
    (out / "summary.json").write_text(json.dumps(summary, separators=(",", ":")))
    manifest = {
        "run_id": run_id,
        "region": state["region"],
        "built": summary["built"],
        "code_commit": code_commit(),
        "downloads": [{"query": n, "key": metas[n]["key"], "doi": metas[n]["doi"], "created": metas[n].get("created"),
                       "records": metas[n].get("totalRecords")} for n in metas],
        "boundaries": boundaries,
        "placement": "coordinates rounded to 3 decimals; points within 5 km of a district take the nearest one",
        "stats": stats,
        "files": {p.name: p.stat().st_size for p in sorted(out.iterdir()) if p.suffix in (".parquet",)},
        "district_map": bpath,
        "inputs": fingerprint,
        "health": state.get("health", [{}])[-1],
        "licence": "Data and text: CC BY 4.0, Sathya Sankaran. GBIF records keep their dataset licences; cite the DOIs.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return finish(args, state, out, manifest, summary, bpath, bfile, publish)


def finish(args, state, out, manifest, summary, bpath, bfile, publish):
    run_id = state["run_id"]
    previous = None
    s3 = None
    if publish:
        from pipeline import r2
        s3 = r2.client()
        latest = r2.get_json(s3, "latest.json")
        if latest and latest["run_id"] != run_id:
            previous = r2.get_json(s3, f"snapshots/{latest['run_id']}/summary.json")
    problems = checks.run(summary, manifest, previous)
    if problems:
        state["status"] = "failed"
        state["problems"] = problems
        save(state)
        sys.exit(f"run {run_id}: checks failed: {problems}")

    if publish:
        prefix = f"snapshots/{run_id}"
        remote = r2.get_json(s3, f"{prefix}/manifest.json")
        if remote and remote.get("inputs") != manifest["inputs"]:
            sys.exit(f"{prefix} already exists in R2 from other inputs; snapshots are never overwritten")
        if not remote:
            r2.sync_file(s3, bfile, bpath)
            files = [p for p in sorted(out.rglob("*")) if p.suffix in (".parquet", ".json") and p.name != "manifest.json"]
            with ThreadPoolExecutor(8) as pool:
                sent = sum(pool.map(lambda p: r2.sync_file(s3, p, f"{prefix}/{p.relative_to(out).as_posix()}"), files))
            print(f"uploaded {sent} of {len(files)} files (the rest were already in R2)")
            # The manifest goes last: its presence marks a complete snapshot.
            r2.sync_file(s3, out / "manifest.json", f"{prefix}/manifest.json")
        built_at = (r2.get_json(s3, f"{prefix}/summary.json") or summary)["built"] if remote else summary["built"]
        latest = {"run_id": run_id, "built": built_at, "base": f"{prefix}/",
                  "manifest": f"{prefix}/manifest.json", "summary": f"{prefix}/summary.json", "boundaries": bpath}
        if r2.get_json(s3, "latest.json") != latest:
            r2.put_json(s3, latest, "latest.json")
        SITE_DATA.mkdir(parents=True, exist_ok=True)
        (SITE_DATA / "latest.json").write_text(json.dumps(latest, indent=1) + "\n")
        state["status"] = "published"
    else:
        state["status"] = "built"
    state["finished"] = now()
    state["summary"] = {k: summary[k] for k in ("species", "records", "districts", "ledger_rows", "quiet_species")}
    save(state)
    print(json.dumps(state["summary"], indent=1))


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("request")
    r.add_argument("--state", help="GADM state name, for a test run")
    r.add_argument("--run-id")
    b = sub.add_parser("build")
    b.add_argument("--run-id")
    b.add_argument("--publish", action="store_true")
    a = p.parse_args()
    {"request": request, "build": build}[a.cmd](a)


if __name__ == "__main__":
    main()
