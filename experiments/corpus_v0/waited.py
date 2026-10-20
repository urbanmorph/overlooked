"""Step 4: test set T1 "waited". For the T1 sample (test observers only, up to 300 per group, from
build_sets.py), fetch each observation's identification history from the iNaturalist API (read only, 200 ids
per request, cached) and keep those that reached research grade at least 30 days after they were created,
and that are still research grade at the same species today.

Outputs: data/corpus_v0/t1_history.parquet (every sampled observation with created, research-grade date,
waited days, identifiers, why it is in or out) and data/corpus_v0/t1.parquet (the qualifying rows).
Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/waited.py
"""

import inat
import pandas as pd
from lib import DATA, RESULTS, accepted_names, atomic_parquet, binomial, log
from logic import waited_record

MIN_WAIT_DAYS = 30
CACHE = DATA / "inat_t1.jsonl"


def reason(r, row_species, accepted):
    if r.get("missing"):
        return "not returned by the API (deleted or private)"
    if r["quality_grade"] != "research":
        return f"now {r['quality_grade']}"
    name = binomial(r["taxon_name"]) if r["taxon_name"] else None
    if name != row_species and accepted.get(name) != row_species:
        return "species changed since the GBIF copy"
    if r["rg_at"] is None:
        return "research-grade date not found in history"
    if r["waited_days"] < MIN_WAIT_DAYS:
        return f"research grade within {MIN_WAIT_DAYS} days"
    return "qualifies"


def history(s):
    """The sample with each observation's history fields and why it is in T1 or not (API answers cached)."""
    obs = inat.fetch(s.obs_id.tolist(), CACHE)
    rows = []
    for oid in s.obs_id:
        o = obs[int(oid)]
        rows.append(
            {"obs_id": int(oid), "missing": True} if o.get("missing") else {**waited_record(o), "missing": False}
        )
    h = s.merge(pd.DataFrame(rows), on="obs_id", how="left")
    names = [binomial(n) for n in h.taxon_name.dropna().unique()]
    accepted = accepted_names([n for n in names if n])
    h["why"] = [
        reason(r._asdict(), r.species, accepted)
        for r in h[["missing", "quality_grade", "taxon_name", "rg_at", "waited_days", "species"]].itertuples(
            index=False
        )
    ]
    return h


def main():
    h = history(pd.read_parquet(DATA / "t1_sample.parquet"))
    atomic_parquet(h, DATA / "t1_history.parquet")
    t1 = h[h.why == "qualifies"].reset_index(drop=True)
    atomic_parquet(t1, DATA / "t1.parquet")
    summary = (
        h.groupby("group")
        .agg(
            sampled=("obs_id", "size"),
            qualify=("why", lambda w: int((w == "qualifies").sum())),
            rg_within_30d=("why", lambda w: int(w.str.startswith("research grade within").sum())),
            changed_or_gone=(
                "why",
                lambda w: int(
                    w.isin(
                        ["species changed since the GBIF copy", "not returned by the API (deleted or private)"]
                    ).sum()
                    + w.str.startswith("now").sum()
                ),
            ),
            no_rg_date=("why", lambda w: int((w == "research-grade date not found in history").sum())),
        )
        .reset_index()
    )
    q = t1.groupby("group").agg(
        median_waited_days=("waited_days", "median"),
        median_identifiers=("n_identifiers", "median"),
        observers=("observer", "nunique"),
        species=("species", "nunique"),
    )
    summary = summary.merge(q.reset_index(), on="group", how="left")
    tot = {
        "group": "All",
        **{c: int(summary[c].sum()) for c in ("sampled", "qualify", "rg_within_30d", "changed_or_gone", "no_rg_date")},
        "median_waited_days": t1.waited_days.median(),
        "median_identifiers": t1.n_identifiers.median(),
        "observers": t1.observer.nunique(),
        "species": t1.species.nunique(),
    }
    summary = pd.concat([summary, pd.DataFrame([tot])])
    summary["median_waited_days"] = summary.median_waited_days.round(0)
    summary.to_csv(RESULTS / "t1_waited.csv", index=False)
    log("\n" + summary.to_string(index=False))
    log("why:\n" + h.why.value_counts().to_string())


if __name__ == "__main__":
    main()
