"""Queue check: the gate verdict per group (rules fixed in the README, "Queue check (rules fixed 20 October 2026)").

From scores/<group>.npz (evaluate.py; the method chosen on validation): species and genus 90% split-conformal sets
calibrated on observer-split halves of T1, 20 repeats (logic.conformal_rows, the model check's rule), top-1, the
same for T1 rows that reached research grade in 2025 or later, and the 95% sets (reported, not used).
Output: results/gate.csv. Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/gate.py
"""

import numpy as np
import pandas as pd
from evaluate import MIN_T1, SCORES
from lib import RESULTS, log
from logic import NOT_ENOUGH, conformal_rows, gate


def truth(p, names, true):
    pos = {n: i for i, n in enumerate(names)}
    idx = np.array([pos.get(t, -1) for t in true])
    has = idx >= 0
    p_true = np.where(has, p[np.arange(len(p)), np.maximum(idx, 0)], 0.0)
    return p_true, has


def level_stats(p, names, true, observers, new, target):
    """Coverage (%), median set size, and coverage for the 2025+ rows, at one level and target."""
    p_true, has = truth(p, names, true)
    cov, tested, sizes = conformal_rows(p_true, has, list(p), observers, target)
    pct = lambda m: round(100 * cov[m].sum() / tested[m].sum(), 1) if tested[m].sum() else None
    return pct(np.ones(len(p), bool)), int(np.median(sizes)) if sizes else None, pct(new)


def group_row(f):
    from pipeline.shortlist import genus, genus_probs

    z = np.load(f, allow_pickle=False)
    group, names, p, true = str(z["group"]), list(z["names"]), z["t1_probs"].astype(np.float64), z["t1_true"]
    n = len(true)
    row = {"group": group, "method": str(z["method"]), "n": n}
    if n < MIN_T1:  # too few to compute sets; the gate needs GATE_MIN_N anyway
        return {**row, "verdict": NOT_ENOUGH}
    obs = z["t1_observer"]
    new = pd.to_datetime(pd.Series(z["t1_rg_at"]), utc=True).dt.year.to_numpy() >= 2025
    genera, gp = genus_probs(p, names)
    gtrue = np.array([genus(t) for t in true])
    row.update(top1=round(100 * float(np.mean(np.array(names)[p.argmax(1)] == true)), 1), new_n=int(new.sum()))
    for tag, target in (("", 0.9), ("95_", 0.95)):
        row[f"sp_{tag}cov"], row[f"sp_{tag}median"], row[f"new_sp_{tag}cov"] = level_stats(
            p, names, true, obs, new, target
        )
        row[f"g_{tag}cov"], row[f"g_{tag}median"], row[f"new_g_{tag}cov"] = level_stats(
            gp, genera, gtrue, obs, new, target
        )
    row["verdict"] = gate({k: (v if v is not None else 0.0) for k, v in row.items()})
    return row


def main():
    rows = [group_row(f) for f in sorted(SCORES.glob("*.npz"))]
    out = pd.DataFrame(rows)
    out = out.sort_values(["verdict", "group"]).reset_index(drop=True)
    out.to_csv(RESULTS / "gate.csv", index=False)
    pd.set_option("display.width", 250)
    log("\n" + out.to_string(index=False))


if __name__ == "__main__":
    main()
