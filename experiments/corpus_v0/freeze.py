"""Queue check, part B: freeze the shortlists of the queue sample (the pre-registration of a prospective test).

Per group, from scores/<group>.npz (evaluate.py, method chosen on validation) and results/gate.csv:
- calibration with pipeline.shortlist.calibrate on all of the group's T1 rows (split conformal, target 90%), saved
  with pipeline.shortlist.make_calibration (its version is a checksum of the entries); groups with fewer than
  100 T1 rows get no entry;
- per queue-sample observation, pipeline.shortlist.shortlist(): the species set and the genus set; the band is the
  group's gate verdict applied to it: "Quick to confirm" (species set of 1 to 3 names in a Quick group),
  "Genus first" (a genus set in a Quick or Genus-first group), else "For an expert" (no names shown).
  The top 10 names, the 90% species set and the genus set are kept for every row, shown or not, for scoring later.

Outputs: data/corpus_v0/frozen_<drawn>.parquet and calibration_<drawn>.json (local only), results/frozen.csv
(counts per group and band, and the file's SHA-256). A frozen file is never overwritten: a rerun only prints
its checksum. Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/freeze.py
"""

import hashlib
import json

import numpy as np
import pandas as pd
from evaluate import SCORES
from lib import DATA, RESULTS, atomic_parquet, log
from logic import EXPERT, GENUS_FIRST, QUICK

MODEL = "bioclip-2.5-vith14-filled+corpus_v0"
TOP = 10
MAX_SET = 50  # longest 90% set kept in the file


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def joined(names, probs=None):
    if probs is None:
        return "|".join(names)
    return "|".join(names), "|".join(f"{p:.4f}" for p in probs)


def band(verdict, res):
    if verdict == QUICK and res["band"] == "Quick to confirm":
        return QUICK
    if verdict in (QUICK, GENUS_FIRST) and res["genera"]:
        return GENUS_FIRST
    return EXPERT


def main():
    from pipeline import shortlist as sl

    qs = pd.read_parquet(DATA / "queue_sample.parquet")
    drawn = qs.drawn.iloc[0]
    out = DATA / f"frozen_{drawn}.parquet"
    if out.exists():
        log(f"{out.name} exists (frozen); SHA-256 {sha256(out)}; not written again")
        return
    gate = pd.read_csv(RESULTS / "gate.csv").set_index("group")
    corpus_version = sha256(DATA / "corpus.parquet")[:12]
    entries, scores = {}, {}
    for f in sorted(SCORES.glob("*.npz")):
        z = np.load(f)
        group = str(z["group"])
        scores[group] = z
        if len(z["t1_true"]) >= sl.MIN_N:
            e = sl.calibrate(
                z["t1_probs"].astype(np.float64),
                list(z["names"]),
                list(z["t1_true"]),
                model_id=f"{MODEL}:{z['method']}",
                corpus_version=corpus_version,
                target=0.9,
                date=drawn,
            )
            verdict = gate.verdict.get(group)
            e.update(passed=verdict == QUICK, reason=f"gate: {verdict}")
            entries[group] = e
    cal = sl.make_calibration(entries)
    cal_path = DATA / f"calibration_{drawn}.json"
    cal_path.write_text(json.dumps(cal, indent=1, sort_keys=True))
    rows = []
    for group, g in qs.groupby("group"):
        z = scores.get(group)
        if z is None:
            continue
        names, probs, obs = list(z["names"]), z["q_probs"].astype(np.float64), list(z["q_obs"])
        entry, verdict = entries.get(group), gate.verdict.get(group, "not enough data")
        pos = {o: i for i, o in enumerate(obs)}
        for r in g.itertuples():
            if r.obs_id not in pos:
                continue  # photo could not be embedded
            p = probs[pos[r.obs_id]]
            res = sl.shortlist(p, names, entry)
            order = np.argsort(-p, kind="stable")
            top_n, top_p = joined([names[i] for i in order[:TOP]], p[order[:TOP]])
            set90 = sl.prediction_set(p, threshold=entry["threshold"]) if entry else []
            gen, gp = sl.genus_probs(p, names)
            gset = sl.prediction_set(gp, threshold=entry["genus_threshold"]) if entry else []
            rows.append(
                {
                    "obs_id": r.obs_id,
                    "group": group,
                    "created_at": r.created_at,
                    "taxon_id": r.taxon_id,
                    "taxon_name": r.taxon_name,
                    "taxon_rank": r.taxon_rank,
                    "community_taxon_id": r.community_taxon_id,
                    "photo_id": r.photo_id,
                    "group_verdict": verdict,
                    "band": band(verdict, res),
                    "shown_species": joined(res["species"] if band(verdict, res) == QUICK else []),
                    "shown_genera": joined(res["genera"] if band(verdict, res) != EXPERT else []),
                    "top_names": top_n,
                    "top_probs": top_p,
                    "set90": joined([names[i] for i in set90[:MAX_SET]]),
                    "set90_size": len(set90),
                    "genus_set90": joined([gen[i] for i in gset[:MAX_SET]]),
                    "method": str(z["method"]),
                    "model": f"{MODEL}:{z['method']}",
                    "corpus_version": corpus_version,
                    "calibration_version": cal["calibration_version"],
                    "drawn": drawn,
                }
            )
    df = pd.DataFrame(rows)
    atomic_parquet(df, out)
    digest = sha256(out)
    counts = df.pivot_table(index="group", columns="band", values="obs_id", aggfunc="size", fill_value=0)
    counts["rows"] = counts.sum(axis=1)
    counts = counts.join(df.groupby("group").group_verdict.first())
    counts.loc["All"] = counts.drop(columns="group_verdict").sum().tolist() + [""]
    counts = counts.reset_index()
    counts["file"], counts["sha256"] = out.name, digest
    counts.to_csv(RESULTS / "frozen.csv", index=False)
    log(f"{out.name}: {len(df):,} rows; SHA-256 {digest}; calibration {cal['calibration_version']}")
    log("\n" + counts.drop(columns=["file", "sha256"]).to_string(index=False))


if __name__ == "__main__":
    main()
