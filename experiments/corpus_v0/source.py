"""Step 1: one GBIF download (Darwin Core Archive, so multimedia is included) of the iNaturalist Research-grade
Observations dataset, country IN, and two tables made from it.

- The download key is stored in data/corpus_v0/download.json as soon as GBIF gives it, so the request is
  never sent twice; a rerun waits for (or reuses) that download. The zip is kept (data/corpus_v0/<key>.zip)
  and fetched through a .part file, so a cut transfer is never used.
- records.parquet: one row per occurrence (gbifID, iNaturalist observation id, names and GBIF taxon keys,
  observer, identifiedBy, date, coordinates, state).
- photos.parquet: one row per still image (gbifID, position, URL, open-data URL, licence, rights holder).
Both are written once; a rerun with them present does nothing.

GBIF credentials come from .env through pipeline.gbif.session() and are never printed.
Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/source.py
"""

import time
import zipfile

import pandas as pd
from lib import DATA, atomic_parquet, atomic_write_json, log, read_json
from logic import open_data_url

DATASET = "50c9509d-22c7-4a22-a47d-8c48425ef4a7"  # iNaturalist Research-grade Observations
KEY_FILE = DATA / "download.json"
API = "https://api.gbif.org/v1/occurrence/download"  # as pipeline.gbif.API
REC_COLS = [
    "gbifID",
    "catalogNumber",
    "occurrenceID",
    "recordedBy",
    "identifiedBy",
    "eventDate",
    "decimalLatitude",
    "decimalLongitude",
    "stateProvince",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
    "taxonRank",
    "scientificName",
    "verbatimScientificName",
    "acceptedScientificName",
    "taxonKey",
    "speciesKey",
    "acceptedTaxonKey",
]
MM_COLS = ["gbifID", "type", "format", "identifier", "license", "rightsHolder"]


def predicate():
    return {
        "creator": None,  # filled from the session's user by GBIF
        "sendNotification": False,
        "format": "DWCA",
        "predicate": {
            "type": "and",
            "predicates": [
                {"type": "equals", "key": "DATASET_KEY", "value": DATASET},
                {"type": "equals", "key": "COUNTRY", "value": "IN"},
            ],
        },
    }


def request_key(http):
    saved = read_json(KEY_FILE)
    if saved and saved.get("key"):
        log(f"download key {saved['key']} already requested; not requesting again")
        return saved["key"]
    body = predicate()
    body["creator"] = http.auth[0]
    r = http.post(f"{API}/request", json=body, timeout=60)
    if not r.ok:
        raise SystemExit(f"GBIF request failed: HTTP {r.status_code} {r.text[:300]}")
    key = r.text.strip()
    atomic_write_json(
        KEY_FILE,
        {"key": key, "requested": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "predicate": body["predicate"]},
    )
    log(f"requested GBIF download {key}")
    return key


def wait(http, key, every=120):
    while True:
        meta = http.get(f"{API}/{key}", timeout=60).json()
        log(f"GBIF {key}: {meta['status']} records={meta.get('totalRecords')} size={meta.get('size')}")
        if meta["status"] == "SUCCEEDED":
            return meta
        if meta["status"] in ("FAILED", "KILLED", "CANCELLED", "FILE_ERASED"):
            raise SystemExit(f"download {key} ended with {meta['status']}")
        time.sleep(every)


def ensure_zip(http, meta):
    z = DATA / f"{meta['key']}.zip"
    if not (z.exists() and z.stat().st_size == meta.get("size")):
        from pipeline import util

        util.stream(http, meta["downloadLink"], z, progress_mb=200)
    saved = read_json(KEY_FILE)
    saved.update({k: meta.get(k) for k in ("doi", "created", "totalRecords", "size")})
    atomic_write_json(KEY_FILE, saved)
    return z


def read_member(z, name, cols, chunks=500_000):
    """Read selected columns of a tab-separated member in chunks (the occurrence file is many GB)."""
    with zipfile.ZipFile(z) as zf, zf.open(name) as f:
        header = f.readline().decode().rstrip("\n").split("\t")
    use = [c for c in cols if c in header]
    missing = sorted(set(cols) - set(use))
    if missing:
        log(f"  {name}: columns not in the archive: {missing}")
    parts = []
    with zipfile.ZipFile(z) as zf, zf.open(name) as f:
        reader = pd.read_csv(
            f, sep="\t", usecols=use, dtype=str, quoting=3, chunksize=chunks, on_bad_lines="warn", keep_default_na=False
        )
        for i, part in enumerate(reader, 1):
            parts.append(part)
            log(f"  {name}: {i * chunks:,} rows read")
    return pd.concat(parts, ignore_index=True)


def build_tables(z):
    rec_path, ph_path = DATA / "records.parquet", DATA / "photos.parquet"
    if rec_path.exists() and ph_path.exists():
        log("records.parquet and photos.parquet exist; nothing to do")
        return
    rec = read_member(z, "occurrence.txt", REC_COLS)
    rec["obs_id"] = pd.to_numeric(rec.catalogNumber, errors="coerce").astype("Int64")
    for c in ("decimalLatitude", "decimalLongitude"):
        rec[c] = pd.to_numeric(rec[c], errors="coerce")
    atomic_parquet(rec, rec_path)
    log(f"records.parquet: {len(rec):,} rows")
    mm = read_member(z, "multimedia.txt", MM_COLS)
    mm = mm[mm.type == "StillImage"].copy()
    mm["position"] = mm.groupby("gbifID").cumcount()
    mm["open_url"] = mm.identifier.map(open_data_url)
    atomic_parquet(mm, ph_path)
    log(f"photos.parquet: {len(mm):,} still images; {mm.open_url.notna().mean():.1%} map to the open-data bucket")


def main():
    from pipeline import gbif

    http = gbif.session()
    key = request_key(http)
    meta = wait(http, key)
    z = ensure_zip(http, meta)
    build_tables(z)


if __name__ == "__main__":
    main()
