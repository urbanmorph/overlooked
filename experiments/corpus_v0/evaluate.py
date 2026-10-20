"""Step 7 and 8: species shortlists on T1 (waited, test observers) and on the pilot's queue (T2, T3).

Per group, over the group's candidate species (the model check's bioclip-2.5-filled lists):
- zero-shot: BioCLIP 2.5 with the filled label vectors (model check zeroshot.Scorer), all candidates;
- classifier: trained on corpus v0 features; logistic regression (weight decay chosen on validation) or
  nearest neighbour (best cosine per species), whichever has the better validation top-1. It can only name
  species with corpus photos, so its candidates are those species;
- combined: w * zero-shot + (1 - w) * classifier, both temperature-calibrated on validation, w on validation.
Validation: corpus observers picked by a second stable hash (15%), so it is split by observer too. The
method reported as "best" per group is chosen on validation top-1, never on T1.

Metrics on T1 (model check scoring.shortlist_table): top-1/3/5/10/20 species and genus, fixed list length
for 90% and 95%, split-conformal sets at 90% and 95% calibrated on half of T1 split by observer (20
repeats). Species with no corpus photo are reported apart.

T2: queue rows that are research grade now; T3: the observer's own species name on queue rows. Both use the
fixed k and the conformal thresholds from all of T1 in that group.

Outputs: results/t1_metrics.csv, results/t1_unseen.csv, results/t1_best.csv, results/choice.csv,
data/corpus_v0/pred_t1.parquet, pred_queue.parquet (per row).
Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/evaluate.py
"""

import time
import warnings

import numpy as np
import pandas as pd
import torch
from candidates import candidates
from embed_v0 import load_all
from lib import DATA, RESULTS, atomic_parquet, atomic_savez, log, pct
from logic import (
    combine_probs,
    conformal_threshold,
    fit_temperature,
    fixed_k,
    in_validation,
    knn_class_scores,
    softmax,
    unseen_summary,
)

METHODS = ("zero-shot", "classifier", "combined")
SCORES = DATA / "scores"  # best method's probabilities per group (T1 and queue sample), for gate.py and freeze.py
WEIGHT_DECAYS = (1e-4, 1e-3, 1e-2)
WEIGHTS = (0.25, 0.5, 0.75)
MIN_T1 = 20  # groups with fewer T1 rows are reported as too few to test (no padding)
MAX_VAL = 3000  # validation rows per group used for choices (enough for the few numbers chosen there)
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"


# --- classifiers ----------------------------------------------------------------------------------------


def train_lr(x, y, n_classes, wd):
    """Multinomial logistic regression on standardised features (full-batch L-BFGS)."""
    xt = torch.from_numpy(x).float().to(DEVICE)
    mu, sd = xt.mean(0), xt.std(0) + 1e-6
    xs = (xt - mu) / sd
    yt = torch.from_numpy(y).long().to(DEVICE)
    lin = torch.nn.Linear(x.shape[1], n_classes).to(DEVICE)
    torch.nn.init.zeros_(lin.weight)
    torch.nn.init.zeros_(lin.bias)
    opt = torch.optim.LBFGS(lin.parameters(), lr=1, max_iter=200, history_size=20, line_search_fn="strong_wolfe")

    def closure():
        opt.zero_grad()
        loss = torch.nn.functional.cross_entropy(lin(xs), yt) + wd * lin.weight.pow(2).sum()
        loss.backward()
        return loss

    opt.step(closure)

    def logits(q):
        with torch.no_grad():
            qs = (torch.from_numpy(q).float().to(DEVICE) - mu) / sd
            return lin(qs).cpu().numpy().astype(np.float64)

    return logits


class Classifier:
    """Fitted classifier over `classes` (species with corpus photos): logits(features) and a temperature."""

    def __init__(self, kind, x, y, classes, wd=None):
        self.kind, self.classes, self.wd, self.temp = kind, np.asarray(classes, dtype=object), wd, 1.0
        if kind == "lr":
            self._f = train_lr(x, y, len(classes), wd)
        else:
            self._x, self._y = x, y

    def logits(self, q):
        if self.kind == "lr":
            return self._f(q)
        s = knn_class_scores(q, self._x, self._y, len(self.classes)).astype(np.float64)
        return np.where(np.isfinite(s), s, -1e9)

    def probs(self, q):
        return softmax(self.logits(q) / self.temp)


def top1(p, y):
    return float(np.mean(p.argmax(axis=1) == y)) if len(y) else 0.0


# --- per group ------------------------------------------------------------------------------------------


def zs_logprobs(scorer, pos, cand):
    if len(pos) == 0:
        return np.zeros((0, len(cand)))
    return np.log(np.clip(scorer.probs(np.asarray(pos), cand), 1e-30, None))


def fit_group(group, cand, corpus_g, F, fpos, scorer):
    """Choices on validation, then the final classifier on all corpus rows. Returns (models, choice row)."""
    cidx = {s: i for i, s in enumerate(cand)}
    tr = corpus_g[~corpus_g.val]
    va = corpus_g[corpus_g.val]
    if len(va) > MAX_VAL:
        va = va.sample(MAX_VAL, random_state=0)
    xv = F[[fpos[p] for p in va.photo_id]]
    yv_all = va.species.map(cidx).to_numpy()
    choice = {"group": group, "corpus_rows": len(corpus_g), "corpus_species": corpus_g.species.nunique()}
    # zero-shot temperature
    zv = zs_logprobs(scorer, [fpos[p] for p in va.photo_id], cand)
    t_zs = fit_temperature(zv, yv_all) if len(va) >= 20 else 1.0
    choice.update(val_rows=len(va), t_zs=round(t_zs, 3), val_top1_zero_shot=round(100 * top1(zv, yv_all), 1))
    all_classes = np.array(sorted(corpus_g.species.unique()), dtype=object)
    if len(all_classes) < 2:
        choice["method_best"] = "zero-shot"
        return {"t_zs": t_zs, "clf": None, "w": None, "best": "zero-shot"}, choice
    # classifier choice on validation (trained on the non-validation observers)
    tr_classes = np.array(sorted(tr.species.unique()), dtype=object)
    best = None
    if len(tr_classes) >= 2 and len(va) >= 20:
        xt = F[[fpos[p] for p in tr.photo_id]]
        yt = np.searchsorted(tr_classes, tr.species.to_numpy())
        seen = va.species.isin(set(tr_classes)).to_numpy()
        yv = np.searchsorted(tr_classes, va.species.to_numpy())
        cands = [("knn", None)] + [("lr", wd) for wd in WEIGHT_DECAYS]
        for kind, wd in cands:
            c = Classifier(kind, xt, yt, tr_classes, wd)
            lg = c.logits(xv)
            acc = float(np.mean(seen & (lg.argmax(1) == yv)))
            choice[f"val_top1_{kind}{'' if wd is None else f'_{wd:g}'}"] = round(100 * acc, 1)
            if best is None or acc > best[0]:
                best = (acc, kind, wd, c, lg)
        acc, kind, wd, c, lg = best
        temp = fit_temperature(lg[seen], yv[seen]) if seen.sum() >= 20 else 1.0
        # combination weight on validation, over all candidates (classifier is 0 for species it lacks)
        p_zs = softmax(zv / t_zs)
        p_cl = np.zeros_like(p_zs)
        p_cl[:, [cidx[s] for s in tr_classes]] = softmax(lg / temp)
        ll = {}
        for w in WEIGHTS:
            pc = combine_probs(p_zs, p_cl, w)
            ll[w] = float(np.mean(np.log(np.clip(pc[np.arange(len(yv_all)), yv_all], 1e-12, None))))
            choice[f"val_top1_combined_{w}"] = round(100 * top1(pc, yv_all), 1)
        w = max(ll, key=ll.get)
        val_top1 = {
            "zero-shot": top1(zv, yv_all),
            "classifier": acc,
            "combined": top1(combine_probs(p_zs, p_cl, w), yv_all),
        }
        choice.update(clf_kind=kind, clf_wd=wd, clf_temp=round(temp, 3), w=w, val_top1_classifier=round(100 * acc, 1))
        choice["val_top1_combined"] = round(100 * val_top1["combined"], 1)
        best_method = max(val_top1, key=val_top1.get)
    else:  # too little validation: logistic regression with the middle weight decay, plain average
        kind, wd, temp, w, best_method = "lr", WEIGHT_DECAYS[1], 1.0, 0.5, "combined"
        choice.update(clf_kind=kind, clf_wd=wd, clf_temp=temp, w=w, note="validation too small; defaults")
    # final classifier on all corpus rows of the group
    xa = F[[fpos[p] for p in corpus_g.photo_id]]
    ya = np.searchsorted(all_classes, corpus_g.species.to_numpy())
    clf = Classifier(kind, xa, ya, all_classes, wd)
    clf.temp = temp
    choice["method_best"] = best_method
    return {"t_zs": t_zs, "clf": clf, "w": w, "best": best_method}, choice


def method_probs(models, scorer, F, fpos, photo_ids, cand):
    """{method: (probs, candidate list)} for these photos."""
    pos = [fpos[p] for p in photo_ids]
    p_zs = softmax(zs_logprobs(scorer, pos, cand) / models["t_zs"])
    out = {"zero-shot": (p_zs, list(cand))}
    clf = models["clf"]
    if clf is not None:
        p_c = clf.probs(F[pos])
        out["classifier"] = (p_c, list(clf.classes))
        cidx = {s: i for i, s in enumerate(cand)}
        full = np.zeros_like(p_zs)
        full[:, [cidx[s] for s in clf.classes]] = p_c
        out["combined"] = (combine_probs(p_zs, full, models["w"]), list(cand))
    return out


def rank_of(p, cand, name):
    """1-based rank of `name` in p over cand (ties in the model's favour, as the model check); inf if absent."""
    if name not in cand:
        return np.inf
    i = cand.index(name)
    return 1 + int((p > p[i]).sum())


def save_scores(group, models, scorer, F, fpos, cand, g, sets):
    """The best method's probabilities for this group's T1 rows and for each extra set (scores/<group>.npz:
    q_ the frozen queue sample, l_ the live set), for gate.py, freeze.py and live.py."""
    from pipeline.shortlist import slug

    best = models["best"]
    pt1, cl = method_probs(models, scorer, F, fpos, g.photo_id.tolist(), cand)[best]
    extra = {}
    for k, s in sets.items():
        extra[f"{k}_probs"] = method_probs(models, scorer, F, fpos, s.photo_id.tolist(), cand)[best][0].astype(
            np.float32
        )
        extra[f"{k}_obs"] = s.obs_id.to_numpy(np.int64)
    atomic_savez(
        SCORES / f"{slug(group)}.npz",
        group=np.array(group),
        method=np.array(best),
        names=np.array(cl, dtype=object).astype(str),
        t1_probs=pt1.astype(np.float32),
        t1_true=g.species.to_numpy().astype(str),
        t1_observer=g.observer.fillna("").to_numpy().astype(str),
        t1_rg_at=g.rg_at.fillna("").to_numpy().astype(str) if "rg_at" in g else np.array([], str),
        t1_obs=g.obs_id.to_numpy(np.int64),
        **extra,
    )


def queue_rows(group, qg, qprobs, t1g):
    """Queue predictions with this group's T1 calibration: fixed k90 and conformal thresholds from all of T1.
    For the species it has now (T2) and the observer's own name (T3): rank and whether it is in each set."""
    out = []
    for m, (p, cl) in qprobs.items():
        k90 = fixed_k([r[f"rank_{m}"] for r in t1g], 0.9)
        thr = {a: conformal_threshold([r[f"ptrue_{m}"] for r in t1g], a) for a in (0.9, 0.95)}
        for i, r in enumerate(qg.itertuples()):
            row = {"obs_id": r.obs_id, "group": group, "method": m, "k90": k90, "top1": cl[int(p[i].argmax())]}
            for a, t in thr.items():
                row[f"set{round(a * 100)}_size"] = int((p[i] >= t).sum())
            for who, name in (("now", r.now_species), ("observer", r.observer_species)):
                ok = isinstance(name, str) and name in cl
                row[f"{who}_rank"] = rank_of(p[i], cl, name) if ok else np.inf
                for a, t in thr.items():
                    row[f"{who}_in_set{round(a * 100)}"] = bool(ok and p[i][cl.index(name)] >= t)
            out.append(row)
    return out


# --- main -----------------------------------------------------------------------------------------------


def main():
    from scoring import shortlist_inputs, shortlist_table
    from zeroshot import Scorer

    t_start = time.time()
    ids, F = load_all()
    fpos = {int(p): i for i, p in enumerate(ids)}
    log(f"features: {len(ids):,} photos")
    cand_all = candidates()
    corpus = pd.read_parquet(DATA / "corpus.parquet")
    corpus = corpus[corpus.photo_id.isin(fpos)].copy()
    corpus["val"] = corpus.observer.map(in_validation)
    t1 = pd.read_parquet(DATA / "t1.parquet")
    n_t1 = len(t1)
    t1 = t1[t1.photo_id.isin(fpos)].reset_index(drop=True)
    size = t1.group.value_counts()
    small = size[size < MIN_T1]
    if len(small):
        log(f"too few T1 rows to test (< {MIN_T1}), left out of the T1 metrics: {small.to_dict()}")
    t1 = t1[~t1.group.isin(small.index)].reset_index(drop=True)
    log(f"corpus rows with features {len(corpus):,}; T1 rows tested {len(t1):,} of {n_t1:,}")
    qpath = DATA / "queue.parquet"
    queue = pd.read_parquet(qpath) if qpath.exists() else None
    if queue is not None:
        queue = queue[queue.photo_id.isin(fpos)].reset_index(drop=True)
    qs_path = DATA / "queue_sample.parquet"
    qs = pd.read_parquet(qs_path) if qs_path.exists() else pd.DataFrame(columns=["group", "photo_id", "obs_id"])
    qs = qs[qs.photo_id.isin(fpos)].reset_index(drop=True)
    lv_path = DATA / "live_sample.parquet"
    lv = pd.read_parquet(lv_path) if lv_path.exists() else qs.iloc[:0]
    lv = lv[lv.photo_id.isin(fpos)].reset_index(drop=True)
    SCORES.mkdir(exist_ok=True)
    scorer = Scorer("bioclip-2.5-filled", {"feats": F}, np.arange(len(F)))

    sl = {m: {"P": [], "T": [], "Pg": [], "Tg": [], "obs": [], "group": []} for m in METHODS}
    pred_rows, choices, qrows = [], [], []
    for group in sorted(set(t1.group) | set(qs.group)):
        tg = time.time()
        cand = cand_all[cand_all.group == group].species.tolist()
        cg = corpus[corpus.group == group]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            models, choice = fit_group(group, cand, cg, F, fpos, scorer)
        choices.append(choice)
        seen = set(cg.species)
        g = t1[t1.group == group]
        save_scores(group, models, scorer, F, fpos, cand, g, {"q": qs[qs.group == group], "l": lv[lv.group == group]})
        if g.empty:
            log(f"{group}: no T1 rows; queue-sample scores only ({time.time() - tg:.0f} s)")
            continue
        probs = method_probs(models, scorer, F, fpos, g.photo_id.tolist(), cand)
        ranks = {}
        for m, (p, cl) in probs.items():
            P, T, Pg, Tg, _ = shortlist_inputs(p, cl, g.species.tolist(), [None] * len(g))
            for k, v in (("P", P), ("T", T), ("Pg", Pg), ("Tg", Tg)):
                sl[m][k] += v
            sl[m]["obs"] += g.observer.tolist()
            sl[m]["group"] += g.group.tolist()
            ranks[m] = [rank_of(pi, cl, t) for pi, t in zip(p, g.species)]
        for i, r in enumerate(g.itertuples()):
            row = {"obs_id": r.obs_id, "group": group, "species": r.species, "observer": r.observer}
            row["seen"] = r.species in seen
            for m, (p, cl) in probs.items():
                row[f"rank_{m}"] = ranks[m][i]
                row[f"top1_{m}"] = cl[int(p[i].argmax())]
                pt = p[i][cl.index(r.species)] if r.species in cl else 0.0
                row[f"ptrue_{m}"] = float(pt)
            pred_rows.append(row)
        if queue is not None and (queue.group == group).any():
            qg = queue[queue.group == group]
            t1g = [pr for pr in pred_rows if pr["group"] == group]
            qrows += queue_rows(group, qg, method_probs(models, scorer, F, fpos, qg.photo_id.tolist(), cand), t1g)
        log(
            f"{group}: T1 {len(g)}, candidates {len(cand)}, corpus species {len(seen)}; "
            + ", ".join(f"{m} top-1 {pct(np.array(ranks[m]) <= 1)}%" for m in ranks)
            + f"; best on validation: {models['best']} ({time.time() - tg:.0f} s)"
        )

    pred = pd.DataFrame(pred_rows)
    atomic_parquet(pred, DATA / "pred_t1.parquet")
    pd.DataFrame(choices).to_csv(RESULTS / "choice.csv", index=False)
    frames = []
    for m in METHODS:
        if not sl[m]["P"]:
            continue
        for level, P, T in (("species", sl[m]["P"], sl[m]["T"]), ("genus", sl[m]["Pg"], sl[m]["Tg"])):
            t = shortlist_table(P, T, sl[m]["obs"], sl[m]["group"])
            t.insert(0, "level", level)
            t.insert(0, "method", m)
            frames.append(t)
    metrics = pd.concat(frames)
    metrics.to_csv(RESULTS / "t1_metrics.csv", index=False)
    uns = []
    for m in METHODS:
        if f"rank_{m}" in pred:
            u = unseen_summary(pred.assign(rank=pred[f"rank_{m}"].fillna(np.inf)))
            u.insert(0, "method", m)
            uns.append(u)
    pd.concat(uns).to_csv(RESULTS / "t1_unseen.csv", index=False)
    best = pd.DataFrame(choices)[["group", "method_best"]]
    best.to_csv(RESULTS / "t1_best.csv", index=False)
    if qrows:
        q = pd.DataFrame(qrows).merge(queue[["obs_id", "now_species", "observer_species"]], on="obs_id")
        atomic_parquet(q, DATA / "pred_queue.parquet")
    log(f"evaluate: done in {(time.time() - t_start) / 60:.1f} min")


if __name__ == "__main__":
    main()
