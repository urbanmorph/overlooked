"""Image features (and class logits for fixed-label models) for the pilot's research-grade photos, per model.

Cache: data/model_check/feats_<model>.npz with photo_id, feats (L2-normalised), logits (eva02 only) and
elapsed seconds of image work. Saved every SAVE_EVERY seconds and on exit (also on Ctrl-C or error), so a
stopped run continues where it stopped, and a finished cache means a rerun does no work.

BioCLIP 2 is not run again: its features are copied from the fnf pilot cache (same photos, same model).

Run: data/model_check/.venv/bin/python -u experiments/model_check/embed.py <model> [<model> ...]
Models: bioclip-2, bioclip-2-rerun, bioclip-2.5, bioclip, dinov2-large, eva02-inat21
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch
from common import BIOCLIP2_DIR, DATA, PHOTOS, atomic_savez, research_photos
from PIL import Image

SAVE_EVERY = 120  # seconds
MODELS = {
    "bioclip-2": "imageomics/bioclip-2",
    "bioclip-2-rerun": "imageomics/bioclip-2",  # same model run here, to time it with this loader
    "bioclip-2.5": "imageomics/bioclip-2.5-vith14",
    "bioclip": "imageomics/bioclip",
    "dinov2-large": "facebook/dinov2-large",
    "eva02-inat21": "timm/eva02_large_patch14_clip_336.merged2b_ft_inat21",
}
BATCH = {"bioclip-2.5": 16, "eva02-inat21": 16}


def cache_path(name):
    return DATA / f"feats_{name}.npz"


def load_cache(name):
    p = cache_path(name)
    if not p.exists():
        return {"photo_id": np.zeros(0, dtype=np.int64), "feats": None, "logits": None, "elapsed": 0.0}
    c = np.load(p)
    return {"photo_id": c["photo_id"], "feats": c["feats"], "logits": c.get("logits"), "elapsed": float(c["elapsed"])}


def save_cache(name, ids, feats, logits, elapsed):
    arrays = {
        "photo_id": np.asarray(ids, dtype=np.int64),
        "feats": np.concatenate(feats).astype(np.float32),
        "elapsed": np.float64(elapsed),
    }
    if logits:
        arrays["logits"] = np.concatenate(logits).astype(np.float16)
    atomic_savez(cache_path(name), **arrays)


def copy_bioclip2(photo_ids):
    """Take the pilot's BioCLIP 2 features for these photos; its timing was measured on 17,626 photos."""
    c = np.load(BIOCLIP2_DIR / "pilot_image_features.npz")
    pos = {int(p): i for i, p in enumerate(c["photo_id"])}
    rows = [pos[int(p)] for p in photo_ids]
    secs = float(c["secs_per_1000"]) * len(rows) / 1000
    atomic_savez(
        cache_path("bioclip-2"),
        photo_id=np.asarray(photo_ids, dtype=np.int64),
        feats=c["feats"][rows],
        elapsed=np.float64(secs),
    )
    print(f"bioclip-2: copied {len(rows)} features from the pilot cache", flush=True)


def build(name, device):
    """Return (preprocess(PIL) -> tensor, forward(batch) -> (feats, logits or None))."""
    repo = MODELS[name]
    norm = torch.nn.functional.normalize
    if name.startswith("bioclip"):
        import open_clip

        model, _, pre = open_clip.create_model_and_transforms(f"hf-hub:{repo}")
        model = model.to(device).eval()
        return pre, lambda x: (norm(model.encode_image(x), dim=-1), None)
    if name == "eva02-inat21":
        import timm

        model = timm.create_model(f"hf-hub:{repo}", pretrained=True).to(device).eval()
        pre = timm.data.create_transform(**timm.data.resolve_data_config({}, model=model))

        def fwd(x):
            f = model.forward_head(model.forward_features(x), pre_logits=True)
            return norm(f, dim=-1), model.head(f)

        return pre, fwd
    if name == "dinov2-large":
        from transformers import AutoImageProcessor, AutoModel

        proc = AutoImageProcessor.from_pretrained(repo)
        model = AutoModel.from_pretrained(repo).to(device).eval()
        return (
            lambda im: proc(images=im, return_tensors="pt")["pixel_values"][0],
            lambda x: (norm(model(pixel_values=x).pooler_output, dim=-1), None),
        )
    raise SystemExit(f"unknown model {name}")


def embed(name, photo_ids, device):
    c = load_cache(name)
    done = {int(p) for p in c["photo_id"]}
    todo = [p for p in photo_ids if int(p) not in done]
    if not todo:
        print(f"{name}: all {len(photo_ids)} photos cached; nothing to do", flush=True)
        return
    print(f"{name}: {len(done)} cached, {len(todo)} to embed on {device}", flush=True)
    pre, fwd = build(name, device)
    ids = list(c["photo_id"])
    feats = [c["feats"]] if c["feats"] is not None else []
    logits = [c["logits"]] if c["logits"] is not None else []
    elapsed, last_save = c["elapsed"], time.time()
    bs = BATCH.get(name, 32)
    load = lambda p: pre(Image.open(PHOTOS / f"{p}.jpg").convert("RGB"))
    try:
        with ThreadPoolExecutor(8) as pool, torch.no_grad():
            for i in range(0, len(todo), bs):
                chunk = todo[i : i + bs]
                t0 = time.time()
                x = torch.stack(list(pool.map(load, chunk))).to(device)
                f, lg = fwd(x)
                feats.append(f.float().cpu().numpy())
                if lg is not None:
                    logits.append(lg.float().cpu().numpy())
                elapsed += time.time() - t0
                ids.extend(chunk)
                if (i // bs) % 20 == 0:
                    print(f"  {name}: {len(ids)}/{len(photo_ids)}  {1000 * elapsed / len(ids):.1f} s/1000", flush=True)
                if time.time() - last_save > SAVE_EVERY:
                    save_cache(name, ids, feats, logits, elapsed)
                    last_save = time.time()
    finally:
        if len(ids) > len(c["photo_id"]):
            save_cache(name, ids, feats, logits, elapsed)
            print(f"{name}: saved {len(ids)} photos, {1000 * elapsed / len(ids):.1f} s per 1,000", flush=True)


def main():
    photo_ids = research_photos().photo_id.astype(np.int64).tolist()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    for name in sys.argv[1:]:
        if name == "bioclip-2":
            if not cache_path(name).exists():
                copy_bioclip2(photo_ids)
            continue
        embed(name, photo_ids, device)


if __name__ == "__main__":
    main()
