"""Steps 2, 3 and 5, and the T1 sample of step 4.

2. Names: each record's group from its classification (the model check's GROUP_SQL); its species matched to
   that group's candidate names: exact (GBIF species, then the iNaturalist name as published), then
   synonyms through the GBIF backbone (accepted name of the iNaturalist name; and candidates whose accepted
   name is the record's species). Records that match no candidate are dropped and counted.
3. Observer split: train (80%) or test (20%) by a stable hash of recordedBy; every observation of a test
   observer is test-only. The pilot's observations (answer key and queue) are left out of both.
5. Corpus v0: train observers, first photo only (open-data bucket URL), at most CAP observations per species,
   spread across observers and states.
4. T1 sample: test observers, first photo, up to 300 random observations per group (waited.py goes on).

Outputs: data/corpus_v0/matched.parquet, corpus.parquet, t1_sample.parquet; results/names.csv,
results/corpus_counts.csv. Deterministic: a rerun writes the same files.
Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/build_sets.py [CAP]
"""

import sys

import duckdb
import numpy as np
import pandas as pd
from candidates import candidates
from lib import DATA, RESULTS, accepted_names, atomic_parquet, binomial, log
from logic import match_name, observer_split, sample_capped

CAP = int(sys.argv[1]) if len(sys.argv) > 1 else 15
T1_PER_GROUP = 300
PILOT = "/Users/sathya/Projects/biodiversity/fnf/out/id_pilot_sample.csv"
SECS_PER_1000 = 94.4  # BioCLIP 2.5 image work on this laptop (model check)


def with_groups(rec):
    from common import GROUP_SQL

    r = rec[["kingdom", "phylum", "class", "order", "family"]].assign(_rid=np.arange(len(rec)))
    # DuckDB does not keep row order on large frames without ORDER BY
    con = duckdb.connect()
    con.register("r", r)
    g = con.sql(f"SELECT {GROUP_SQL} AS g FROM r ORDER BY _rid").df().g
    return rec.assign(group=g.values)


def match_records(rec, cand):
    """Add species (candidate name) and how it matched; synonyms through GBIF backbone matches (cached)."""
    by_group = cand.groupby("group").species.apply(set).to_dict()
    rec["verbatim"] = rec.verbatimScientificName.map(lambda n: binomial(n) if n else None)
    rec["gbif_species"] = rec.species.replace("", None)
    keys = rec[["group", "gbif_species", "verbatim"]].drop_duplicates()
    keys = keys[keys.group.notna()]
    exact = [match_name([s, v], by_group.get(g, set()), {}) for g, s, v in keys.itertuples(index=False)]
    keys["cand"], keys["how"] = [e[0] for e in exact], [e[1] for e in exact]
    todo = keys[keys.cand.isna()]
    # candidate names never seen exactly in the records: their accepted name may be a record's species
    seen = set(keys.cand.dropna())
    unseen_cand = cand[~cand.species.isin(seen) & cand.group.isin(set(todo.group))]
    names = set(todo.verbatim.dropna()) | set(unseen_cand.species)
    log(f"names: {len(keys):,} name keys, {len(todo):,} without an exact match; {len(names):,} names to GBIF match")
    acc = accepted_names(sorted(names))
    rev = {}
    for c, g in zip(unseen_cand.species, unseen_cand.group):
        a = acc.get(c)
        if a and a != c:
            rev.setdefault((g, a), set()).add(c)
    for i, (g, s, v) in zip(todo.index, todo[["group", "gbif_species", "verbatim"]].itertuples(index=False)):
        c, how = match_name([v], by_group.get(g, set()), acc)
        if c is None and len(rev.get((g, s), ())) == 1:
            c, how = next(iter(rev[(g, s)])), "synonym"
        keys.loc[i, ["cand", "how"]] = c, how
    out = rec.merge(keys, on=["group", "gbif_species", "verbatim"], how="left")
    return out


def name_report(m):
    m = m.assign(
        status=np.select(
            [m.group.isna(), m.cand.notna() & (m.how == "exact"), m.cand.notna()],
            ["outside the 24 groups", "exact", "synonym"],
            "not a candidate",
        )
    )
    t = m[m.group.notna()].pivot_table(index="group", columns="status", values="gbifID", aggfunc="size", fill_value=0)
    t.loc["All"] = t.sum()
    t["records"] = t.sum(axis=1)
    t["pct_kept"] = (100 * (t.get("exact", 0) + t.get("synonym", 0)) / t.records).round(1)
    t = t.reset_index()
    log(f"records outside the 24 groups: {int(m.group.isna().sum()):,}")
    return t


def main():
    rec = pd.read_parquet(DATA / "records.parquet")
    log(f"records: {len(rec):,}")
    rec = with_groups(rec)
    m = match_records(rec, candidates())
    names = name_report(m)
    names.to_csv(RESULTS / "names.csv", index=False)
    log("\n" + names.to_string(index=False))

    ph = pd.read_parquet(DATA / "photos.parquet")
    first = ph[ph.position == 0][["gbifID", "identifier", "open_url", "license", "rightsHolder"]]
    k = m[m.cand.notna()].merge(first, on="gbifID", how="left")
    k = k.rename(columns={"species": "gbif_species_col", "cand": "species", "recordedBy": "observer"})
    k["state"] = k.stateProvince.replace("", "(none)")
    k["split"] = k.observer.map(observer_split)
    k["photo_id"] = pd.to_numeric(k.open_url.str.extract(r"/photos/(\d+)/")[0], errors="coerce").astype("Int64")
    k["url"] = k.open_url
    pilot = set(pd.read_csv(PILOT, usecols=["id"]).id)
    log(
        f"matched {len(k):,}; first photo in the open-data bucket {int(k.url.notna().sum()):,}; "
        f"pilot observations left out {int(k.obs_id.isin(pilot).sum()):,}"
    )
    k = k[k.url.notna() & ~k.obs_id.isin(pilot)].reset_index(drop=True)
    keep = [
        "gbifID", "obs_id", "group", "species", "how", "genus", "observer", "identifiedBy", "eventDate",
        "decimalLatitude", "decimalLongitude", "state", "split", "photo_id", "url", "license", "rightsHolder",
        "taxonKey", "speciesKey", "acceptedTaxonKey",
    ]  # fmt: skip
    k = k[keep]
    atomic_parquet(k, DATA / "matched.parquet")
    log(
        f"split: {k.split.value_counts().to_dict()}; observers {k.observer.nunique():,}, "
        f"test observers {k[k.split == 'test'].observer.nunique():,}"
    )

    train = k[k.split == "train"]
    corpus = sample_capped(train, cap=CAP, by="species", observer="observer", state="state", seed=0)
    atomic_parquet(corpus.reset_index(drop=True), DATA / "corpus.parquet")
    test = k[k.split == "test"]
    t1 = test.sample(frac=1, random_state=0).groupby("group").head(T1_PER_GROUP).sort_index()
    atomic_parquet(t1.reset_index(drop=True), DATA / "t1_sample.parquet")

    cand = candidates()
    c = cand.groupby("group").size().rename("candidates").to_frame()
    c["train_species"] = train.groupby("group").species.nunique()
    c["corpus_species"] = corpus.groupby("group").species.nunique()
    c["corpus_obs"] = corpus.groupby("group").size()
    c["corpus_photos"] = c.corpus_obs  # first photo only
    c["corpus_observers"] = corpus.groupby("group").observer.nunique()
    c["species_with_cap"] = corpus.groupby("group").species.value_counts().ge(CAP).groupby("group").sum()
    c["test_obs"] = test.groupby("group").size()
    c["t1_sample"] = t1.groupby("group").size()
    c = c.fillna(0).astype(int)
    c.loc["All"] = c.sum()
    c.loc["All", "corpus_observers"] = corpus.observer.nunique()
    c["pct_species_covered"] = (100 * c.corpus_species / c.candidates).round(1)
    c = c.reset_index()
    c.to_csv(RESULTS / "corpus_counts.csv", index=False)
    log("\n" + c.to_string(index=False))
    n = len(corpus) + len(t1)
    log(f"licences in corpus: {corpus.license.value_counts().to_dict()}")
    log(f"to embed: {n:,} photos; estimate {n * SECS_PER_1000 / 1000 / 3600:.1f} h at {SECS_PER_1000} s per 1,000")


if __name__ == "__main__":
    main()
