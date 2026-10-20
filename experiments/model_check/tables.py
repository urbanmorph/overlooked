"""Print the README's result tables (markdown) from results/*.csv, so every number is quoted from the runs.

Run: data/model_check/.venv/bin/python experiments/model_check/tables.py
"""

import pandas as pd
from common import HERE, STRONG, WEAK

R = HERE / "results"
ZS_MODELS = ["bioclip-2", "bioclip-2.5", "bioclip-2.5-filled", "bioclip", "eva02-inat21"]
SPEED_OF = {"bioclip-2": "bioclip-2-rerun", "bioclip-2.5-filled": "bioclip-2.5"}


def md(df):
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def main():
    zs = pd.read_csv(R / "zeroshot_groups.csv")
    sl = pd.read_csv(R / "shortlist_zeroshot.csv")
    vocab = pd.read_csv(R / "vocab.csv")
    speed = pd.read_csv(R / "speed.csv").set_index("model").secs_per_1000
    rows = []
    for m in ZS_MODELS:
        a = zs[(zs.model == m) & (zs.group == "All")].iloc[0]
        s = sl[(sl.model == m) & (sl.group == "All") & (sl.level == "species")].iloc[0]
        g = sl[(sl.model == m) & (sl.group == "All") & (sl.level == "genus")].iloc[0]
        v = vocab[(vocab.model == m) & (vocab.group == "All")].iloc[0]
        rows.append({
            "model": m, "s/1000 photos": speed.get(SPEED_OF.get(m, m)),
            "Indian spp. in vocab": f"{v.pct_in_vocab}%", "answer in candidates": f"{a.in_cand_syn}%",
            "top-1 sp. (exact / syn)": f"{a.top1} / {a.top1_syn}", "top-1 genus (syn)": a.genus_syn,
            "top-5 sp. (syn)": a.top5_syn, "top-1 if answer is a candidate": a.top1_in_cand,
            "sp. r@10": s["r@10"], "sp. r@20": s["r@20"], "sp. k for 90%": s.k90, "genus k for 90%": g.k90,
            "genus k for 95%": g.k95,
        })
    print("## Overall, zero-shot (answer key, 5,604 photos)\n")
    print(md(pd.DataFrame(rows)))

    print("\n## Per group, zero-shot: top-1 species (syn) / species in top 10 / species k for 90%\n")
    groups = WEAK + ["Flies", "Moths", "Fish", "Reptiles"] + STRONG
    tab = []
    for grp in groups:
        row = {"group": grp}
        for m in ZS_MODELS:
            a = zs[(zs.model == m) & (zs.group == grp)].iloc[0]
            s = sl[(sl.model == m) & (sl.group == grp) & (sl.level == "species")].iloc[0]
            row[m] = f"{a.top1_syn} / {s['r@10']} / {s.k90}"
        tab.append(row)
    print(md(pd.DataFrame(tab)))

    print("\n## Shortlist detail (zero-shot, all groups): recall at k and calibrated sets\n")
    cols = ["model", "level", "group", "n", "median_candidates", "r@1", "r@3", "r@5", "r@10", "r@20", "k90",
            "conf90_cov", "conf90_median", "conf90_p90", "k95", "conf95_cov", "conf95_median", "conf95_p90"]
    best = sl[sl.model.isin(["bioclip-2", "bioclip-2.5-filled"])][cols]
    print(md(best))

    pr = pd.read_csv(R / "probe_groups.csv")
    sp = pd.read_csv(R / "shortlist_probe.csv")
    print("\n## Probe (species with >= 3 answer-key photos; 5-fold CV by observation)\n")
    rows = []
    for m in pr.model.unique():
        a = pr[(pr.model == m) & (pr.group == "All")].iloc[0]
        lr = sp[(sp.model == m) & (sp.method == "lr") & (sp.level == "species") & (sp.group == "All")].iloc[0]
        rows.append({"features": m, "photos": a.n, "species": a.species, "1-NN top-1": a.knn_top1,
                     "LR top-1": a.lr_top1, "LR genus": a.lr_genus, "LR top-5": a.lr_top5, "LR k for 95%": lr.k95,
                     "zero-shot closed-set top-1": a.get("zs_closed_top1"),
                     "zero-shot closed-set top-5": a.get("zs_closed_top5"), "zero-shot open top-1": a.get("zs_top1")})
    print(md(pd.DataFrame(rows)))
    print("\n## Probe per group, LR top-1 (zero-shot closed-set top-1 in brackets)\n")
    tab = []
    for grp in groups:
        row = {"group": grp}
        for m in pr.model.unique():
            a = pr[(pr.model == m) & (pr.group == grp)]
            if len(a):
                a = a.iloc[0]
                zc = "" if pd.isna(a.get("zs_closed_top1")) else f" ({a.zs_closed_top1})"
                row[m] = f"{a.lr_top1}{zc} n={a.n}"
        tab.append(row)
    print(md(pd.DataFrame(tab)))


if __name__ == "__main__":
    main()
