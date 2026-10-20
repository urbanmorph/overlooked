"""Markdown tables for the README from the result files (no new computation beyond counting T2/T3 rows).

Writes results/t2.csv, results/t3.csv and prints the tables.
Run: data/model_check/.venv/bin/python experiments/corpus_v0/report.py
"""

import numpy as np
import pandas as pd
from lib import DATA, RESULTS, pct

COLS = ["r@1", "r@3", "r@5", "r@10", "r@20", "k90", "k95", "conf90_cov", "conf90_median", "conf90_p90"]
COLS += ["conf95_cov", "conf95_median", "conf95_p90"]


def md(df):
    df = df.astype(object).where(df.notna(), "")
    head = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "|" + "---|" * len(df.columns)
    return "\n".join([head, sep] + ["| " + " | ".join(map(str, r)) + " |" for r in df.itertuples(index=False)])


def queue_table(q, who, best):
    """Per group with the validation-chosen method, and overall per method."""
    col = f"{who}_species"
    q = q[q[col].notna()]
    rows = []

    def one(g, label, method):
        r = g[f"{who}_rank"]
        return {
            "group": label,
            "method": method,
            "n": len(g),
            "top1": pct(r <= 1),
            "top5": pct(r <= 5),
            "in k90 list": pct(r <= g.k90.fillna(np.inf)),
            "median k90": g.k90.median(),
            "in 90% set": pct(g[f"{who}_in_set90"]),
            "median 90% set": g.set90_size.median(),
            "in 95% set": pct(g[f"{who}_in_set95"]),
            "median 95% set": g.set95_size.median(),
        }

    pick = q.merge(best, on="group")
    pick = pick[pick.method == pick.method_best]
    for grp, g in pick.groupby("group"):
        rows.append(one(g, grp, g.method.iloc[0]))
    rows.append(one(pick, "All", "best per group"))
    for m, g in q.groupby("method"):
        rows.append(one(g, "All", m))
    return pd.DataFrame(rows)


MIN_N = 40  # T1 rows below this: the verdict is provisional


def num(x):
    return float(x) if str(x) != "not reached" else np.inf


def verdicts(sp, ge, best, t3):
    """Per group, with the method chosen on validation. Rules fixed before reading the results:
    Quick to confirm: species k90 <= 3, 90% set median <= 2 and 95% set median <= 5;
    else genus only: genus k90 <= 3 and genus 95% set median <= 3; else expert only.
    Fewer than MIN_N T1 rows: provisional. T3 (observer's name in the 90% set) is shown, not used."""
    rows = []
    for r in best.itertuples():
        s = sp[(sp.method == r.method_best) & (sp.group == r.group)]
        if s.empty:
            continue
        s, g = s.iloc[0], ge[(ge.method == r.method_best) & (ge.group == r.group)].iloc[0]
        if num(s.k90) <= 3 and num(s.conf90_median) <= 2 and num(s.conf95_median) <= 5:
            v = "Quick to confirm"
        elif num(g.k90) <= 3 and num(g.conf95_median) <= 3:
            v = "genus only"
        else:
            v = "expert only"
        t = t3[t3.group == r.group]
        rows.append(
            {
                "group": r.group,
                "method": r.method_best,
                "T1 n": int(s.n),
                "species k90": s.k90,
                "90% set median": s.conf90_median,
                "95% set median": s.conf95_median,
                "genus k90": g.k90,
                "genus 95% set median": g.conf95_median,
                "T3 name in 90% set": t["in 90% set"].iloc[0] if len(t) else None,
                "verdict": v + (" (provisional: few test rows)" if s.n < MIN_N else ""),
            }
        )
    return pd.DataFrame(rows)


def by_era():
    """Top-1 and top-5 per method for T1 rows that reached research grade by 2024 (their photos may be in
    TreeOfLife-200M, BioCLIP's training set, built from GBIF) and in 2025 or later (unlikely to be)."""
    p = pd.read_parquet(DATA / "pred_t1.parquet").merge(
        pd.read_parquet(DATA / "t1.parquet")[["obs_id", "rg_at"]], on="obs_id"
    )
    p["research grade"] = np.where(pd.to_datetime(p.rg_at, utc=True).dt.year >= 2025, "2025 or later", "by 2024")
    rows = []
    for era, g in p.groupby("research grade"):
        row = {"research grade": era, "n": len(g)}
        for m in ("zero-shot", "classifier", "combined"):
            row[f"{m} r@1"] = pct(g[f"rank_{m}"] <= 1)
            row[f"{m} r@5"] = pct(g[f"rank_{m}"] <= 5)
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    pd.set_option("display.width", 250)
    counts = pd.read_csv(RESULTS / "corpus_counts.csv")
    print("## Corpus counts\n" + md(counts) + "\n")
    print("## Names\n" + md(pd.read_csv(RESULTS / "names.csv")) + "\n")
    print("## T1 waited\n" + md(pd.read_csv(RESULTS / "t1_waited.csv")) + "\n")
    m = pd.read_csv(RESULTS / "t1_metrics.csv")
    best = pd.read_csv(RESULTS / "t1_best.csv")
    sp = m[m.level == "species"]
    ge = m[m.level == "genus"]
    head = sp.merge(best, on="group", how="left")
    head = head[(head.method == head.method_best)]
    g13 = ge.set_index(["method", "group"])[["r@1", "r@3"]].rename(columns={"r@1": "genus r@1", "r@3": "genus r@3"})
    head = head.join(g13, on=["method", "group"])
    head = head[["group", "method", "n", "r@1", "r@5", "genus r@1", "k90", "conf90_median", "conf95_median"]]
    print("## Headline (method chosen per group on validation)\n" + md(head) + "\n")
    for meth in sp.method.unique():
        t = sp[sp.method == meth].join(g13.xs(meth), on="group")
        print(f"## T1 {meth}\n" + md(t[["group", "n", "median_candidates"] + COLS + ["genus r@1", "genus r@3"]]) + "\n")
    print("## T1 by when research grade was reached (BioCLIP training overlap check)\n" + md(by_era()) + "\n")
    print("## Unseen species\n" + md(pd.read_csv(RESULTS / "t1_unseen.csv")) + "\n")
    print("## Choices on validation\n" + md(pd.read_csv(RESULTS / "choice.csv")) + "\n")
    qp = DATA / "pred_queue.parquet"
    if qp.exists():
        q = pd.read_parquet(qp)
        for who, name in (("now", "t2"), ("observer", "t3")):
            t = queue_table(q, who, best)
            t.to_csv(RESULTS / f"{name}.csv", index=False)
            print(f"## {name.upper()}\n" + md(t) + "\n")
        for f, title in (("gate.csv", "Gate"), ("frozen.csv", "Frozen"), ("recheck_log.csv", "Re-check log")):
            if (RESULTS / f).exists():
                t = pd.read_csv(RESULTS / f)
                print(f"## {title}\n" + md(t.drop(columns=[c for c in ("file", "sha256") if c in t])) + "\n")
        v = verdicts(sp, ge, best, pd.read_csv(RESULTS / "t3.csv"))
        v.to_csv(RESULTS / "verdicts.csv", index=False)
        print("## Verdicts\n" + md(v) + "\n")


if __name__ == "__main__":
    main()
