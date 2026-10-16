"""Small JSON files the site reads, built from the ledger and species tables.

The pages never need a database in the browser: each view loads one file.
  summary.json          overview figures
  map_stats.json        per district, state and India, per group: species, effort, quiet and unsurveyed counts
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
        GROUP BY grp ORDER BY count(*) DESC, grp""").fetchall()]
    gi = {g: i for i, g in enumerate(groups)}
    con.execute("CREATE OR REPLACE TABLE gidx AS SELECT unnest($1) AS grp, generate_subscripts($1, 1) - 1 AS gi", [groups])
    con.sql("""
        CREATE OR REPLACE TABLE lg AS
        SELECT l.*, s.name, s.family, g.gi
        FROM ledger l JOIN sp s USING (species_key) JOIN gidx g USING (grp)
    """)

    # Map stats. Arrays are indexed [0 = all groups, 1 + group index]; q, u and a have one array per year.
    #   s  species with public records
    #   a  species of the group recorded since the year (survey effort)
    #   q  quiet species: records, none since the year, in a group that WAS recorded since the year
    #   u  species with no record since the year in a group with no records since then at all:
    #      the area looks unsurveyed for that group, so these are not counted as quiet
    n = len(groups) + 1

    def area_stats(rel, area, with_records):
        a_cols = ", ".join(f"count(*) FILTER (WHERE last_year >= {y}) AS a{y}" for y in YEARS)
        con.sql(f"CREATE OR REPLACE TABLE eff AS SELECT {area}, gi, {a_cols} FROM {rel} GROUP BY {area}, gi")
        q_cols = ", ".join(f"count(*) FILTER (WHERE x.last_year < {y} AND e.a{y} > 0) AS q{y}" for y in YEARS)
        u_cols = ", ".join(f"count(*) FILTER (WHERE x.last_year < {y} AND e.a{y} = 0) AS u{y}" for y in YEARS)
        a_sum = ", ".join(f"sum(e.a{y}) FILTER (WHERE x.rk = 1) AS a{y}" for y in YEARS)
        rec = "sum(x.n_records)" if with_records else "0"
        out = {}
        for row in con.sql(f"""
                WITH x AS (SELECT *, row_number() OVER (PARTITION BY {area}, gi ORDER BY species_key) AS rk FROM {rel})
                SELECT x.{area}, x.gi, count(*), {rec}, {q_cols}, {u_cols}, {a_sum}
                FROM x JOIN eff e USING ({area}, gi)
                GROUP BY GROUPING SETS ((x.{area}, x.gi), (x.{area}))""").fetchall():
            key, g, sp_n, recs = row[:4]
            k, Y = (0 if g is None else g + 1), len(YEARS)
            qs, us, as_ = row[4:4 + Y], row[4 + Y:4 + 2 * Y], row[4 + 2 * Y:]
            d = out.setdefault(str(key), {"s": [0] * n, "a": [[0] * n for _ in YEARS],
                                          "q": [[0] * n for _ in YEARS], "u": [[0] * n for _ in YEARS]})
            d["s"][k] = sp_n
            if with_records:
                d.setdefault("r", [0] * n)[k] = int(recs or 0)
            for i in range(Y):
                d["q"][i][k], d["u"][i][k], d["a"][i][k] = qs[i], us[i], int(as_[i] or 0)
        return out

    stats = area_stats("lg", "district_lgd", True)
    con.sql("""CREATE OR REPLACE TABLE lst AS
               SELECT state_lgd, species_key, any_value(gi) AS gi, max(last_year) AS last_year
               FROM lg GROUP BY state_lgd, species_key""")
    states = area_stats("lst", "state_lgd", False)
    con.sql("""CREATE OR REPLACE TABLE lin AS
               SELECT 0 AS country, species_key, any_value(gi) AS gi, max(last_year) AS last_year
               FROM lg GROUP BY species_key""")
    india = area_stats("lin", "country", False)["0"]
    dump({"groups": groups, "years": YEARS, "districts": stats, "states": states, "india": india},
         out / "map_stats.json")

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
        "quiet_species": {str(y): india["q"][i][0] for i, y in enumerate(YEARS)},
        "districts_with_quiet": {str(y): sum(1 for d in stats.values() if d["q"][i][0] > 0) for i, y in enumerate(YEARS)},
        "unsurveyed_species_district_pairs": {str(y): sum(d["u"][i][0] for d in stats.values()) for i, y in enumerate(YEARS)},
        "groups": groups,
        "group_species": [one(f"SELECT count(*) FROM india WHERE gi = {i}") for i in range(len(groups))],
        "group_quiet_1980": [india["q"][0][i + 1] for i in range(len(groups))],
    })
    dump(summary, out / "summary.json")
    return summary


def unresolved_json(con, out: Path):
    """Records not named to species (module 5), per district, state and India, by group and rank."""
    groups = [r[0] for r in con.sql("SELECT grp FROM unresolved GROUP BY grp ORDER BY sum(n_records) DESC").fetchall()]
    ranks = [r[0] for r in con.sql("SELECT taxonrank FROM unresolved GROUP BY 1 ORDER BY sum(n_records) DESC").fetchall()]
    gi, ri = {g: i for i, g in enumerate(groups)}, {r: i for i, r in enumerate(ranks)}

    def by(level):
        res = {}
        for area, g, rk, n in con.sql(f"SELECT {level}, grp, taxonrank, sum(n_records) FROM unresolved GROUP BY ALL").fetchall():
            d = res.setdefault(str(area), {"n": 0, "g": [0] * len(groups), "r": [0] * len(ranks)})
            d["n"] += int(n); d["g"][gi[g]] += int(n); d["r"][ri[rk]] += int(n)
        return res

    obj = {"groups": groups, "ranks": ranks, "districts": by("district_lgd"), "states": by("state_lgd"),
           "india": by("0")["0"]}
    dump(obj, out / "unresolved.json")
    return obj["india"]["n"]


def changes_json(con, out: Path, counts, previous, summary):
    """Page data for the change feed. previous: the previous snapshot's summary, or None (first run)."""
    if previous is None:
        dump({"baseline": True, "previous": None}, out / "changes.json")
        return
    rows = con.sql("""
        SELECT c.change, c.species_key, s.name, g.gi, c.district_lgd, c.state_lgd, c.before_year, c.now_year, c.reason
        FROM changes c JOIN sp s USING (species_key) JOIN gidx g USING (grp)
        ORDER BY CASE c.change WHEN 'recorded_again' THEN 0 WHEN 'first_in_state' THEN 1 WHEN 'now_quiet' THEN 2 ELSE 3 END,
                 c.now_year DESC NULLS LAST, s.name
    """).fetchall()
    prev_q = dict(zip(previous.get("groups", []), previous.get("group_quiet_1980", [])))
    groups = [{"group": g, "before": prev_q.get(g), "now": q} for g, q in zip(summary["groups"], summary["group_quiet_1980"])]
    dump({"baseline": False, "previous": previous["run_id"], "counts": counts, "groups": groups, "rows": rows},
         out / "changes.json")


SHARDS = 512


def shard_of(key):
    """FNV-1a (32-bit) of the species key, modulo SHARDS. The site computes the same in JavaScript."""
    h = 0x811C9DC5
    for ch in str(key).encode("utf-8"):
        h ^= ch
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h % SHARDS


def species_shards(con, out: Path):
    """One small file per shard: each species with its classification, districts and history by decade."""
    has_decades = bool(con.sql("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'species_decade'").fetchone()[0])
    genus = "s.genus" if "genus" in [c[0] for c in con.sql("DESCRIBE species").fetchall()] else "NULL"
    sp = {r[0]: {"name": r[1], "gi": r[2], "kingdom": r[3], "phylum": r[4], "class": r[5], "order": r[6],
                 "family": r[7], "genus": r[8], "districts": [], "decades": []}
          for r in con.sql("""
              SELECT s.species_key, s.name, g.gi, s.kingdom, s.phylum, s.class, s."order", s.family,
                     {genus} AS genus
              FROM species s JOIN sp USING (species_key) JOIN gidx g USING (grp)
              WHERE s.species_key IN (SELECT species_key FROM lg)""".format(genus=genus)).fetchall()}
    for key, dist, first, last, n in con.sql(
            "SELECT species_key, district_lgd, first_year, last_year, n_records FROM lg ORDER BY species_key, last_year DESC").fetchall():
        sp[key]["districts"].append([dist, first, last, int(n)])
    if has_decades:
        for key, dec, basis, n in con.sql("SELECT species_key, decade, basis, n_records FROM species_decade").fetchall():
            if key in sp:
                sp[key]["decades"].append([dec, basis, int(n)])
    shards = {}
    for key, v in sp.items():
        shards.setdefault(shard_of(key), {})[key] = v
    for i, part in shards.items():
        dump(part, out / "species" / f"{i}.json")
    return len(sp)
