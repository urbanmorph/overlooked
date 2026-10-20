"""Queue check, part A: grow T1 so every group has at least 100 qualifying rows (README "Queue check").

The sample order is build_sets.py's: test observers only, shuffled once (random_state 0), first N per group. So
the first 300 per group are the T1 sample already drawn, and growing it only adds rows. Per round, each group below
100 qualifying rows gets enough more to reach 100 at its rate so far (logic.next_sample_size), up to 4,000 sampled
or the end of its test pool. The iNaturalist answers go to the same cache as T1 (inat_t1.jsonl), so a stopped run
continues and a rerun sends no requests. At the end t1_sample.parquet holds the grown sample and waited.main()
rebuilds t1.parquet and results/t1_waited.csv from the cache.

Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/grow_t1.py
"""

import pandas as pd
import waited
from build_sets import T1_PER_GROUP
from lib import DATA, atomic_parquet, log
from logic import next_sample_size

TARGET, CAP = 100, 4000


def ordered_test():
    m = pd.read_parquet(DATA / "matched.parquet")
    t = m[m.split == "test"].sample(frac=1, random_state=0)
    t["order"] = t.groupby("group").cumcount()
    return t


def main():
    t = ordered_test()
    pool = t.groupby("group").size()
    first = t[t.order < T1_PER_GROUP]
    old = pd.read_parquet(DATA / "t1_sample.parquet")
    if set(first.obs_id) != set(old[old.obs_id.isin(first.obs_id)].obs_id) or len(first) != len(old):
        raise SystemExit("the shuffled test order does not reproduce the T1 sample; stop")
    n = {g: min(T1_PER_GROUP, int(pool[g])) for g in pool.index}
    for rnd in range(1, 20):
        h = waited.history(t[t.order < t.group.map(n)].drop(columns="order"))
        q = h[h.why == "qualifies"].groupby("group").size().reindex(pool.index, fill_value=0)
        new = {g: next_sample_size(n[g], int(q[g]), int(pool[g]), TARGET, CAP) for g in pool.index}
        grow = {g: (n[g], new[g], int(q[g])) for g in pool.index if new[g] > n[g]}
        log(f"round {rnd}: " + ("; ".join(f"{g} {a}->{b} ({c} qualify)" for g, (a, b, c) in grow.items()) or "done"))
        if not grow:
            break
        n = new
    s = t[t.order < t.group.map(n)].drop(columns="order")
    atomic_parquet(s.sort_index(), DATA / "t1_sample.parquet")
    log(f"T1 sample: {len(s):,} observations")
    waited.main()


if __name__ == "__main__":
    main()
