"""Georeferencing test: run the place-name matcher on GBIF India records and measure it.

1. Test: records with good coordinates (uncertainty <= 1 km, no geospatial issue) and locality text. The
   coordinates are hidden from the matcher; the true district is where pipeline.places puts the point.
2. To fix: query L records (no coordinates, flagged, or uncertain by more than 25 km).

Each sample: about 20,000 records, stratified by dataset (every record of a small dataset; the same cap for
the large ones), ordered within a dataset by a hash of gbifid, so the sample is the same on every run.

A district name can give a district set (the district and the districts carved from it after the record's
year, from ref/district_splits.csv). The answer is right when the true district is in the set; "single" counts
only answers of one district; "first" counts the first district of the answer (the parent) alone. A set keeps the
confidence of the name match: the tiers say how sure the place is in the answer, not how small the answer is.

Matching runs in chunks of 2,000 records; each chunk is saved to data/georef/matches/<version>/ when done,
so a stopped run continues with the next chunk. The version is a hash of the matcher, the gazetteer and the
alias and split tables: a second run with the same inputs reads the saved chunks and does no new matching.

Results (small CSVs) go to experiments/georef/results/.

Usage: .venv/bin/python experiments/georef/evaluate.py [download key] [--n 20000]
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import duckdb
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from matcher import FIELDS, Entry, Gazetteer, load_splits, match

from pipeline import districts, ledger, places, unlocated, util
from pipeline.unresolved import read_tsv

DATA = ROOT / "data" / "georef"
GAZ = DATA / "gazetteer.parquet"
SPLITS = HERE / "ref" / "district_splits.csv"
RESULTS = HERE / "results"
CHUNK = 2000
TEXT_CAP = 5
TEXT_KEY = " || '|' || ".join(f"coalesce({f}, '')" for f in FIELDS)
# The query L cube of snapshot 2026-10 (doi:10.15468/dl.tnbsse): records per dataset, to weight the sample.
QUERY_L_CUBE = "0033984-260928105237408"

KINDS = {"PRESERVED_SPECIMEN": "specimen", "MATERIAL_SAMPLE": "specimen", "HUMAN_OBSERVATION": "observation",
         "OBSERVATION": "observation", "MACHINE_OBSERVATION": "observation",
         "MATERIAL_CITATION": "material citation"}
KIND_SQL = "CASE basisofrecord " + " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in KINDS.items()) + " ELSE 'other' END"


def kind_of(basis):
    return KINDS.get(basis, "other")


def outcome(pred, truth):
    """pred: the district set of the answer (one district, or a parent with the districts carved from it)."""
    if truth is None:
        return "no truth"
    if not pred:
        return "none"
    return "right" if truth in pred else "wrong"


def caps(counts, total):
    """Records to take per dataset: all of a small dataset, the same cap for the others, summing to total
    (or to everything there is)."""
    if sum(counts.values()) <= total:
        return dict(counts)
    lo, hi = 0, max(counts.values())
    while lo < hi:  # largest cap whose sum stays within total
        mid = (lo + hi + 1) // 2
        if sum(min(c, mid) for c in counts.values()) <= total:
            lo = mid
        else:
            hi = mid - 1
    got = {k: min(c, lo) for k, c in counts.items()}
    left = total - sum(got.values())
    for k in sorted((k for k, c in counts.items() if c > lo), key=lambda k: -counts[k])[:left]:
        got[k] += 1
    return got


TYPES = {"gbifid": "BIGINT", "datasetkey": "VARCHAR", "basisofrecord": "VARCHAR", "sample": "VARCHAR",
         "problem": "VARCHAR", "decimallatitude": "DOUBLE", "decimallongitude": "DOUBLE",
         "coordinateuncertaintyinmeters": "DOUBLE", "year": "INTEGER", **{f: "VARCHAR" for f in FIELDS}}


def load(con, key, n):
    read_tsv(con, "recs", ledger.unpack(key), TYPES)
    # Test: at most TEXT_CAP records with the same text, so one checklist site published as many datasets
    # (e.g. 14 bird-survey datasets at one park) does not fill the sample.
    con.sql(f"""DELETE FROM recs WHERE sample = 'test' AND gbifid IN (
                  SELECT gbifid FROM (SELECT gbifid, row_number() OVER (PARTITION BY {TEXT_KEY}
                                                                         ORDER BY md5(gbifid::VARCHAR)) AS rn
                                      FROM recs WHERE sample = 'test') WHERE rn > {TEXT_CAP})""")
    util.log(con.sql("SELECT sample, count(*) FROM recs GROUP BY 1 ORDER BY 1").fetchall())
    for s in ("test", "fix"):
        counts = dict(con.sql(f"SELECT datasetkey, count(*) FROM recs WHERE sample = '{s}' GROUP BY 1").fetchall())
        c = caps(counts, n)
        con.execute(f"CREATE OR REPLACE TEMP TABLE cap_{s} AS SELECT unnest($1) AS datasetkey, unnest($2) AS cap",
                    [list(c), list(c.values())])
    con.sql(f"""
        CREATE OR REPLACE TABLE smp AS
        WITH ranked AS (
            SELECT r.*, {KIND_SQL} AS kind,
                   row_number() OVER (PARTITION BY sample, datasetkey ORDER BY md5(gbifid::VARCHAR)) AS rn
            FROM recs r)
        SELECT r.* EXCLUDE (rn) FROM ranked r
        JOIN (SELECT 'test' AS sample, * FROM cap_test UNION ALL SELECT 'fix', * FROM cap_fix) c
          USING (sample, datasetkey)
        WHERE r.rn <= c.cap
    """)
    con.sql("CREATE OR REPLACE TEMP VIEW pts AS SELECT decimallatitude AS lat, decimallongitude AS lon FROM smp WHERE sample = 'test'")
    places.place_points(con, "pts", str(districts.PATH))
    con.sql("""CREATE OR REPLACE TABLE truth AS
               SELECT s.gbifid, p.dist_lgd AS true_dist, p.state_lgd AS true_state, p.how
               FROM smp s JOIN point_district p ON p.lat = s.decimallatitude AND p.lon = s.decimallongitude
               WHERE s.sample = 'test'""")


def http():
    h = requests.Session()
    h.headers["User-Agent"] = "overlooked-india georef test (+https://github.com/urbanmorph/overlooked)"
    return h


def version():
    h = hashlib.sha256()
    for f in (HERE / "matcher.py", GAZ, HERE / "ref" / "district_aliases.csv", SPLITS,
              ROOT / "pipeline" / "ref" / "state_names.csv"):
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


def check_splits(con):
    """Every split row names LGD districts by their code, name and state (the parent may be an old district
    without a code)."""
    bad = con.sql(f"""SELECT s.parent, s.child FROM read_csv('{SPLITS}', header=true, all_varchar=true) s
                      WHERE (s.parent_lgd IS NOT NULL AND NOT EXISTS (
                                SELECT 1 FROM '{districts.PATH}' d WHERE d.dist_lgd = s.parent_lgd::INTEGER
                                AND d.dtname = s.parent AND d.state_lgd = s.parent_state_lgd::INTEGER))
                         OR NOT EXISTS (SELECT 1 FROM '{districts.PATH}' d WHERE d.dist_lgd = s.child_lgd::INTEGER
                                        AND d.dtname = s.child AND d.state_lgd = s.child_state_lgd::INTEGER)""").fetchall()
    if bad:
        sys.exit(f"splits name districts that LGD does not have: {bad}")


def run_matches(con):
    check_splits(con)
    out = DATA / "matches" / version()
    out.mkdir(parents=True, exist_ok=True)
    gaz = None
    for s in ("test", "fix"):
        rows = con.sql(f"SELECT gbifid, year, {', '.join(FIELDS)} FROM smp WHERE sample = '{s}' ORDER BY gbifid").fetchall()
        chunks = range(0, len(rows), CHUNK)
        for i in chunks:
            f = out / f"{s}_{i // CHUNK:04d}.parquet"
            if f.exists():
                continue
            if gaz is None:
                t = time.time()
                gaz = Gazetteer([Entry(*r) for r in duckdb.sql(
                    f"SELECT kind, name, state_lgd, dist_lgd, lat, lon, radius_km FROM '{GAZ}'").fetchall()],
                    load_splits(SPLITS))
                util.log(f"gazetteer loaded in {time.time() - t:.0f} s")
            t = time.time()
            res = []
            for r in rows[i:i + CHUNK]:
                m = match({"year": r[1], **dict(zip(FIELDS, r[2:]))}, gaz)
                res.append((r[0], m.dist_lgd, m.districts, len(m.districts), m.state_lgd, m.lat, m.lon, m.radius_km,
                            m.kind, m.confidence, len(m.candidates), json.dumps(m.candidates), m.matched))
            con.execute("""CREATE OR REPLACE TEMP TABLE chunk (gbifid BIGINT, dist_lgd INTEGER, districts INTEGER[],
                           set_size INTEGER, state_lgd INTEGER, lat DOUBLE, lon DOUBLE, radius_km DOUBLE,
                           place_kind VARCHAR, confidence VARCHAR, n_candidates INTEGER, candidates VARCHAR,
                           matched VARCHAR)""")
            con.executemany("INSERT INTO chunk VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", res)
            part = f.with_name(f.name + ".part")
            con.sql(f"COPY chunk TO '{part}' (FORMAT parquet)")
            part.replace(f)
            util.log(f"{s}: chunk {i // CHUNK + 1} of {len(chunks)} matched in {time.time() - t:.1f} s")
    con.sql(f"CREATE OR REPLACE TABLE m AS SELECT * FROM '{out}/*.parquet'")
    util.log(f"matches: {out}")


def metrics(con):
    con.sql("""
        CREATE OR REPLACE TABLE ev AS
        SELECT s.gbifid, CASE WHEN hash(s.gbifid) % 2 = 0 THEN 'dev' ELSE 'holdout' END AS half,
               s.datasetkey, s.kind, s.basisofrecord, s.year, t.true_dist, t.true_state, t.how, m.*  EXCLUDE (gbifid),
               s.decimallatitude AS true_lat, s.decimallongitude AS true_lon,
               CASE WHEN t.true_dist IS NULL THEN 'no truth' WHEN m.dist_lgd IS NULL THEN 'none'
                    WHEN list_contains(m.districts, t.true_dist) THEN 'right' ELSE 'wrong' END AS district,
               CASE WHEN t.true_state IS NULL THEN 'no truth' WHEN m.state_lgd IS NULL THEN 'none'
                    WHEN m.state_lgd = t.true_state THEN 'right' ELSE 'wrong' END AS state,
               CASE WHEN m.lat IS NOT NULL THEN 2 * 6371 * asin(sqrt(power(sin(radians(s.decimallatitude - m.lat) / 2), 2)
                    + cos(radians(m.lat)) * cos(radians(s.decimallatitude))
                    * power(sin(radians(s.decimallongitude - m.lon) / 2), 2))) END AS err_km
        FROM smp s JOIN truth t USING (gbifid) JOIN m USING (gbifid)
    """)
    agg = """count(*) AS n,
             count(*) FILTER (district <> 'no truth') AS n_with_district,
             count(*) FILTER (district = 'right') AS district_right,
             count(*) FILTER (district = 'wrong') AS district_wrong,
             count(*) FILTER (district = 'none') AS district_none,
             round(100.0 * count(*) FILTER (district = 'right') / nullif(count(*) FILTER (district <> 'no truth'), 0), 1) AS pct_right,
             round(100.0 * count(*) FILTER (district = 'wrong') / nullif(count(*) FILTER (district <> 'no truth'), 0), 1) AS pct_wrong,
             round(100.0 * count(*) FILTER (district = 'none') / nullif(count(*) FILTER (district <> 'no truth'), 0), 1) AS pct_none,
             round(100.0 * count(*) FILTER (district = 'right') / nullif(count(*) FILTER (district IN ('right', 'wrong')), 0), 1) AS precision_pct,
             round(100.0 * count(*) FILTER (district = 'right' AND dist_lgd = true_dist) / nullif(count(*) FILTER (district <> 'no truth'), 0), 1) AS pct_right_first,
             count(*) FILTER (district = 'right' AND set_size = 1) AS right_single,
             round(100.0 * count(*) FILTER (district = 'right' AND set_size = 1) / nullif(count(*) FILTER (district <> 'no truth'), 0), 1) AS pct_right_single,
             count(*) FILTER (set_size > 1) AS n_set,
             round(avg(set_size) FILTER (set_size > 0), 2) AS mean_set_size,
             median(set_size) FILTER (set_size > 0) AS median_set_size,
             max(set_size) AS max_set_size,
             count(*) FILTER (state = 'right') AS state_right,
             count(*) FILTER (state = 'wrong') AS state_wrong,
             round(100.0 * count(*) FILTER (state = 'right') / nullif(count(*) FILTER (state <> 'no truth'), 0), 1) AS pct_state_right,
             count(err_km) AS n_point,
             round(median(err_km), 1) AS median_km,
             round(quantile_cont(err_km, 0.9), 1) AS p90_km,
             round(100.0 * count(*) FILTER (err_km <= radius_km) / nullif(count(err_km), 0), 1) AS pct_within_radius"""
    RESULTS.mkdir(exist_ok=True)
    titles = unlocated.dataset_titles(http(), [r[0] for r in con.sql(
        "SELECT datasetkey FROM ev GROUP BY 1 ORDER BY count(*) DESC LIMIT 25").fetchall()])
    con.execute("CREATE OR REPLACE TEMP TABLE titles AS SELECT unnest($1) AS datasetkey, unnest($2) AS title",
                [list(titles), [t or "" for t in titles.values()]])
    tables = {
        "test_overall": f"SELECT 'all' AS grp, {agg} FROM ev UNION ALL SELECT half, {agg} FROM ev GROUP BY half",
        "test_by_kind_holdout": f"SELECT kind AS grp, {agg} FROM ev WHERE half = 'holdout' GROUP BY 1 ORDER BY n DESC",
        "test_by_confidence_holdout": f"SELECT coalesce(confidence, 'no answer') AS grp, {agg} FROM ev WHERE half = 'holdout' GROUP BY 1 ORDER BY 1",
        "test_by_kind": f"SELECT kind AS grp, {agg} FROM ev GROUP BY 1 ORDER BY n DESC",
        "test_by_confidence": f"SELECT coalesce(confidence, 'no answer') AS grp, {agg} FROM ev GROUP BY 1 ORDER BY 1",
        "test_by_confidence_set": f"""SELECT coalesce(confidence, 'no answer') || CASE WHEN set_size > 1 THEN ' / set' WHEN set_size = 1 THEN ' / single' ELSE '' END AS grp,
                                      {agg} FROM ev GROUP BY 1 ORDER BY 1""",
        "test_by_place_kind": f"SELECT coalesce(place_kind, 'no point') AS grp, {agg} FROM ev GROUP BY 1 ORDER BY n DESC",
        "test_by_kind_confidence": f"SELECT kind || ' / ' || coalesce(confidence, 'no answer') AS grp, {agg} FROM ev GROUP BY 1 ORDER BY 1",
        "test_by_dataset": f"""SELECT e.datasetkey AS grp, any_value(t.title) AS title, any_value(e.kind) AS kind, {agg}
                               FROM ev e JOIN titles t USING (datasetkey) GROUP BY 1 ORDER BY n DESC""",
    }
    for name, sql in tables.items():
        con.sql(f"COPY ({sql}) TO '{RESULTS / (name + '.csv')}' (HEADER)")
    # Failures: why a district was wrong or missing. "Carved from the answer": the true district was split from
    # the proposed one (at any time), but not after the record's year, or the answer came from a village.
    tree = Gazetteer([], load_splits(SPLITS))
    pairs = [(p, c) for p in tree.children for c in tree.district_set([p])[1:]]
    con.execute("CREATE OR REPLACE TEMP TABLE carved AS SELECT unnest($1) AS parent, unnest($2) AS child",
                [[p for p, _ in pairs], [c for _, c in pairs]])
    con.sql("""
        CREATE OR REPLACE TABLE fail AS
        SELECT e.*, CASE
            WHEN district = 'none' AND n_candidates > 1 THEN 'none: name in several districts'
            WHEN district = 'none' AND state = 'right' THEN 'none: state only'
            WHEN district = 'none' THEN 'none: no place name found'
            WHEN district = 'wrong' AND (e.dist_lgd, e.true_dist) IN (SELECT (parent, child) FROM carved)
                THEN 'wrong: true district carved from the answer'
            WHEN district = 'wrong' AND state = 'wrong' THEN 'wrong: same name in another state'
            WHEN district = 'wrong' AND ST_Intersects(p.geometry, t.geometry) THEN 'wrong: neighbouring district'
            ELSE 'wrong: other district in the same state'
            END AS reason
        FROM ev e LEFT JOIN districts p ON p.dist_lgd = e.dist_lgd LEFT JOIN districts t ON t.dist_lgd = e.true_dist
        WHERE district IN ('none', 'wrong')
    """)
    con.sql(f"""COPY (SELECT reason, kind, count(*) AS n FROM fail GROUP BY ALL ORDER BY kind, n DESC)
                TO '{RESULTS / 'test_failures.csv'}' (HEADER)""")
    con.sql(f"""COPY (SELECT reason, f.kind, s.locality, s.verbatimlocality, s.county, s.stateprovince, f.matched,
                             f.dist_lgd AS proposed_dist, d1.dtname AS proposed, f.true_dist, d2.dtname AS truth,
                             round(f.err_km, 1) AS err_km, f.confidence, f.gbifid
                      FROM (SELECT *, row_number() OVER (PARTITION BY reason, kind ORDER BY md5(gbifid::VARCHAR)) AS rn FROM fail) f
                      JOIN smp s USING (gbifid)
                      LEFT JOIN districts d1 ON d1.dist_lgd = f.dist_lgd LEFT JOIN districts d2 ON d2.dist_lgd = f.true_dist
                      WHERE rn <= 8 ORDER BY reason, kind)
                TO '{RESULTS / 'test_failure_examples.csv'}' (HEADER)""")


def fix_report(con):
    cube = ledger.unpack(QUERY_L_CUBE)
    con.sql(f"""CREATE OR REPLACE TABLE pop AS SELECT datasetkey, sum(n_records::BIGINT) AS pop
                FROM read_csv('{cube}', delim='\t', header=true, quote='', all_varchar=true) GROUP BY 1""")
    # Today's rule (query L): a state only from the stateprovince text.
    names = unlocated.load_state_names()
    texts = [r[0] for r in con.sql("SELECT DISTINCT stateprovince FROM smp WHERE sample = 'fix' AND stateprovince IS NOT NULL").fetchall()]
    con.execute("CREATE OR REPLACE TEMP TABLE sp_state AS SELECT unnest($1) AS stateprovince, unnest($2)::INTEGER AS sp_state",
                [texts, [unlocated.state_of(t, names) for t in texts]])
    has_text = " OR ".join(f"{f} IS NOT NULL" for f in FIELDS)
    con.sql(f"""
        CREATE OR REPLACE TABLE fx AS
        SELECT s.gbifid, s.datasetkey, s.kind, s.problem, ({has_text}) AS has_text, ({'locality IS NOT NULL OR verbatimlocality IS NOT NULL'}) AS has_locality,
               m.*  EXCLUDE (gbifid),
               CASE WHEN m.dist_lgd IS NOT NULL THEN 'district' WHEN m.state_lgd IS NOT NULL THEN 'state only' ELSE 'nothing' END AS placed,
               coalesce(p.pop, 0) / count(*) OVER (PARTITION BY s.datasetkey) AS w, sp.sp_state
        FROM smp s JOIN m USING (gbifid) LEFT JOIN pop p USING (datasetkey) LEFT JOIN sp_state sp USING (stateprovince)
        WHERE s.sample = 'fix'
    """)
    agg = """count(*) AS n,
             round(100.0 * count(*) FILTER (has_text) / count(*), 1) AS pct_any_text,
             count(*) FILTER (placed = 'district') AS district,
             count(*) FILTER (placed = 'state only') AS state_only,
             count(*) FILTER (placed = 'nothing') AS nothing,
             round(100.0 * count(*) FILTER (placed = 'district') / count(*), 1) AS pct_district,
             round(100.0 * count(*) FILTER (placed <> 'nothing') / count(*), 1) AS pct_state_or_better,
             round(100.0 * sum(w) FILTER (placed = 'district') / sum(w), 1) AS wpct_district,
             round(100.0 * sum(w) FILTER (placed = 'district' AND set_size = 1) / sum(w), 1) AS wpct_district_single,
             round(avg(set_size) FILTER (placed = 'district'), 2) AS mean_set_size,
             round(100.0 * sum(w) FILTER (placed <> 'nothing') / sum(w), 1) AS wpct_state_or_better,
             round(100.0 * sum(w) FILTER (placed = 'district' AND confidence = 'high') / sum(w), 1) AS wpct_district_high,
             round(100.0 * sum(w) FILTER (placed = 'district' AND confidence IN ('high', 'medium')) / sum(w), 1) AS wpct_district_high_medium,
             round(100.0 * sum(w) FILTER (sp_state IS NOT NULL) / sum(w), 1) AS wpct_state_today,
             round(sum(w)) AS records_represented"""
    for name, sql in {
        "fix_overall": f"SELECT 'all' AS grp, {agg} FROM fx",
        "fix_by_kind": f"SELECT kind AS grp, {agg} FROM fx GROUP BY 1 ORDER BY records_represented DESC",
        "fix_by_problem": f"SELECT problem AS grp, {agg} FROM fx GROUP BY 1 ORDER BY records_represented DESC",
        "fix_by_confidence": f"SELECT coalesce(confidence, 'no district') AS grp, {agg} FROM fx GROUP BY 1 ORDER BY 1",
        "fix_by_dataset": f"""SELECT datasetkey AS grp, any_value(kind) AS kind, {agg} FROM fx GROUP BY 1
                              ORDER BY records_represented DESC LIMIT 30""",
    }.items():
        con.sql(f"COPY ({sql}) TO '{RESULTS / (name + '.csv')}' (HEADER)")
    con.sql(f"""COPY (SELECT placed, coalesce(confidence, '') AS confidence, f.kind, s.locality, s.verbatimlocality, s.county,
                             s.stateprovince, f.matched, d.dtname AS district, f.state_lgd, round(f.radius_km, 1) AS radius_km,
                             f.n_candidates, f.gbifid
                      FROM (SELECT *, row_number() OVER (PARTITION BY placed, kind ORDER BY md5(gbifid::VARCHAR)) AS rn
                            FROM fx WHERE has_text) f
                      JOIN smp s USING (gbifid) LEFT JOIN districts d USING (dist_lgd)
                      WHERE rn <= 10 ORDER BY placed, kind)
                TO '{RESULTS / 'fix_examples.csv'}' (HEADER)""")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("key", nargs="?", help="download key (default: data/georef/download.json)")
    p.add_argument("--n", type=int, default=20000)
    a = p.parse_args()
    key = a.key or json.loads((DATA / "download.json").read_text())["key"]
    con = duckdb.connect()
    load(con, key, a.n)
    util.log(con.sql("SELECT sample, kind, count(*) FROM smp GROUP BY ALL ORDER BY ALL").fetchall())
    run_matches(con)
    metrics(con)
    fix_report(con)
    for t in ("ev", "fx"):  # for looking at failures by hand
        con.sql(f"COPY (SELECT x.*, {', '.join('s.' + f for f in FIELDS)} FROM {t} x JOIN smp s USING (gbifid)) TO '{DATA / (t + '.parquet')}' (FORMAT parquet)")
    for f in ("test_overall", "test_by_kind", "test_by_confidence", "fix_overall", "fix_by_kind"):
        util.log(f"\n{f}\n" + (RESULTS / f"{f}.csv").read_text())


if __name__ == "__main__":
    main()
