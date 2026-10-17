"""GBIF SQL downloads: validate, request, wait and fetch.

Ported from fnf scripts/01b_gbif_sql_attention.py. SQL downloads are an experimental GBIF
feature; a 403 means the account needs it enabled (helpdesk@gbif.org).

Usage:
    .venv/bin/python -m pipeline.gbif validate ledger_cube [--state Kerala]
    .venv/bin/python -m pipeline.gbif request  ledger_cube [--state Kerala]
    .venv/bin/python -m pipeline.gbif fetch    <download key>
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
QUERIES = ROOT / "pipeline" / "queries"
EXCLUDED = ROOT / "pipeline" / "ref" / "excluded_datasets.csv"
RAW = ROOT / "data" / "raw"
API = "https://api.gbif.org/v1/occurrence/download"


def session():
    load_dotenv(ROOT / ".env", override=True)
    http = requests.Session()
    # GBIF asks for a User-Agent with a URL or an email address.
    http.headers["User-Agent"] = f"overlooked-india (+https://github.com/urbanmorph/overlooked; {os.environ['GBIF_EMAIL']})"
    http.auth = (os.environ["GBIF_USER"], os.environ["GBIF_PASSWORD"])
    return http


def build_sql(name, state=None):
    excluded = ", ".join(f"'{r['datasetKey']}'" for r in csv.DictReader(EXCLUDED.open()))
    # GADM state name is only for test runs. The real runs place cells in LGD districts later.
    region = f"AND level1name = '{state}'" if state else ""
    # Records with no coordinates have no GADM name; a test run selects them by the state text.
    text_region = f"AND stateprovince = '{state}'" if state else ""
    text = (QUERIES / f"{name}.sql").read_text()
    body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("--"))
    return " ".join(body.format(excluded=excluded, region_filter=region, stateprovince_filter=text_region).split())


def request_body(sql):
    return {"sendNotification": False, "format": "SQL_TSV_ZIP", "sql": sql}


def validate(http, sql):
    r = http.post(f"{API}/request/validate", json=request_body(sql), timeout=60)
    return r.status_code, r.text


def submit(http, sql):
    """Submit a download. Returns its key, or None if GBIF says too many downloads are running (429)."""
    r = http.post(f"{API}/request", json=request_body(sql), timeout=60)
    if r.status_code == 429:
        return None
    if not r.ok:
        sys.exit(f"HTTP {r.status_code}: {r.text[:500]}")
    return r.text.strip()


def wait(http, key, every=60):
    while True:
        meta = http.get(f"{API}/{key}", timeout=60).json()
        print(f"{time.strftime('%H:%M:%S')} {meta['status']} rows={meta.get('totalRecords')}", flush=True)
        if meta["status"] == "SUCCEEDED":
            return meta
        if meta["status"] in ("FAILED", "KILLED", "CANCELLED"):
            sys.exit(f"download {key} ended with {meta['status']}")
        time.sleep(every)


def fetch(http, meta):
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / f"{meta['key']}.zip"
    part = dest.with_suffix(".zip.part")  # renamed only when complete, so a cut download is never used
    with http.get(meta["downloadLink"], stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    part.replace(dest)
    (RAW / f"{meta['key']}.json").write_text(json.dumps(
        {k: meta.get(k) for k in ("key", "doi", "created", "modified", "totalRecords", "size")}, indent=1))
    print(f"saved {dest} ({dest.stat().st_size / 1e6:.1f} MB), doi:{meta['doi']}")
    return dest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["validate", "request", "fetch"])
    p.add_argument("target", help="query name, or download key for fetch")
    p.add_argument("--state", help="GADM state name, for test runs")
    a = p.parse_args()
    http = session()
    if a.action == "fetch":
        fetch(http, wait(http, a.target))
        return
    sql = build_sql(a.target, a.state)
    if a.action == "validate":
        code, text = validate(http, sql)
        print(code, text[:1500])
        return
    key = submit(http, sql)
    if not key:
        sys.exit("GBIF: too many downloads running for this account (429); try again later")
    print(f"requested {key}")
    fetch(http, wait(http, key))


if __name__ == "__main__":
    main()
