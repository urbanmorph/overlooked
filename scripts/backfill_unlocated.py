"""Add query L (records with no coordinates) to a snapshot published before the query existed.

Requests the GBIF download, waits for it, and builds unlocated.json and unlocated.parquet from it and from
the snapshot's own published Parquet files. Only new files are written; a published file is never changed.
The download's DOI goes into unlocated.json, as the manifest is not changed.

The download key is kept in data/backfill/<run_id>/ and in R2 cache/backfill/<run_id>/, so a stopped run
continues with the same download. A second run after publishing does nothing.

Usage: .venv/bin/python scripts/backfill_unlocated.py <run_id> [--wait] [--publish]
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import gbif, ledger, names, r2, site_data, unlocated  # noqa: E402

QUERY = "unlocated_cube"
FILES = ("unlocated.json", "unlocated.parquet")


def next_step(state, published):
    if published:
        return "done"
    if not state.get("key") or state.get("status") in ("FAILED", "KILLED", "CANCELLED"):
        return "submit"
    return "build" if state.get("status") == "SUCCEEDED" else "wait"


def ensure_zip(http, key):
    """The download's zip in data/raw, fetched once. Returns the GBIF metadata."""
    meta = http.get(f"{gbif.API}/{key}", timeout=60).json()
    z = gbif.RAW / f"{key}.zip"
    if not (z.exists() and (not meta.get("size") or z.stat().st_size == meta["size"])):
        gbif.fetch(http, meta)
    return meta


def build(http, s3, run_id, key, work: Path):
    prefix = f"snapshots/{run_id}/"
    con = duckdb.connect()
    for t in ("ledger", "species"):
        f = work / f"{t}.parquet"
        if not f.exists():
            s3.download_file(r2.bucket(), prefix + f"{t}.parquet", str(f))
        con.sql(f"CREATE TABLE {t} AS SELECT * FROM '{f}'")
    # Merge duplicate keys as the run did, from its own names download.
    run = json.loads((ROOT / "runs" / f"{run_id}.json").read_text())
    history = run["downloads"]["species_history"]["key"]
    ensure_zip(http, history)
    names.load_history(con, ledger.unpack(history))
    print(f"merged duplicate keys for {names.merge_duplicates(con)} names", flush=True)
    meta = ensure_zip(http, key)
    n = unlocated.build(con, ledger.unpack(key))
    print(f"{n} records that cannot go in a district", flush=True)
    out = work / "out"
    out.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY unlocated TO '{out / 'unlocated.parquet'}' (FORMAT parquet, COMPRESSION zstd)")
    u = site_data.unlocated_json(con, out, titles=lambda keys: unlocated.dataset_titles(http, keys, s3=s3))
    u["download"] = {"key": key, "doi": meta["doi"], "created": meta.get("created")}
    site_data.dump(u, out / "unlocated.json")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run_id")
    p.add_argument("--wait", action="store_true", help="wait for GBIF instead of stopping")
    p.add_argument("--publish", action="store_true")
    a = p.parse_args()
    http = gbif.session()  # loads .env
    s3 = r2.client()
    prefix, cache_key = f"snapshots/{a.run_id}/", f"cache/backfill/{a.run_id}/unlocated_run.json"
    work = ROOT / "data" / "backfill" / a.run_id
    work.mkdir(parents=True, exist_ok=True)
    local = work / "unlocated_run.json"
    state = json.loads(local.read_text()) if local.exists() else (r2.get_json(s3, cache_key) or {})

    def save():
        local.write_text(json.dumps(state, indent=1))
        r2.put_json(s3, state, cache_key)

    while True:
        step = next_step(state, all(r2.exists(s3, prefix + f) for f in FILES))
        if step == "done":
            print(f"{prefix} already has {', '.join(FILES)}; nothing to do", flush=True)
            return
        if step == "submit":
            key = gbif.submit(http, gbif.build_sql(QUERY))
            if not key:
                sys.exit("GBIF is busy for this account (429); run again later")
            state.update(key=key, status="PREPARING")
            save()
            print(f"{QUERY}: requested {key}", flush=True)
            continue
        if step == "wait":
            if not a.wait:
                meta = http.get(f"{gbif.API}/{state['key']}", timeout=60).json()
                state["status"] = meta["status"]
                save()
                print(f"{state['key']}: {meta['status']}; run again (or with --wait)", flush=True)
                if meta["status"] != "SUCCEEDED":
                    return
                continue
            state["status"] = gbif.wait(http, state["key"])["status"]
            save()
            continue
        out = build(http, s3, a.run_id, state["key"], work)
        if not a.publish:
            print(f"built {out}; not published", flush=True)
            return
        for f in FILES:
            if not r2.exists(s3, prefix + f):  # never change a published file
                r2.sync_file(s3, out / f, prefix + f)
                print(f"uploaded {prefix + f}", flush=True)


if __name__ == "__main__":
    main()
