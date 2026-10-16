"""Small JSON files the site reads, built from the ledger and species tables.

The pages never need a database in the browser: each view loads one file.
  summary.json          overview figures
  map_stats.json        per district and group: species, records, quiet counts for each threshold year
  ledger/india.json     one row per species quiet in India (latest record before the last threshold year)
  ledger/s/<state>.json the same for a state
  ledger/d/<dist>.json  one row per species in a district (all species; these files are small)
India and state files hold only quiet species, to keep them small; the site says so.
Row: [species_key, name, group index, family, first year, last year, records]
"""

import json
from pathlib import Path

import duckdb

from pipeline.groups import GROUP_SQL

YEARS = [1980, 1990, 2000, 2010]


def dump(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))


def build(con: duckdb.DuckDBPyConnection, out: Path, meta: dict):
    """Needs tables ledger (species_key, district_lgd, state_lgd, first_year, last_year, n_records, ...),
    species (species_key, name, kingdom, phylum, class, "order", family) and districts."""
    con.sql(f"""
        CREATE OR REPLACE TABLE sp AS
        SELECT species_key, name, family, {GROUP_SQL} AS grp FROM species
    """)
    groups = [r[0] for r in con.sql("""
        SELECT grp FROM sp JOIN (SELECT DISTINCT species_key FROM ledger) USING (species_key)
        GROUP BY grp ORDER BY count(*) DESC""").fetchall()]
    gi = {g: i for i, g in enumerate(groups)}
    con.execute("CREATE OR REPLACE TABLE gidx AS SELECT unnest($1) AS grp, generate_subscripts($1, 1) - 1 AS gi", [groups])
    con.sql("""
        CREATE OR REPLACE TABLE lg AS
        SELECT l.*, s.name, s.family, g.gi
        FROM ledger l JOIN sp s USING (species_key) JOIN gidx g USING (grp)
    """)

    # Map stats: arrays indexed [0 = all groups, 1 + group index].
    n = len(groups) + 1
    stats = {}
    q_cols = ", ".join(f"count(*) FILTER (WHERE last_year < {y}) AS q{y}" for y in YEARS)
    for dist, g, sp_n, rec, *qs in con.sql(f"""
            SELECT district_lgd, gi, count(*), sum(n_records), {q_cols}
            FROM lg GROUP BY GROUPING SETS ((district_lgd, gi), (district_lgd))""").fetchall():
        d = stats.setdefault(str(dist), {"s": [0] * n, "r": [0] * n, "q": [[0] * n for _ in YEARS]})
        k = 0 if g is None else g + 1
        d["s"][k], d["r"][k] = sp_n, int(rec)
        for i, q in enumerate(qs):
            d["q"][i][k] = q
    # States: species counted once per state, not summed over districts.
    states = {}
    for state, g, sp_n, *qs in con.sql(f"""
            WITH lst AS (SELECT state_lgd, species_key, any_value(gi) AS gi, max(last_year) AS last_year
                         FROM lg GROUP BY state_lgd, species_key)
            SELECT state_lgd, gi, count(*), {q_cols}
            FROM lst GROUP BY GROUPING SETS ((state_lgd, gi), (state_lgd))""").fetchall():
        d = states.setdefault(str(state), {"s": [0] * n, "q": [[0] * n for _ in YEARS]})
        k = 0 if g is None else g + 1
        d["s"][k] = sp_n
        for i, q in enumerate(qs):
            d["q"][i][k] = q
    dump({"groups": groups, "years": YEARS, "districts": stats, "states": states}, out / "map_stats.json")

    # National species table and quiet counts.
    con.sql("""
        CREATE OR REPLACE TABLE india AS
        SELECT species_key, any_value(name) AS name, any_value(gi) AS gi, any_value(family) AS family,
               min(first_year) AS first_year, max(last_year) AS last_year, sum(n_records) AS n
        FROM lg GROUP BY species_key
    """)
    row_sql = "SELECT species_key, name, gi, family, first_year, last_year, n FROM {} ORDER BY last_year NULLS LAST, name"
    quiet = f"(SELECT * FROM {{}} WHERE last_year < {YEARS[-1]})"
    dump({"scope": f"quiet_before_{YEARS[-1]}", "rows": con.sql(row_sql.format(quiet.format("india"))).fetchall()},
         out / "ledger" / "india.json")
    for (state,) in con.sql("SELECT DISTINCT state_lgd FROM lg").fetchall():
        rows = con.sql(row_sql.format(quiet.format(f"""(SELECT species_key, any_value(name) AS name, any_value(gi) AS gi,
                any_value(family) AS family, min(first_year) AS first_year, max(last_year) AS last_year, sum(n_records) AS n
                FROM lg WHERE state_lgd = {state} GROUP BY species_key)"""))).fetchall()
        dump({"scope": f"quiet_before_{YEARS[-1]}", "rows": rows}, out / "ledger" / "s" / f"{state}.json")
    for (dist,) in con.sql("SELECT DISTINCT district_lgd FROM lg").fetchall():
        rows = con.sql(row_sql.format(f"""(SELECT species_key, name, gi, family, first_year, last_year, n_records AS n
                FROM lg WHERE district_lgd = {dist})""")).fetchall()
        dump({"scope": "all", "rows": rows}, out / "ledger" / "d" / f"{dist}.json")

    one = lambda s: con.sql(s).fetchone()[0]
    summary = dict(meta)
    summary.update({
        "species": one("SELECT count(*) FROM india"),
        "records": int(one("SELECT sum(n) FROM india")),
        "districts_with_records": one("SELECT count(DISTINCT district_lgd) FROM lg"),
        "districts_total": one("SELECT count(*) FROM districts"),
        "quiet_species": {str(y): one(f"SELECT count(*) FROM india WHERE last_year < {y}") for y in YEARS},
        "districts_with_quiet": {str(y): one(f"SELECT count(DISTINCT district_lgd) FROM lg WHERE last_year < {y}") for y in YEARS},
        "groups": groups,
        "group_species": [one(f"SELECT count(*) FROM india WHERE gi = {i}") for i in range(len(groups))],
        "group_quiet_1980": [one(f"SELECT count(*) FROM india WHERE gi = {i} AND last_year < 1980") for i in range(len(groups))],
    })
    dump(summary, out / "summary.json")
    return summary
