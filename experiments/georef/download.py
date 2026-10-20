"""One GBIF SQL download for the georeferencing test (georef_sample.sql): request, wait, fetch.

The download key is kept in data/georef/download.json as soon as GBIF gives it, so a stopped run waits for the
same download instead of asking again. The zip goes to data/raw/ (pipeline.gbif.ensure: fetched once, checked by
size). A second run after the zip is complete does nothing. Local cache only: this experiment uploads nothing.

Usage: .venv/bin/python experiments/georef/download.py [--validate]
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pipeline import gbif, util

STATE = ROOT / "data" / "georef" / "download.json"
# build_sql reads pipeline/queries/<name>.sql; this relative name points it at the experiment's query.
QUERY = "../../experiments/georef/georef_sample"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--validate", action="store_true")
    a = p.parse_args()
    http = gbif.session()  # loads .env
    sql = gbif.build_sql(QUERY)
    if a.validate:
        code, text = gbif.validate(http, sql)
        util.log(code, text[:300])
        return
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if state.get("status") in ("FAILED", "KILLED", "CANCELLED"):
        state = {}
    if not state.get("key"):
        key = gbif.submit(http, sql)
        if not key:
            sys.exit("GBIF is busy for this account (429); run again later")
        state = {"key": key, "status": "PREPARING", "requested": util.now()}
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=1))
        util.log(f"requested {key}")
    meta = gbif.wait(http, state["key"]) if state.get("status") != "SUCCEEDED" else \
        http.get(f"{gbif.API}/{state['key']}", timeout=60).json()
    state.update(status=meta["status"], doi=meta.get("doi"), records=meta.get("totalRecords"))
    STATE.write_text(json.dumps(state, indent=1))
    # A stream can end early without an error (seen twice here): check the size and the zip, and try again.
    for attempt in range(1, 4):
        z = gbif.ensure(http, meta)
        if complete(z, meta.get("size")):
            util.log(f"{z} ready ({meta.get('totalRecords')} records, doi:{meta.get('doi')})")
            return
        util.log(f"attempt {attempt}: {z.stat().st_size} of {meta.get('size')} bytes; fetching again")
        z.unlink()
    sys.exit("the zip stayed incomplete after 3 attempts")


def complete(z, size):
    if size and z.stat().st_size != size:
        return False
    try:
        with zipfile.ZipFile(z) as f:
            return f.testzip() is None
    except zipfile.BadZipFile:
        return False


if __name__ == "__main__":
    main()
