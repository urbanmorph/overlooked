"""Queue check, part B: re-check a frozen queue sample (run at 30, 60 and 90 days after it was drawn).

Fetches the same observation ids from the iNaturalist API (read only, 200 per request; answers cached in
inat_recheck_<drawn>_<today>.jsonl, so a rerun on the same day sends no requests and gives the same result), and
records which reached research grade or changed taxon. Scores, per group, band and overall: share that reached
research grade, and of those, share whose final species was in the shown shortlist, in the frozen 90% set, first,
in the top 5, and whose genus was in the shown genera. The frozen file's SHA-256 is checked against
results/frozen.csv first, so a changed file is never scored.

Outputs: results/recheck_<drawn>_<today>.csv (the summary) and a row per run in results/recheck_log.csv (the
row of the same day is replaced). Per-observation outcomes stay in data/corpus_v0/recheck_<drawn>_<today>.parquet.
Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/recheck.py [frozen parquet | --shown <run>]
"""

import sys
from datetime import date
from pathlib import Path

import inat
import numpy as np
import pandas as pd
from candidates import candidates
from freeze import sha256
from lib import DATA, RESULTS, ROOT, accepted_names, atomic_parquet, binomial, log, pct
from logic import SPECIES_OR_BELOW, match_name, recheck_outcome

HITS = ["in_shown", "in_set90", "first", "in_top5", "genus_in_shown"]


def summary(df, by):
    def one(g):
        rg = g[g.reached_rg]
        out = {"n": len(g), "reached_rg": len(rg), "reached_rg_pct": pct(g.reached_rg)}
        out["changed_taxon_pct"] = pct(g.changed_taxon.dropna().astype(bool))
        out["rg_with_candidate_species"] = int(rg.final_species.notna().sum())
        for h in HITS:
            out[f"{h}_pct"] = pct(rg[h].astype(bool)) if len(rg) else None
        return out

    rows = [{by: k, **one(g)} for k, g in df.groupby(by)]
    rows.append({by: "All", **one(df)})
    return pd.DataFrame(rows)


def load_set(argv):
    """(name, frame) of the set to score: a frozen test (default the newest; SHA-256 checked against
    results/frozen.csv) or, with --shown <run>, the rows published in data/shortlist/<run>/ (SHA-256 checked against
    its shown.sha256)."""
    if argv[:1] == ["--shown"]:
        run = argv[1]
        path = ROOT / "data" / "shortlist" / run / "shown.parquet"
        want = (path.parent / "shown.sha256").read_text().strip()
        name = f"shown_{run}"
    else:
        path = Path(argv[0]) if argv else max(DATA.glob("frozen_*.parquet"))
        frozen_csv = pd.read_csv(RESULTS / "frozen.csv")
        w = frozen_csv.loc[frozen_csv.file == path.name, "sha256"]
        want = w.iloc[0] if len(w) else None
        name = "frozen"
    if sha256(path) != want:
        raise SystemExit(f"{path}: SHA-256 does not match its recorded checksum; not scored")
    return name, path, pd.read_parquet(path)


def main():
    kind, path, fz = load_set(sys.argv[1:])
    drawn, today = fz.drawn.iloc[0], date.today().isoformat()
    days = (date.fromisoformat(today) - date.fromisoformat(drawn)).days
    tag = drawn if kind == "frozen" else kind
    obs = inat.fetch(fz.obs_id.tolist(), DATA / f"inat_recheck_{tag}_{today}.jsonl")
    cand = candidates()
    by_group = cand.groupby("group").species.apply(set).to_dict()
    now_name = {}
    for oid, o in obs.items():
        t = (o.get("taxon") or {}) if not o.get("missing") else {}
        now_name[oid] = binomial(t.get("name")) if t.get("rank") in SPECIES_OR_BELOW else None
    acc = accepted_names(sorted({n for n in now_name.values() if n}))
    rows = []
    for r in fz.to_dict("records"):
        o = obs[int(r["obs_id"])]
        now = {"missing": True} if o.get("missing") else {
            "quality_grade": o.get("quality_grade"), "taxon_id": (o.get("taxon") or {}).get("id")
        }  # fmt: skip
        final, _ = match_name([now_name.get(int(r["obs_id"]))], by_group.get(r["group"], set()), acc)
        rows.append({"obs_id": r["obs_id"], "group": r["group"], "band": r["band"], **recheck_outcome(r, now, final)})
    out = pd.DataFrame(rows)
    atomic_parquet(out, DATA / f"recheck_{tag}_{today}.parquet")
    s = pd.concat([summary(out, "group").assign(by="group"), summary(out, "band").rename(columns={"band": "group"})])
    s["by"] = s["by"].fillna("band")
    s.insert(0, "days", days)
    s.insert(0, "checked", today)
    s.to_csv(RESULTS / f"recheck_{tag}_{today}.csv", index=False)
    allrow = s[(s.group == "All") & (s.by == "group")].drop(columns=["group", "by"]).assign(drawn=drawn, set=kind)
    logp = RESULTS / "recheck_log.csv"
    old = pd.read_csv(logp) if logp.exists() else pd.DataFrame()
    if len(old):
        old = old.assign(set=old.get("set", "frozen")).fillna({"set": "frozen"})
        old = old[~((old.checked == today) & (old.drawn == drawn) & (old.set == kind))]
    pd.concat([old, allrow]).to_csv(logp, index=False)
    pd.set_option("display.width", 250)
    log(f"re-check of {path.name} on {today} ({days} days after drawing):")
    log("\n" + s.replace({np.nan: None}).to_string(index=False))


if __name__ == "__main__":
    main()
