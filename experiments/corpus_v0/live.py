"""The live shortlist set for the experimental page (contract: docs/shortlist_data.md).

  live.py draw    the current India needs-ID queue for the groups that passed the gate (results/gate.csv: "Quick to
                  confirm" or "Genus first"), same window and filters as queue_sample.py (created in the last 120
                  days, named to a candidate species or a genus with candidates, open-licence first photo), up to
                  1,000 per group; never an id of a frozen test (frozen_*.parquet) or of the pilot; research-grade
                  rows dropped. State: live_state.json (saved after every request; a rerun sends no requests once
                  complete). Output: data/corpus_v0/live_sample.parquet (coordinates kept here only, for the state).
  (then photos.py, embed_v0.py and evaluate.py, which writes l_probs into scores/<group>.npz)
  live.py build   shortlists with the frozen calibration (calibration_<drawn>.json, version ce7c9b55be8e) and the best
                  method per group; band from the group's verdict (quick: up to 3 species; genus: up to 5 genera;
                  expert rows are not published); LGD state from the coordinates (pipeline.places, the pipeline's
                  district file), null when obscured or absent; order by pipeline.shortlist priority, then oldest
                  first. Writes data/shortlist/<run>/latest.json and g/<key>.json (pages g/<key>.<n>.json when a
                  group passes MAX_BYTES), compact and deterministic, and shown.parquet (local only: every
                  published id with its full shortlist, for recheck.py --shown).
  live.py prune <run> <date>   after recheck.py --shown <run> on <date>: a copy of the run without the observations
                  now research grade, casual or gone, as run <date> (latest.json gives sample, checked, removed).
Nothing is posted anywhere; publish_live.py (run only when the owner agrees) copies the JSON files to R2.
Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/live.py draw|build|prune
"""

import hashlib
import json
import sys
import time

import duckdb
import numpy as np
import pandas as pd
from evaluate import SCORES
from freeze import TOP, band, joined
from lib import DATA, RESULTS, ROOT, atomic_parquet, atomic_write_json, log
from logic import (
    EXPERT,
    GENUS_FIRST,
    QUICK,
    compact,
    done_ids,
    live_order,
    page_name,
    paginate,
    public_row,
)
from queue_sample import PILOT, draw, row

STATE = DATA / "live_state.json"
SAMPLE = DATA / "live_sample.parquet"
OUT = ROOT / "data" / "shortlist"
PER_GROUP, MAX_PAGES = 1000, 12
MAX_BYTES = 300_000
CALIBRATION = "ce7c9b55be8e"
BAND_KEY = {QUICK: "quick", GENUS_FIRST: "genus", EXPERT: "expert"}
MODEL_NAME = "BioCLIP 2.5 + corpus v0 classifier"


def live_row(o, group, cand, how):
    """queue_sample's row plus what the page needs (photo attribution, place text) and the location for the state."""
    ph, loc = (o.get("photos") or [{}])[0], o.get("location") or ""
    lat, lon = (float(x) for x in loc.split(",")) if "," in loc else (None, None)
    return {
        **row(o, group, cand, how),
        "photo_api_url": ph.get("url"),
        "attribution": ph.get("attribution"),
        "place_guess": o.get("place_guess"),
        "obscured": bool(o.get("obscured"))
        or o.get("geoprivacy") in ("obscured", "private")
        or o.get("taxon_geoprivacy") in ("obscured", "private"),
        "lat": lat,
        "lon": lon,
        "quality_grade": o.get("quality_grade"),
    }


def passed_groups():
    g = pd.read_csv(RESULTS / "gate.csv")
    return g[g.verdict.isin([QUICK, GENUS_FIRST])].set_index("group")


def do_draw():
    exclude = set(pd.read_csv(PILOT, usecols=["id"]).id)
    for f in DATA.glob("frozen_*.parquet"):
        exclude |= set(pd.read_parquet(f, columns=["obs_id"]).obs_id)
    state = draw(STATE, sorted(passed_groups().index), PER_GROUP, MAX_PAGES, exclude, make_row=live_row)
    if "finished" not in state:  # fixed once, so the files built from this draw are always the same bytes
        state["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        atomic_write_json(STATE, state)
    rows = [r for g in state["groups"].values() for r in list(g["rows"].values())[:PER_GROUP]]
    df = pd.DataFrame(rows).drop_duplicates("obs_id")
    df = df[(df.quality_grade == "needs_id") & ~df.obs_id.isin(exclude)]
    df["drawn"] = state["drawn"]
    atomic_parquet(df.sort_values(["group", "obs_id"]).reset_index(drop=True), SAMPLE)
    log(f"live sample: {len(df):,} rows; {df.groupby('group').size().to_dict()}")


def states(df):
    """LGD state code (text) per row from its coordinates; None when obscured or absent."""
    from pipeline import places

    con = duckdb.connect()
    con.register("pts", df.loc[~df.obscured & df.lat.notna(), ["lat", "lon"]].drop_duplicates())
    places.place_points(con, "pts", str(ROOT / "data" / "ref" / "LGD_Districts.parquet"))
    placed = con.sql("SELECT lat, lon, state_lgd FROM point_district").df()
    m = df.merge(placed, on=["lat", "lon"], how="left")
    return [None if o or pd.isna(s) else str(int(s)) for o, s in zip(m.obscured, m.state_lgd)]


def obs_view(r):
    """The fields public_row reads, from a live_sample row."""
    return {
        "id": int(r.obs_id), "observed_on": r.observed_on, "place_guess": r.place_guess, "obscured": r.obscured,
        "taxon": {"name": r.taxon_name, "rank": r.taxon_rank},
        "photos": [{"url": r.photo_api_url, "attribution": r.attribution, "license_code": r.licence}],
    }  # fmt: skip


def write_pages(out_dir, key, rows):
    """Write a group's rows, in order, as pages of at most MAX_BYTES (docs/shortlist_data.md). Returns the page count."""
    pages = paginate(rows, lambda rs: compact({"group": key, "rows": rs}), MAX_BYTES)
    for n, page in enumerate(pages, 1):
        body = {"group": key, "rows": page}
        if len(pages) > 1:
            body = {"group": key, "page": n, "pages": len(pages), "rows": page}
        (out_dir / "g" / page_name(key, n)).write_text(compact(body))
    return len(pages)


def group_rows(run_dir, group):
    """All rows of a group in a built run, in page order."""
    return [r for n in range(1, group.get("pages", 1) + 1)
            for r in json.loads((run_dir / "g" / page_name(group["key"], n)).read_text())["rows"]]


def do_prune():
    """A copy of the sample run without the observations a re-check found done (research grade, casual or gone), as a
    new run named by the check date. The sample run and its shown.parquet stay as they are: the measure uses them.
    Usage: live.py prune <sample run> <check date>   (after recheck.py --shown <sample run> on that date)"""
    run, checked = sys.argv[2], sys.argv[3]
    src, out_dir = OUT / run, OUT / checked
    latest = json.loads((src / "latest.json").read_text())
    answers = [json.loads(line) for line in (DATA / f"inat_recheck_shown_{run}_{checked}.jsonl").open()]
    rows = {g["key"]: group_rows(src, g) for g in latest["groups"]}
    done = done_ids(answers, [r["id"] for rs in rows.values() for r in rs])
    (out_dir / "g").mkdir(parents=True, exist_ok=True)
    for old in (out_dir / "g").glob("*.json"):
        old.unlink()  # a second prune on the same date writes the same files again
    for g in latest["groups"]:
        keep = [r for r in rows[g["key"]] if r["id"] not in done]
        g.update(rows=len(keep), pages=write_pages(out_dir, g["key"], keep))
    latest.update(run=checked, sample=run, checked=checked, removed=len(done), rows=sum(g["rows"] for g in latest["groups"]))
    (out_dir / "latest.json").write_text(compact(latest))
    log(f"run {checked}: {latest['rows']:,} rows; {len(done):,} done since {run} left out")


def do_build():
    from pipeline import shortlist as sl

    df = pd.read_parquet(SAMPLE)
    run = df.drawn.iloc[0]
    cal = json.loads((DATA / "calibration_2026-10-20.json").read_text())
    if cal["calibration_version"] != CALIBRATION:
        raise SystemExit(f"calibration {cal['calibration_version']} is not the frozen one ({CALIBRATION})")
    gates = passed_groups()
    df["state"] = states(df)
    out_dir = OUT / run
    (out_dir / "g").mkdir(parents=True, exist_ok=True)
    groups, shown, total = [], [], 0
    for group in sorted(df.group.unique()):
        z = np.load(SCORES / f"{sl.slug(group)}.npz")
        names, probs = list(z["names"]), z["l_probs"].astype(np.float64)
        pos = {int(o): i for i, o in enumerate(z["l_obs"])}
        entry, verdict = cal["groups"][group], gates.verdict[group]
        if entry["model_id"].split(":")[-1] != str(z["method"]):
            raise SystemExit(f"{group}: method {z['method']} is not the calibrated one ({entry['model_id']})")
        rows = []
        for r in df[df.group == group].itertuples():
            if int(r.obs_id) not in pos:
                continue  # no photo features
            p = probs[pos[int(r.obs_id)]]
            res = sl.shortlist(p, names, entry)
            b = BAND_KEY[band(verdict, res)]
            if b == "expert":
                continue
            pub = public_row(obs_view(r), b, res["species"], res["genera"], r.state)
            rows.append({**pub, "created_at": r.created_at})
            order = np.argsort(-p, kind="stable")
            top_n, top_p = joined([names[i] for i in order[:TOP]], p[order[:TOP]])
            shown.append(
                {
                    "obs_id": int(r.obs_id), "group": group, "band": b, "taxon_id": r.taxon_id,
                    "created_at": r.created_at, "shown_species": joined(pub["names"]),
                    "shown_genera": joined(pub["genera"]), "top_names": top_n, "top_probs": top_p,
                    "set90": joined([names[i] for i in sl.prediction_set(p, threshold=entry["threshold"])][:50]),
                    "method": str(z["method"]), "calibration_version": CALIBRATION, "drawn": run,
                }
            )  # fmt: skip
        rows = [{k: v for k, v in r.items() if k != "created_at"} for r in live_order(rows)]
        key = sl.slug(group)
        t1 = gates.loc[group]
        groups.append(
            {
                "key": key, "name": group, "verdict": verdict, "rows": len(rows), "pages": write_pages(out_dir, key, rows),
                "t1": {"n": int(t1.n), "top1": float(t1.top1), "cov90": float(t1.sp_cov if verdict == QUICK else t1.g_cov)},
            }
        )  # fmt: skip
        total += len(rows)
    built = json.loads(STATE.read_text())["finished"]
    latest = {
        "run": run, "built": built, "model": MODEL_NAME, "corpus": "v0", "calibration": CALIBRATION,
        "rows": total, "groups": groups,
    }  # fmt: skip
    (out_dir / "latest.json").write_text(compact(latest))
    sh = pd.DataFrame(shown).sort_values(["group", "obs_id"]).reset_index(drop=True)
    atomic_parquet(sh, out_dir / "shown.parquet")
    digest = hashlib.sha256((out_dir / "shown.parquet").read_bytes()).hexdigest()
    (out_dir / "shown.sha256").write_text(digest + "\n")
    log(f"run {run}: {total:,} rows in {len(groups)} groups; shown.parquet SHA-256 {digest}")
    for f in sorted((out_dir / "g").glob("*.json")):
        log(f"  {f.name}: {f.stat().st_size / 1000:.1f} KB")


if __name__ == "__main__":
    {"draw": do_draw, "build": do_build, "prune": do_prune}[sys.argv[1]]()
