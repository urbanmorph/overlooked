"""Step 6a: download "medium" photos from the iNaturalist open-data bucket (inaturalist-open-data on AWS) for
the corpus and the T1 test set. Only URLs in that bucket are fetched; at most 8 at a time.

Each photo goes to data/corpus_v0/photos/<photo_id>.<ext> through a .part file, so a cut file is never
used; a file already there is skipped, so a rerun does no new work. Failures (404, not an image) are
kept in photos_failed.json, saved every few minutes and on exit, and not retried unless --retry.

Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/photos.py [--retry]
"""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from lib import DATA, PHOTOS, Checkpoint, atomic_write_json, log, read_json, ua

FAILED = DATA / "photos_failed.json"
WORKERS = 8
BUCKET = "https://inaturalist-open-data.s3.amazonaws.com/"


def photo_path(photo_id, url):
    return PHOTOS / f"{photo_id}.{url.rsplit('.', 1)[-1].lower()}"


def wanted():
    """All photos the corpus and T1 need: photo_id, url (medium, open-data bucket)."""
    frames = [pd.read_parquet(DATA / f, columns=["photo_id", "url"]) for f in ("corpus.parquet", "t1.parquet")]
    w = pd.concat(frames).drop_duplicates("photo_id")
    return w[w.url.str.startswith(BUCKET)]


def get(http, photo_id, url):
    dest = photo_path(photo_id, url)
    part = dest.with_name(dest.name + ".part")
    try:
        r = http.get(url, timeout=60)
        if r.status_code != 200 or not r.headers.get("Content-Type", "").startswith("image/"):
            return photo_id, f"HTTP {r.status_code} {r.headers.get('Content-Type', '')}"
        part.write_bytes(r.content)
        part.replace(dest)
        return photo_id, None
    except requests.RequestException as e:
        return photo_id, type(e).__name__


def main():
    retry = "--retry" in sys.argv
    w = wanted()
    failed = read_json(FAILED, {})
    have = {p.stem for p in PHOTOS.iterdir() if not p.name.endswith(".part")}
    todo = [
        (int(r.photo_id), r.url)
        for r in w.itertuples()
        if str(r.photo_id) not in have and (retry or str(r.photo_id) not in failed)
    ]
    log(f"photos: {len(w):,} wanted, {len(have):,} on disk, {len(failed):,} failed before, {len(todo):,} to fetch")
    if not todo:
        return
    cp = Checkpoint(lambda: atomic_write_json(FAILED, failed))
    done = 0
    try:
        with requests.Session() as http, ThreadPoolExecutor(WORKERS) as pool:
            http.headers["User-Agent"] = ua()
            adapter = requests.adapters.HTTPAdapter(pool_connections=WORKERS, pool_maxsize=WORKERS)
            http.mount("https://", adapter)
            futures = [pool.submit(get, http, pid, url) for pid, url in todo]
            for f in as_completed(futures):
                pid, err = f.result()
                done += 1
                if err:
                    failed[str(pid)] = err
                else:
                    failed.pop(str(pid), None)
                if done % 5000 == 0:
                    log(f"  photos: {done:,}/{len(todo):,} ({len(failed):,} failed in all)")
                cp.tick()
    finally:
        cp.final()
        log(f"photos: {done:,} handled this run; {len(failed):,} failed in all")


if __name__ == "__main__":
    main()
