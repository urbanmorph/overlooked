"""Step 6b: BioCLIP 2.5 (ViT-H/14) image features for the corpus, T1 and the pilot's queue photos.

Shards: data/corpus_v0/emb/shard_<n>.npz (photo_id, feats L2-normalised float32, elapsed seconds), one per
SHARD photos, written atomically when full and on exit (also on Ctrl-C or error), so a stopped run loses at
most one partial shard's worth of time and never a finished one. Photos in any shard are skipped, so a
rerun does no new work. Photos that cannot be read are listed in emb/unreadable.json.

The model and preprocessing are the model check's (experiments/model_check/embed.py build()).
Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/embed_v0.py [corpus t1 queue qsample live]
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from lib import DATA, EMB, PHOTOS, atomic_savez, atomic_write_json, log, read_json

SHARD = 2000
BATCH = 16  # as the model check for bioclip-2.5
UNREADABLE = EMB / "unreadable.json"
PILOT_PHOTOS = Path("/Users/sathya/Projects/biodiversity/fnf/data/raw/inat_photos")  # read only


def local_paths():
    return {p.stem: p for p in PHOTOS.iterdir() if not p.name.endswith(".part")}


def manifest(sets):
    """photo_id -> image path for the requested sets."""
    paths = {}
    files = {"corpus": "corpus", "t1": "t1", "qsample": "queue_sample", "live": "live_sample"}
    if set(files) & set(sets):
        local = local_paths()
        for s, f in files.items():
            if s in sets and (DATA / f"{f}.parquet").exists():
                for pid in pd.read_parquet(DATA / f"{f}.parquet", columns=["photo_id"]).photo_id:
                    if str(pid) in local:
                        paths[int(pid)] = local[str(pid)]
    if "queue" in sets:
        q = pd.read_parquet(DATA / "queue.parquet")
        q = q[q.now_species.notna() | q.observer_species.notna()]  # only rows T2 or T3 can use
        for pid in q.photo_id:
            p = PILOT_PHOTOS / f"{int(pid)}.jpg"
            if p.exists():
                paths[int(pid)] = p
    return paths


def load_all():
    """All cached features: (photo_ids array, feats matrix)."""
    ids, feats = [], []
    for f in sorted(EMB.glob("shard_*.npz")):
        c = np.load(f)
        ids.append(c["photo_id"])
        feats.append(c["feats"])
    if not ids:
        return np.zeros(0, np.int64), np.zeros((0, 0), np.float32)
    return np.concatenate(ids), np.concatenate(feats)


def done_ids():
    out = set()
    for f in EMB.glob("shard_*.npz"):
        out.update(int(x) for x in np.load(f)["photo_id"])
    return out


def total_elapsed():
    return sum(float(np.load(f)["elapsed"]) for f in EMB.glob("shard_*.npz"))


def main():
    sets = sys.argv[1:] or ["corpus", "t1", "queue", "qsample", "live"]
    paths = manifest(sets)
    bad = read_json(UNREADABLE, {})
    have = done_ids()
    todo = [p for p in paths if p not in have and str(p) not in bad]
    log(f"embed: {len(paths):,} photos in {sets}, {len(have):,} embedded, {len(todo):,} to do")
    if not todo:
        return
    import torch
    from embed import build
    from PIL import Image

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    pre, fwd = build("bioclip-2.5", device)
    next_n = 1 + max((int(f.stem.split("_")[1]) for f in EMB.glob("shard_*.npz")), default=-1)

    def load(pid):
        try:
            return pre(Image.open(paths[pid]).convert("RGB"))
        except (OSError, ValueError, SyntaxError) as e:  # a broken or non-image file: note it, go on
            bad[str(pid)] = type(e).__name__
            return None

    buf_ids, buf_feats, elapsed, t_start, n_done = [], [], 0.0, time.time(), 0

    def flush():
        nonlocal buf_ids, buf_feats, elapsed, next_n
        if buf_ids:
            atomic_savez(
                EMB / f"shard_{next_n:05d}.npz",
                photo_id=np.asarray(buf_ids, np.int64),
                feats=np.concatenate(buf_feats).astype(np.float32),
                elapsed=np.float64(elapsed),
            )
            next_n += 1
        atomic_write_json(UNREADABLE, bad)
        buf_ids, buf_feats, elapsed = [], [], 0.0

    try:
        with ThreadPoolExecutor(8) as pool, torch.no_grad():
            for i in range(0, len(todo), BATCH):
                chunk = todo[i : i + BATCH]
                t0 = time.time()
                imgs = list(pool.map(load, chunk))
                keep = [(p, x) for p, x in zip(chunk, imgs) if x is not None]
                if keep:
                    f, _ = fwd(torch.stack([x for _, x in keep]).to(device))
                    buf_feats.append(f.float().cpu().numpy())
                    buf_ids.extend(p for p, _ in keep)
                elapsed += time.time() - t0
                n_done += len(chunk)
                if len(buf_ids) >= SHARD:
                    flush()
                if (i // BATCH) % 250 == 0:
                    rate = 1000 * (time.time() - t_start) / max(n_done, 1)
                    eta_h = rate * (len(todo) - n_done) / 1000 / 3600
                    log(f"  embed: {n_done:,}/{len(todo):,}  {rate:.1f} s/1000  about {eta_h:.1f} h left")
    finally:
        flush()
        log(f"embed: stopped after {n_done:,} photos; {len(bad):,} unreadable in all")


if __name__ == "__main__":
    main()
