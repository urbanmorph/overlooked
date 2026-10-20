"""Shared paths and I/O helpers for corpus v0. Everything this experiment writes stays in data/corpus_v0/
(gitignored, on this machine only: no upload to R2, Hugging Face or anywhere else).

The model check's modules (common, scoring, synonyms, embed, zeroshot) are imported from
experiments/model_check, so the candidate lists, label vectors and metrics are the same.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODEL_CHECK = ROOT / "experiments" / "model_check"
for p in (str(ROOT), str(MODEL_CHECK)):
    if p not in sys.path:
        sys.path.append(p)

import common as _common  # model check module, importable once the path is set

binomial = _common.binomial

DATA = ROOT / "data" / "corpus_v0"
PHOTOS = DATA / "photos"  # medium photos, <photo_id>.jpg
EMB = DATA / "emb"  # .npz shards of BioCLIP 2.5 image features
RESULTS = HERE / "results"
for d in (DATA, PHOTOS, EMB, RESULTS):
    d.mkdir(parents=True, exist_ok=True)

SAVE_EVERY = 300  # seconds between checkpoints (the rule is at most 10 minutes)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def atomic_write_json(path, obj):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".json.tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else default


def atomic_parquet(df, path):
    path = Path(path)
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def atomic_savez(path, **arrays):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".npz")
    os.close(fd)
    np.savez(tmp, **arrays)
    os.replace(tmp, path)


class Checkpoint:
    """Calls save() when SAVE_EVERY seconds have passed since the last save; use .final() in a finally block."""

    def __init__(self, save, every=SAVE_EVERY):
        self.save, self.every, self.last = save, every, time.time()

    def tick(self):
        if time.time() - self.last >= self.every:
            self.save()
            self.last = time.time()

    def final(self):
        self.save()


def pct(x):
    x = np.asarray(x, dtype=float)
    return round(100 * float(x.mean()), 1) if len(x) else None


def load_parquet(name):
    return pd.read_parquet(DATA / name)


def ua():
    """User-Agent for iNaturalist and the open-data bucket (pipeline.health.ua)."""
    from pipeline.health import ua as _ua

    return _ua()


def accepted_names(names):
    """name -> GBIF backbone accepted species (model check synonyms.py), cached in data/corpus_v0/gbif_match.json,
    seeded once from the model check's cache so its file is never changed."""
    import shutil

    import synonyms

    mine = DATA / "gbif_match.json"
    if not mine.exists() and synonyms.CACHE.exists():
        shutil.copyfile(synonyms.CACHE, mine)
    synonyms.CACHE = mine
    return synonyms.accepted_names(names)
