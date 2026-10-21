"""Small JSON files the site reads from a GBIF snapshot, built from the ledger and species tables.

  summary.json          snapshot figures, groups, rights
  unresolved.json       records not named to species, by group and area (method page)
  unlocated.json        records that cannot go in a district, by group and area (Records to fix)
  species/<shard>.json  one species' GBIF records by decade and district (species page)
"""

from pathlib import Path

import duckdb

from pipeline import ledger
from pipeline.groups import GROUP_SQL
from pipeline.util import dump, value

# PDGI: the rights travel inside the data, so nobody can use a file without the credit and the limits.
RIGHTS = {
    "licence": "CC BY 4.0, Sathya Sankaran (data and text). Each source keeps its own licence.",
    "attribution": ("Overlooked (https://overlooked-india.pages.dev). Sources: GBIF.org (cite the download DOIs), "
                    "iNaturalist, Botanical Survey of India and Zoological Survey of India (Ministry of Environment, "
                    "Forest and Climate Change, Government of India), Royal Botanic Gardens, Kew (WCVP), Plazi, "
                    "IUCN Red List, Catalogue of Life, Local Government Directory via bharatlas."),
    "disclaimer": ("Overlooked is not an official checklist or conservation assessment. For the status of a species, "
                   "consult BSI, ZSI, the IUCN Red List and the state forest department."),
}


def build(con: duckdb.DuckDBPyConnection, out: Path, meta: dict):
    """summary.json with the snapshot figures. Needs tables ledger (species_key, district_lgd, state_lgd,
    first_year, last_year, n_records, ...), species (species_key, name, kingdom, phylum, class, "order", family)
    and districts. Leaves tables sp, gidx, lg and india for the other files."""
    con.sql(f"""
        CREATE OR REPLACE TABLE sp AS
        SELECT species_key, name, family, {GROUP_SQL} AS grp FROM species
    """)
    groups = [r[0] for r in con.sql("""
        SELECT grp FROM sp JOIN (SELECT DISTINCT species_key FROM ledger) USING (species_key)
        GROUP BY grp ORDER BY count(*) DESC, grp""").fetchall()]
    con.execute("CREATE OR REPLACE TABLE gidx AS SELECT unnest($1) AS grp, generate_subscripts($1, 1) - 1 AS gi", [groups])
    ledger.ensure_dna_column(con, "ledger")
    con.sql("""
        CREATE OR REPLACE TABLE lg AS
        SELECT l.*, s.name, s.family, g.gi
        FROM ledger l JOIN sp s USING (species_key) JOIN gidx g USING (grp)
    """)
    con.sql("""
        CREATE OR REPLACE TABLE india AS
        SELECT species_key, any_value(name) AS name, any_value(gi) AS gi, any_value(family) AS family,
               min(first_year) AS first_year, max(last_year) AS last_year, sum(n_records) AS n
        FROM lg GROUP BY species_key
    """)
    one = lambda q: value(con, q)
    summary = dict(meta, **RIGHTS)
    summary.update({
        "species": one("SELECT count(*) FROM india"),
        "records": int(one("SELECT sum(n) FROM india")),
        "districts_with_records": one("SELECT count(DISTINCT district_lgd) FROM lg"),
        "districts_total": one("SELECT count(*) FROM districts"),
        "groups": groups,
        "group_species": [one(f"SELECT count(*) FROM india WHERE gi = {i}") for i in range(len(groups))],
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


def unlocated_json(con, out: Path, titles=None, cap=2000, top=50, per_state=3):
    """Records that cannot be placed in a district, by state ("none" for no place) and group: records (r) and
    species (s), arrays indexed [0 = all groups, 1 + group index]; records per problem (p: none, issue, coarse).
    Top dataset holders, and species known in India only from these records (no record with coordinates in the ledger or species table).
    titles: a function from dataset keys to {key: title}, or None to leave titles out."""
    groups = [r[0] for r in con.sql("SELECT grp FROM unlocated GROUP BY grp ORDER BY sum(n_records) DESC, grp").fetchall()]
    gi, n = {g: i for i, g in enumerate(groups)}, len(groups) + 1

    def by(area):
        res = {}
        for key, g, recs, sp in con.sql(f"""
                SELECT area, grp, sum(n_records), count(DISTINCT species_key)
                FROM (SELECT {area} AS area, * FROM unlocated)
                GROUP BY GROUPING SETS ((area, grp), (area))""").fetchall():
            d = res.setdefault(str(key), {"r": [0] * n, "s": [0] * n})
            k = 0 if g is None else gi[g] + 1
            d["r"][k], d["s"][k] = int(recs), sp
        for key, problem, recs in con.sql(f"""SELECT area, problem, sum(n_records) FROM (SELECT {area} AS area, * FROM unlocated)
                                              GROUP BY ALL ORDER BY 3 DESC""").fetchall():
            res[str(key)].setdefault("p", {})[problem] = int(recs)
        return res

    holders = con.sql(f"""SELECT datasetkey, sum(n_records), count(DISTINCT species_key) FROM unlocated
                          GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {top}""").fetchall()
    state_holders = {}
    for state, key, recs in con.sql(f"""
            SELECT state, datasetkey, r FROM (
                SELECT coalesce(state_lgd::VARCHAR, 'none') AS state, datasetkey, sum(n_records) AS r,
                       row_number() OVER (PARTITION BY state_lgd ORDER BY sum(n_records) DESC, datasetkey) AS rk
                FROM unlocated GROUP BY state_lgd, datasetkey)
            WHERE rk <= {per_state} ORDER BY state, r DESC""").fetchall():
        state_holders.setdefault(state, []).append([key, int(recs)])
    keys = list(dict.fromkeys([h[0] for h in holders] + [k for v in state_holders.values() for k, _ in v]))
    names = titles(keys) if titles else {}

    con.sql("""
        CREATE OR REPLACE TABLE only_unlocated AS
        SELECT species_key, any_value(name) AS name, any_value(grp) AS grp, sum(n_records) AS n,
               min(first_year) AS first_year, max(last_year) AS last_year, count(DISTINCT state_lgd) AS states
        FROM unlocated
        WHERE species_key IS NOT NULL
          AND species_key NOT IN (SELECT species_key FROM ledger) AND species_key NOT IN (SELECT species_key FROM species)
        GROUP BY species_key
    """)
    only_g = [0] * n
    for g, c in con.sql("SELECT grp, count(*) FROM only_unlocated GROUP BY GROUPING SETS ((grp), ())").fetchall():
        only_g[0 if g is None else gi[g] + 1] = c
    only_rows = [[k, nm, gi[g], int(c), f, la, st] for k, nm, g, c, f, la, st in con.sql(f"""
        SELECT species_key, name, grp, n, first_year, last_year, states FROM only_unlocated
        ORDER BY n DESC, name LIMIT {cap}""").fetchall()]

    states = by("coalesce(state_lgd::VARCHAR, 'none')")
    obj = {"groups": groups, "states": states, "india": by("0")["0"],
           "holders": [[k, names.get(k), int(r), s] for k, r, s in holders],
           "state_holders": state_holders, "titles": {k: names.get(k) for k in keys},
           "only_unlocated": {"g": only_g, "rows": only_rows}}
    dump(obj, out / "unlocated.json")
    return obj


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
    has_decades = bool(value(con, "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'species_decade'"))
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
