"""Scoring rules for the model check, shared by the zero-shot and probe protocols.

Exact match: the predicted name equals the answer key's species name (iNaturalist taxon cut to a binomial).
Synonym-aware match: the answer key's name is first mapped to its accepted species in the GBIF backbone
(GBIF species match API, cached). Candidate names already come from GBIF occurrences, so they are backbone
names, and a guess counts as right if it equals either the iNaturalist name or its GBIF accepted name.
"""

import numpy as np
import pandas as pd
from common import pct

SPECIES_LEVEL = {"SPECIES", "SUBSPECIES", "VARIETY", "FORM"}
METRICS = ["true_in_candidates", "species_correct", "genus_correct", "species_in_top5"]


def accepted_from_match(m):
    """Accepted species name from a GBIF /v1/species/match answer, or None if it did not match to a species."""
    if not m or m.get("matchType") in (None, "NONE", "HIGHERRANK"):
        return None
    if m.get("rank") not in SPECIES_LEVEL:
        return None
    return m.get("species")


def genus(name):
    return str(name).split()[0] if name else None


def score_probs(probs, cand, true_sp, accepted, cand_set=None):
    """Per-row results for one group. probs: (n, len(cand)) scores; higher is better (need not sum to 1)."""
    cand = np.asarray(cand, dtype=object)
    cand_set = set(cand) if cand_set is None else cand_set
    gcodes, gnames = pd.factorize(pd.Series(cand).str.split().str[0])
    order = np.argsort(-probs, axis=1)[:, :5]
    rows = []
    for p, top5, t, a in zip(probs, order, true_sp, accepted):
        gp = np.bincount(gcodes, weights=p, minlength=len(gnames))
        pred, pred_g, t5 = cand[top5[0]], gnames[int(gp.argmax())], set(cand[top5])
        names = {t} | ({a} if a else set())
        rows.append(
            {
                "pred_species": pred,
                "pred_prob": round(float(p[top5[0]]), 4),
                "pred_genus": pred_g,
                "pred_top5": "|".join(cand[top5]),
                "true_in_candidates": t in cand_set,
                "true_in_candidates_syn": bool(names & cand_set),
                "species_correct": pred == t,
                "species_correct_syn": pred in names,
                "genus_correct": pred_g == genus(t),
                "genus_correct_syn": pred_g in {genus(n) for n in names},
                "species_in_top5": t in t5,
                "species_in_top5_syn": bool(names & t5),
            }
        )
    return pd.DataFrame(rows)


def summarise(df, by="group"):
    """Per-group and overall percentages (exact and synonym-aware)."""

    def one(g):
        return {
            "n": len(g),
            "in_cand": pct(g.true_in_candidates),
            "in_cand_syn": pct(g.true_in_candidates_syn),
            "top1": pct(g.species_correct),
            "top1_syn": pct(g.species_correct_syn),
            "genus": pct(g.genus_correct),
            "genus_syn": pct(g.genus_correct_syn),
            "top5": pct(g.species_in_top5),
            "top5_syn": pct(g.species_in_top5_syn),
            # accuracy when the model could name the answer: separates vocabulary gaps from visual errors
            "top1_in_cand": pct(g.species_correct[g.true_in_candidates]),
        }

    rows = [{by: k, **one(g)} for k, g in df.groupby(by)]
    rows.append({by: "All", **one(df)})
    return pd.DataFrame(rows)


# --- Shortlist metrics (headline): the model proposes a list; a taxonomist picks or rejects. ---
KS = (1, 3, 5, 10, 20)
TARGETS = (0.90, 0.95)
NOT_REACHED = "not reached"


def true_rank(p, idx):
    """1-based rank of the best-scored correct class (ties count in the model's favour); inf if none is a candidate."""
    if len(idx) == 0:
        return np.inf
    return 1 + int((p > p[list(idx)].max()).sum())


def shortlist_inputs(probs, cand, true_sp, accepted):
    """Per-row species and genus score vectors plus the indices that count as right (synonym-aware)."""
    cand = list(cand)
    pos = {s: i for i, s in enumerate(cand)}
    gcodes, gnames = pd.factorize(pd.Series(cand, dtype=object).str.split().str[0])
    gpos = {g: i for i, g in enumerate(gnames)}
    P, T, Pg, Tg = [], [], [], []
    for p, t, a in zip(probs, true_sp, accepted):
        names = [n for n in (t, a) if n]
        P.append(np.asarray(p, dtype=np.float64))
        T.append(sorted({pos[n] for n in names if n in pos}))
        Pg.append(np.bincount(gcodes, weights=p, minlength=len(gnames)))
        Tg.append(sorted({gpos[genus(n)] for n in names if genus(n) in gpos}))
    return P, T, Pg, Tg, gnames


def _conformal(P, T, obs, groups, target, n_splits, seed):
    """Split conformal (score = 1 - p(true)), calibrated per group on half of the observations and tested on
    the other half; repeated n_splits times. Returns (mean coverage %, test set sizes pooled over splits)."""
    rng = np.random.default_rng(seed)
    ptrue = np.array([p[t].max() if len(t) else 0.0 for p, t in zip(P, T)])
    has = np.array([len(t) > 0 for t in T])
    obs, groups = np.asarray(obs), np.asarray(groups)
    covered, sizes = [], []
    for _ in range(n_splits):
        for g in np.unique(groups):
            rows = np.flatnonzero(groups == g)
            ids = rng.permutation(np.unique(obs[rows]))
            cal_ids = set(ids[: len(ids) // 2])
            cal = np.array([o in cal_ids for o in obs[rows]])
            c, te = rows[cal], rows[~cal]
            if len(c) == 0 or len(te) == 0:
                continue
            level = np.ceil((len(c) + 1) * target) / len(c)
            q = 1.0 if level > 1 else np.quantile(1 - ptrue[c], level, method="higher")
            thr = 1 - q
            for i in te:
                covered.append(bool(has[i] and ptrue[i] >= thr))
                sizes.append(int((P[i] >= thr).sum()))
    return 100 * float(np.mean(covered)), np.array(sizes)


def _one(P, T, obs, groups, n_splits, seed):
    ranks = np.array([true_rank(p, t) for p, t in zip(P, T)])
    n = len(ranks)
    in_cand = float(np.isfinite(ranks).mean())
    out = {"n": n, "median_candidates": int(np.median([len(p) for p in P]))}
    for k in KS:
        out[f"r@{k}"] = pct(ranks <= k)
    for a in TARGETS:
        tag = round(a * 100)
        if in_cand < a:  # the full candidate list itself misses the target
            out[f"k{tag}"] = out[f"conf{tag}_cov"] = out[f"conf{tag}_median"] = out[f"conf{tag}_p90"] = NOT_REACHED
            continue
        out[f"k{tag}"] = int(np.sort(ranks)[int(np.ceil(a * n)) - 1])
        cov, sizes = _conformal(P, T, obs, groups, a, n_splits, seed)
        out[f"conf{tag}_cov"] = round(cov, 1)
        out[f"conf{tag}_median"] = int(np.median(sizes))
        out[f"conf{tag}_p90"] = int(np.percentile(sizes, 90))
    return out


def shortlist_table(P, T, obs, groups, n_splits=20, seed=0):
    """Per-group and overall shortlist metrics. Overall: pooled ranks; conformal calibrated per group, pooled.
    Fixed k is the smallest list length that holds the right answer for the target share of photos (chosen on
    all photos; an upper bound on what a held-out k would give)."""
    groups = np.asarray(groups)
    rows = []
    for g in list(dict.fromkeys(groups)):
        m = np.flatnonzero(groups == g)
        sel = lambda xs, m=m: [xs[i] for i in m]
        rows.append({"group": g, **_one(sel(P), sel(T), sel(list(obs)), groups[m], n_splits, seed)})
    rows.append({"group": "All", **_one(P, T, obs, groups, n_splits, seed)})
    return pd.DataFrame(rows)
