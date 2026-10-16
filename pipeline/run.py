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

from pipeline import checks, districts, gbif, ledger

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
SNAPSHOTS = ROOT / "data" / "snapshots"
SITE_DATA = ROOT / "site" / "data"

# Queries B to D join this list as they are written (docs/plan.md, section 3).
QUERIES = ["ledger_cube"]
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


def request(args):
    run_id = args.run_id or default_run_id(args.state)
    if load(run_id):
        print(f"run {run_id} already requested; nothing to do")
        return
    http = gbif.session()
    state = {"run_id": run_id, "region": args.state, "status": "requested", "requested": now(), "downloads": {}}
    for name in QUERIES:
        sql = gbif.build_sql(name, args.state)
        key = gbif.submit(http, sql)
        state["downloads"][name] = {"key": key, "status": "PREPARING"}
        print(f"{name}: requested {key}")
        time.sleep(1.5)
    save(state)


def build(args):
    run_id = args.run_id or default_run_id()
    state = load(run_id)
    if not state:
        print(f"no run {run_id}; nothing to do")
        return
    if state["status"] in ("published", "built", "failed"):
        print(f"run {run_id} is {state['status']}; nothing to do")
        return

    http = gbif.session()
    metas = {}
    for name, d in state["downloads"].items():
        meta = http.get(f"{gbif.API}/{d['key']}", timeout=60).json()
        d["status"] = meta["status"]
        metas[name] = meta
        time.sleep(1.0)
    if any(d["status"] in FAILED for d in state["downloads"].values()):
        state["status"] = "failed"
        save(state)
        sys.exit(f"run {run_id}: a download ended badly: {state['downloads']}")
    if not all(d["status"] == DONE for d in state["downloads"].values()):
        save(state)
        print(f"run {run_id}: waiting for GBIF: { {n: d['status'] for n, d in state['downloads'].items()} }")
        return

    for name, meta in metas.items():
        if not (gbif.RAW / f"{meta['key']}.zip").exists():
            gbif.fetch(http, meta)
        state["downloads"][name]["doi"] = meta["doi"]

    out = SNAPSHOTS / run_id
    ua = http.headers["User-Agent"]
    boundaries = districts.ensure(ua)
    con = duckdb.connect()
    ledger.load_cube(con, ledger.unpack(state["downloads"]["ledger_cube"]["key"]))
    stats = ledger.build(con, out, f"GBIF download {state['downloads']['ledger_cube']['key']}", districts.PATH)

    summary = {
        "run_id": run_id,
        "built": now(),
        "species": stats["species"],
        "records": stats["records"],
        "districts": stats["districts"],
        "ledger_rows": stats["ledger_rows"],
        "species_quiet_since_1980": con.sql("""
            SELECT count(*) FROM (SELECT species_key FROM ledger GROUP BY species_key HAVING max(last_year) < 1980)
        """).fetchone()[0],
    }
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
        "licence": "Data and text: CC BY 4.0, Sathya Sankaran. GBIF records keep their dataset licences; cite the DOIs.",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))

    publish = args.publish and not state["region"]
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
        if r2.exists(s3, f"{prefix}/manifest.json"):
            sys.exit(f"{prefix} already exists in R2; snapshots are never overwritten")
        for p in sorted(out.iterdir()):
            if p.suffix in (".parquet", ".json"):
                r2.put_file(s3, p, f"{prefix}/{p.name}")
        latest = {"run_id": run_id, "built": summary["built"], "manifest": f"{prefix}/manifest.json",
                  "summary": f"{prefix}/summary.json"}
        r2.put_json(s3, latest, "latest.json")
        SITE_DATA.mkdir(parents=True, exist_ok=True)
        (SITE_DATA / "latest.json").write_text(json.dumps(latest, indent=1) + "\n")
        state["status"] = "published"
    else:
        state["status"] = "built"
    state["finished"] = now()
    state["summary"] = summary
    save(state)
    print(json.dumps(summary, indent=1))


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
