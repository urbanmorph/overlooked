"""Step 8 data: the fnf pilot's queue sample (needs-ID rows of out/id_pilot_sample.csv; fnf is read only),
re-fetched from the iNaturalist API today (read only, 200 ids per request, cached in inat_queue.jsonl).

For each row: the state now (quality grade, taxon), the species it now has if research grade at species
level (T2 truth), and the observer's own current species identification (T3), both matched to the group's
candidate names (exact, then GBIF synonyms). Output: data/corpus_v0/queue.parquet
Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/queue_fetch.py
"""

import inat
import pandas as pd
from candidates import candidates
from lib import DATA, accepted_names, atomic_parquet, binomial, log
from logic import SPECIES_OR_BELOW, match_name

PILOT = "/Users/sathya/Projects/biodiversity/fnf/out/id_pilot_sample.csv"
CACHE = DATA / "inat_queue.jsonl"


def observer_name(o):
    """Binomial of the observer's own current identification at species or below, else None."""
    me = (o.get("user") or {}).get("id")
    for i in o.get("identifications") or []:
        t = i.get("taxon") or {}
        if (i.get("user") or {}).get("id") == me and i.get("current") and t.get("rank") in SPECIES_OR_BELOW:
            return binomial(t.get("name"))
    return None


def main():
    s = pd.read_csv(PILOT)
    s = s[s.quality_grade == "needs_id"].reset_index(drop=True)
    obs = inat.fetch(s.id.tolist(), CACHE)
    cand = candidates()
    by_group = cand.groupby("group").species.apply(set).to_dict()
    rows = []
    for r in s.itertuples():
        o = obs[int(r.id)]
        t = o.get("taxon") or {}
        now = binomial(t.get("name")) if t.get("rank") in SPECIES_OR_BELOW else None
        rows.append(
            {
                "obs_id": int(r.id),
                "group": r.group,
                "photo_id": int(r.photo_id),
                "pilot_taxon": r.taxon_name,
                "pilot_rank": r.taxon_rank,
                "missing": bool(o.get("missing")),
                "now_quality": o.get("quality_grade"),
                "now_taxon": t.get("name"),
                "now_rank": t.get("rank"),
                "now_name": now if o.get("quality_grade") == "research" else None,
                "observer_name": observer_name(o),
                "observer_login": (o.get("user") or {}).get("login"),
                "observer_display": (o.get("user") or {}).get("name"),
            }
        )
    q = pd.DataFrame(rows)
    names = sorted({n for n in pd.concat([q.now_name, q.observer_name]).dropna()})
    acc = accepted_names(names)
    for col, out in (("now_name", "now_species"), ("observer_name", "observer_species")):
        q[out] = [match_name([n], by_group.get(g, set()), acc)[0] for n, g in zip(q[col], q.group)]
    atomic_parquet(q, DATA / "queue.parquet")
    log(
        f"queue: {len(q):,} rows; now research grade {int((q.now_quality == 'research').sum()):,}; "
        f"with a species now (T2) {int(q.now_species.notna().sum()):,}; "
        f"observer named a candidate species (T3) {int(q.observer_species.notna().sum()):,}; missing {int(q.missing.sum())}"
    )
    log("now quality:\n" + q.now_quality.value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
