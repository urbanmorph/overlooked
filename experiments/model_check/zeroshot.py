"""Protocol 1: zero-shot species ID on the pilot's answer key, per model, with the pilot's candidate rule.

For each answer-key photo, the candidates are the species of its group that have an Indian GBIF record and
that the model knows (its published label set: BioCLIP text embeddings, or the iNat21 class list).
Scores: top-1 species, top-1 genus (probabilities summed by genus), top-5 species; exact and synonym-aware.

Label vectors that are all zero in a published file are made again with the model's own text encoder
(the pilot's fix for BioCLIP 2), cached in data/model_check/txt_reencoded_<model>.npz.

Inputs: data/model_check/feats_<model>.npz (embed.py), gbif_match.json (synonyms.py), fnf pilot files.
Outputs: data/model_check/zeroshot_<model>.csv (per photo), experiments/model_check/results/zeroshot_groups.csv,
         results/vocab.csv, results/speed.csv
Run: data/model_check/.venv/bin/python -u experiments/model_check/zeroshot.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from common import (
    BIOCLIP2_DIR,
    DATA,
    HERE,
    answer_key,
    atomic_savez,
    india_species,
    pct,
)
from embed import MODELS, cache_path, load_cache
from huggingface_hub import hf_hub_download
from scoring import score_probs, shortlist_inputs, shortlist_table, summarise
from synonyms import accepted_names

RESULTS = HERE / "results"
TOL = "imageomics/TreeOfLife-200M"
LABEL_FILES = {  # model -> (repo, repo_type, json, npy)
    "bioclip-2": None,  # the pilot's local copy of TreeOfLife-200M embeddings/txt_emb_bioclip-2.*
    "bioclip-2.5": (
        TOL,
        "dataset",
        "embeddings/txt_emb_bioclip-2.5-vith14.json",
        "embeddings/txt_emb_bioclip-2.5-vith14.npy",
    ),
    "bioclip": (
        "imageomics/TreeOfLife-10M",
        "dataset",
        "embeddings/txt_emb_species.json",
        "embeddings/txt_emb_species.npy",
    ),
}
ZERO_SHOT = ["bioclip-2", "bioclip-2.5", "bioclip-2.5-filled", "bioclip", "eva02-inat21"]
# BioCLIP 2.5 scored with its published label file, and "filled": taxa missing from that file (it has almost no
# reptiles or ray-finned fish) take their taxonomy string from the BioCLIP 2 file and are encoded with the
# BioCLIP 2.5 text encoder. Same image features.
FEATS_OF = {"bioclip-2.5-filled": "bioclip-2.5"}


def clip_labels(model):
    if model == "bioclip-2":
        js, npy = BIOCLIP2_DIR / "txt_emb_bioclip-2.json", BIOCLIP2_DIR / "txt_emb_bioclip-2.npy"
    else:
        repo, rtype, j, n = LABEL_FILES[model]
        js, npy = hf_hub_download(repo, j, repo_type=rtype), hf_hub_download(repo, n, repo_type=rtype)
    labels = json.loads(Path(js).read_text())
    emb = np.load(npy, mmap_mode="r")
    if emb.shape[0] != len(labels):
        emb = emb.T
    index = {}
    for i, (tax, _) in enumerate(labels):
        if tax[5] and tax[6]:
            index.setdefault(f"{tax[5]} {tax[6]}", i)
    return index, emb, labels


def logit_scale(model):
    """Read the CLIP temperature from the weights file without building the model."""
    repo = MODELS[model]
    from huggingface_hub import file_exists

    if file_exists(repo, "open_clip_model.safetensors"):
        from safetensors import safe_open

        with safe_open(hf_hub_download(repo, "open_clip_model.safetensors"), "pt") as f:
            return float(f.get_tensor("logit_scale").exp())
    else:
        sd = torch.load(hf_hub_download(repo, "open_clip_pytorch_model.bin"), map_location="cpu", weights_only=True)
        return float(sd["logit_scale"].exp())


def reencode(model, labels, rows):
    """Text vectors for label rows, made with the model's own text encoder (cached per model by row number):
    rows whose published vector is zero, and for bioclip-2.5-filled the rows added from the BioCLIP 2 file."""
    cache = DATA / f"txt_reencoded_{model}.npz"
    have = dict(np.load(cache)) if cache.exists() else {}
    if model == "bioclip-2" and (BIOCLIP2_DIR / "txt_emb_reencoded.npz").exists():
        have = {**dict(np.load(BIOCLIP2_DIR / "txt_emb_reencoded.npz")), **have}
    todo = [i for i in rows if str(i) not in have]
    if todo:
        import open_clip

        print(f"  {model}: encoding {len(todo)} label vectors with the text encoder", flush=True)
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        m, _, _ = open_clip.create_model_and_transforms(f"hf-hub:{MODELS[model]}")
        m = m.to(device).eval()
        tok = open_clip.get_tokenizer(f"hf-hub:{MODELS[model]}")
        try:
            with torch.no_grad():
                for j in range(0, len(todo), 256):
                    chunk = todo[j : j + 256]
                    txt = [
                        f"a photo of {' '.join(labels[i][0])}"
                        + (f" with common name {labels[i][1]}." if labels[i][1] else ".")
                        for i in chunk
                    ]
                    f = torch.nn.functional.normalize(m.encode_text(tok(txt).to(device)), dim=-1)
                    have.update({str(i): v for i, v in zip(chunk, f.float().cpu().numpy())})
        finally:
            atomic_savez(cache, **{k: v for k, v in have.items()})
    return np.stack([have[str(i)] for i in rows])


class Scorer:
    """Zero-shot class probabilities for a model over any list of candidate species names (all in its index).
    feats/logits are the cached rows `rows`; probs() takes positions into those rows."""

    def __init__(self, model, c, rows):
        self.model, self.zero_total, self.filled_total = model, 0, 0
        if model == "eva02-inat21":
            names = json.loads(Path(hf_hub_download(MODELS[model], "config.json")).read_text())["label_names"]
            self.index = {}
            for i, n in enumerate(names):
                self.index.setdefault(" ".join(str(n).split()[:2]), i)
            self.logits = torch.from_numpy(c["logits"][rows].astype(np.float32))
        else:
            self.enc = FEATS_OF.get(model, model)
            self.index, self.emb, self.labels = clip_labels(self.enc)
            if model == "bioclip-2.5-filled":
                b2_index, _, b2_labels = clip_labels("bioclip-2")
                self.labels = list(self.labels)
                for name, i in b2_index.items():
                    if name not in self.index:
                        self.index[name] = len(self.labels)
                        self.labels.append(b2_labels[i])
            self.scale = logit_scale(self.enc)
            self.feats = torch.from_numpy(c["feats"][rows]).float()

    def probs(self, pos, cand):
        lrows = [self.index[s] for s in cand]
        if self.model == "eva02-inat21":
            return self.logits[pos][:, lrows].softmax(dim=-1).numpy()
        n = len(self.emb)
        w = np.stack([self.emb[i] if i < n else np.zeros(self.emb.shape[1], np.float32) for i in lrows])
        w = w.astype(np.float32)
        zero = np.abs(w).sum(axis=1) == 0
        if zero.any():
            self.zero_total += int(sum(z and i < n for i, z in zip(lrows, zero)))
            self.filled_total += int(sum(z and i >= n for i, z in zip(lrows, zero)))
            w[zero] = reencode(self.enc, self.labels, [r for r, z in zip(lrows, zero) if z])
        w = torch.nn.functional.normalize(torch.from_numpy(w), dim=-1)
        return (self.scale * self.feats[pos] @ w.T).softmax(dim=-1).numpy()


def features(model, key):
    c = load_cache(FEATS_OF.get(model, model))
    pos = {int(p): i for i, p in enumerate(c["photo_id"])}
    missing = [p for p in key.photo_id if int(p) not in pos]
    if missing:
        return None
    rows = [pos[int(p)] for p in key.photo_id]
    return c, rows


def run_model(model, key, sp):
    got = features(model, key)
    if got is None:
        print(f"{model}: features missing; run embed.py {model} first", flush=True)
        return None, None, None
    c, rows = got
    scorer = Scorer(model, c, rows)
    index = scorer.index
    in_vocab = sp.species.isin(index)
    out, sl = [], {"P": [], "T": [], "Pg": [], "Tg": [], "obs": [], "group": []}
    for group, g in key.groupby("group"):
        cand = sp[(sp.group == group) & in_vocab].species.tolist()
        if not cand:  # nothing in this group can be named (e.g. reptiles in the published BioCLIP 2.5 file)
            res = score_probs(np.zeros((len(g), 1)), ["(none)"], g.true_species.tolist(), g.accepted.tolist())
            res["pred_species"] = res["pred_genus"] = res["pred_top5"] = None
            add_shortlist(sl, np.zeros((len(g), 1)), ["(none)"], g)  # counted as misses at every k
        else:
            probs = scorer.probs(g.index.to_numpy(), cand)
            res = score_probs(probs, cand, g.true_species.tolist(), g.accepted.tolist())
            add_shortlist(sl, probs, cand, g)
        res.index = g.index
        out.append(res)
    shortlist = shortlist_frames(sl, model)
    pred = key.join(pd.concat(out))
    pred.drop(columns=["photo_url"]).to_csv(DATA / f"zeroshot_{model}.csv", index=False)
    vocab = sp.assign(in_vocab=in_vocab).groupby("group").in_vocab.agg(["size", "sum"]).reset_index()
    vocab.columns = ["group", "india_species", "in_vocab"]
    vocab = pd.concat(
        [vocab, pd.DataFrame([{"group": "All", "india_species": len(sp), "in_vocab": int(in_vocab.sum())}])]
    )
    vocab["pct_in_vocab"] = (100 * vocab.in_vocab / vocab.india_species).round(1)
    vocab.insert(0, "model", model)
    print(
        f"{model}: label set {len(index):,} species; {int(in_vocab.sum()):,} of {len(sp):,} Indian species "
        f"({pct(in_vocab)}%); {scorer.zero_total} zero label vectors re-encoded; "
        f"{scorer.filled_total} added from the BioCLIP 2 label file",
        flush=True,
    )
    return pred, vocab, shortlist


def add_shortlist(sl, probs, cand, g):
    P, T, Pg, Tg, _ = shortlist_inputs(probs, cand, g.true_species.tolist(), g.accepted.tolist())
    sl["P"] += P
    sl["T"] += T
    sl["Pg"] += Pg
    sl["Tg"] += Tg
    sl["obs"] += g.id.tolist()
    sl["group"] += g.group.tolist()


def shortlist_frames(sl, model, **meta):
    """Species and genus shortlist tables. Groups with no candidates are absent here and count as misses
    only through the top-1 table."""
    frames = []
    for level, P, T in (("species", sl["P"], sl["T"]), ("genus", sl["Pg"], sl["Tg"])):
        if not P:
            continue
        t = shortlist_table(P, T, sl["obs"], sl["group"])
        t.insert(0, "level", level)
        for k, v in reversed(list({"model": model, **meta}.items())):
            t.insert(0, k, v)
        frames.append(t)
    return pd.concat(frames) if frames else None


def main():
    RESULTS.mkdir(exist_ok=True)
    key = answer_key()
    sp = india_species()
    acc = accepted_names(key.true_species.unique().tolist())
    key["accepted"] = key.true_species.map(acc)
    groups, vocabs, speed, shortlists = [], [], [], []
    for model in ZERO_SHOT:
        if not cache_path(FEATS_OF.get(model, model)).exists():
            print(f"{model}: no features yet; skipped", flush=True)
            continue
        pred, vocab, shortlist = run_model(model, key, sp)
        if pred is None:
            continue
        s = summarise(pred)
        s.insert(0, "model", model)
        groups.append(s)
        vocabs.append(vocab)
        shortlists.append(shortlist)
    for model in MODELS:
        if cache_path(model).exists():
            c = load_cache(model)
            speed.append(
                {
                    "model": model,
                    "photos": len(c["photo_id"]),
                    "secs_per_1000": round(1000 * c["elapsed"] / len(c["photo_id"]), 1),
                }
            )
    pd.concat(groups).to_csv(RESULTS / "zeroshot_groups.csv", index=False)
    pd.concat(vocabs).to_csv(RESULTS / "vocab.csv", index=False)
    pd.concat(shortlists).to_csv(RESULTS / "shortlist_zeroshot.csv", index=False)
    pd.DataFrame(speed).to_csv(RESULTS / "speed.csv", index=False)
    pd.set_option("display.width", 250)
    allg = pd.concat(groups)
    print(allg[allg.group == "All"].to_string(index=False))
    print(pd.DataFrame(speed).to_string(index=False))


if __name__ == "__main__":
    main()
