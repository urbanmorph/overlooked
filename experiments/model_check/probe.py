"""Protocol 2: what training on an Indian corpus would add. A probe on frozen image features, trained and
tested on the answer key itself with 5-fold cross-validation, per group.

Only species with at least MIN_PHOTOS answer-key photos in the group are used. Folds keep each observation's
photos together (StratifiedGroupKFold on the observation id; the pilot has one photo per observation, so
this equals folds by photo). Classifiers: 1-nearest neighbour (cosine) and logistic regression on
standardised features (C fixed at 1.0, no tuning). The candidate set of a probe is the species of the
training folds, so these numbers are not comparable one-to-one with zero-shot over all Indian species; the
zero-shot result on the same photos is reported next to it for reference.

Inputs: data/model_check/feats_<model>.npz, data/model_check/zeroshot_<model>.csv (for the reference)
Outputs: experiments/model_check/results/probe_groups.csv, data/model_check/probe_<model>.csv (per photo)
Run: data/model_check/.venv/bin/python -u experiments/model_check/probe.py
"""

import warnings

import numpy as np
import pandas as pd
from common import DATA, HERE, answer_key, pct
from embed import cache_path, load_cache
from scoring import score_probs
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import StandardScaler
from zeroshot import ZERO_SHOT, Scorer, add_shortlist, features, shortlist_frames

MIN_PHOTOS = 3
K = 5
ZS_REFERENCE = {"bioclip-2.5": "bioclip-2.5-filled"}  # zero-shot reference with its label gaps filled
PROBE_MODELS = ["bioclip-2", "bioclip-2.5", "bioclip", "dinov2-large", "eva02-inat21"]


def folds(df, min_photos=MIN_PHOTOS, k=K):
    """Rows of species with >= min_photos photos, and k (train, test) splits grouped by observation id."""
    n = df.true_species.map(df.true_species.value_counts())
    sub = df[n >= min_photos].reset_index(drop=True)
    if sub.true_species.nunique() < 2:
        return sub, []
    # sklearn needs one class with >= k photos; small groups (e.g. lichens) fall back to fewer folds
    k = min(k, int(sub.true_species.value_counts().max()))
    cv = StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # "least populated class has only 3 members": expected
        return sub, list(cv.split(np.zeros(len(sub)), sub.true_species, groups=sub.id))


def probe_group(x, sub, splits, scorer=None, sls=None):
    """Out-of-fold results for 1-NN, logistic regression and (with a scorer) closed-set zero-shot over the
    same training-fold species, so the training effect can be read apart from the smaller candidate set."""
    out = []
    for tr, te in splits:
        ytr = sub.true_species.iloc[tr].to_numpy()
        classes = np.unique(ytr)
        # 1-NN by cosine (features are L2-normalised): score = best similarity per class
        sim = x[te] @ x[tr].T
        nn = np.full((len(te), len(classes)), -np.inf)
        cidx = np.searchsorted(classes, ytr)
        for c in range(len(classes)):
            nn[:, c] = sim[:, cidx == c].max(axis=1)
        sc = StandardScaler().fit(x[tr])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lr = LogisticRegression(C=1.0, max_iter=2000).fit(sc.transform(x[tr]), ytr)
        p_lr = lr.predict_proba(sc.transform(x[te]))
        t = sub.true_species.iloc[te].tolist()
        a = sub.accepted.iloc[te].tolist()
        # 1-NN genus vote uses softmax-like weights so genus sums stay meaningful
        p_nn = np.exp(20 * (nn - nn.max(axis=1, keepdims=True)))
        r_nn = score_probs(p_nn, classes, t, a).add_prefix("knn_")
        r_lr = score_probs(p_lr, lr.classes_, t, a).add_prefix("lr_")
        if sls is not None:
            add_shortlist(sls["lr"], p_lr, lr.classes_, sub.iloc[te])
        parts = [r_nn, r_lr]
        if scorer is not None:
            cand = [s for s in classes if s in scorer.index]
            if cand:
                p_zs = scorer.probs(sub.kpos.iloc[te].to_numpy(), cand)
                parts.append(score_probs(p_zs, cand, t, a, cand_set=set(cand)).add_prefix("zsc_"))
                if sls is not None:
                    add_shortlist(sls["zs_closed"], p_zs, cand, sub.iloc[te])
        r = pd.concat(parts, axis=1)
        r.index = sub.index[te]
        out.append(r)
    return sub.join(pd.concat(out))


def main():
    key = answer_key()
    rows, shortlists = [], []
    for model in PROBE_MODELS:
        if not cache_path(model).exists():
            print(f"{model}: no features yet; skipped", flush=True)
            continue
        c = load_cache(model)
        pos = {int(p): i for i, p in enumerate(c["photo_id"])}
        if any(int(p) not in pos for p in key.photo_id):
            print(f"{model}: features incomplete; skipped", flush=True)
            continue
        zs_model = ZS_REFERENCE.get(model, model)
        zs_path = DATA / f"zeroshot_{zs_model}.csv"
        zs = pd.read_csv(zs_path).set_index("photo_id") if zs_path.exists() else None
        acc_path = DATA / "zeroshot_bioclip-2.csv"  # carries the GBIF accepted name per photo
        accepted = pd.read_csv(acc_path).set_index("photo_id").accepted
        k = key.assign(kpos=np.arange(len(key)), accepted=key.photo_id.map(accepted).where(lambda s: s.notna(), None))
        scorer = Scorer(zs_model, *features(zs_model, key)) if zs_model in ZERO_SHOT else None
        res = []
        sls = {m: {"P": [], "T": [], "Pg": [], "Tg": [], "obs": [], "group": []} for m in ("lr", "zs_closed")}
        for group, g in k.groupby("group"):
            sub, splits = folds(g.reset_index(drop=True))
            if not splits:
                continue
            x = c["feats"][[pos[int(p)] for p in sub.photo_id]]
            r = probe_group(x, sub, splits, scorer, sls)
            if zs is not None:
                z = zs.loc[r.photo_id]
                r["zs_species_correct"] = z.species_correct.to_numpy()
                r["zs_species_correct_syn"] = z.species_correct_syn.to_numpy()
                r["zs_genus_correct"] = z.genus_correct.to_numpy()
                r["zs_species_in_top5"] = z.species_in_top5.to_numpy()
            res.append(r)
            print(
                f"  {model} {group}: {len(sub)} photos, {sub.true_species.nunique()} species; "
                f"LR top-1 {pct(r.lr_species_correct)}%",
                flush=True,
            )
        for method, sl in sls.items():
            if sl["P"]:
                shortlists.append(shortlist_frames(sl, model, method=method))
        r = pd.concat(res)
        r.drop(columns=["photo_url"]).to_csv(DATA / f"probe_{model}.csv", index=False)
        for group, g in list(r.groupby("group")) + [("All", r)]:
            row = {
                "model": model,
                "group": group,
                "n": len(g),
                "species": g.true_species.nunique(),
                "knn_top1": pct(g.knn_species_correct),
                "lr_top1": pct(g.lr_species_correct),
                "lr_top1_syn": pct(g.lr_species_correct_syn),
                "lr_genus": pct(g.lr_genus_correct),
                "lr_top5": pct(g.lr_species_in_top5),
            }
            if "zs_species_correct" in g:
                row.update(
                    {
                        "zs_top1": pct(g.zs_species_correct),
                        "zs_top1_syn": pct(g.zs_species_correct_syn),
                        "zs_genus": pct(g.zs_genus_correct),
                        "zs_top5": pct(g.zs_species_in_top5),
                    }
                )
            if "zsc_species_correct" in g:
                z = g.zsc_species_correct.fillna(False).astype(bool)
                row.update(
                    {"zs_closed_top1": pct(z), "zs_closed_top5": pct(g.zsc_species_in_top5.fillna(False).astype(bool))}
                )
            rows.append(row)
    out = pd.DataFrame(rows)
    (HERE / "results").mkdir(exist_ok=True)
    out.to_csv(HERE / "results" / "probe_groups.csv", index=False)
    pd.concat(shortlists).to_csv(HERE / "results" / "shortlist_probe.csv", index=False)
    pd.set_option("display.width", 250)
    print(out[out.group == "All"].to_string(index=False))


if __name__ == "__main__":
    main()
