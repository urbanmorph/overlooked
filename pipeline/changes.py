"""Species health, first measure: the state of each species in a snapshot, and what moved since the previous one.

Built from the snapshot's own files (species, ledger, species_decade) and the cached IUCN Red List table; no
new downloads. Not on the site yet.

  species_state.parquet    one row per species: species_key, name, grp, kingdom, family, records (with
                           coordinates), records_observation / _specimen / _other (by kind of record), records_placed
                           (in a district), districts[], n_districts, states[], first_year, last_year,
                           districts_recent (districts with a record in the latest RECENT_YEARS), iucn
  species_state.json       reference year, inputs fingerprint, sources fingerprint, IUCN version, totals
  species_changes.parquet  one row per species x change since the previous published snapshot (CHANGE_TYPES)
  species_changes.json     counts by type, source shifts, largest record changes; the first snapshot is the baseline

Artefacts. A change between two snapshots is a change in the public data, not always a change in the field: GBIF
re-processes about 5% of India records each month, datasets are added or withdrawn, the Catalogue of Life renames
and merges species, and the district boundaries can change. Each snapshot keeps a fingerprint of its sources
(rows per download, GBIF's India record count, a hash of each query with its excluded datasets, the boundary
checksum). Rows are flagged when the sources moved more than LARGE_SOURCE_CHANGE, when a species' own records
jump or change kind at once (typical of a museum or literature dataset), and when its name changed. A merge of one species into another
shows only as "not_in_snapshot" plus a records jump on the other: the snapshot has no synonym list.

Usage:
    python -m pipeline.changes state <snapshot> [<snapshot> ...]
    python -m pipeline.changes compare <old snapshot> <new snapshot>
A snapshot is a folder or a run id under data/snapshots.
"""

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

from pipeline import iucn, r2
from pipeline.groups import GROUP_SQL
from pipeline.r2 import sha256
from pipeline.util import first, now, value

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "data" / "snapshots"
SNAPSHOT_FILES = ("species.parquet", "ledger.parquet", "species_decade.parquet")
STATE, STATE_META = "species_state.parquet", "species_state.json"
FEED, FEED_META = "species_changes.parquet", "species_changes.json"

# A record in the latest RECENT_YEARS years (counted from the snapshot's year) is recent (plan section 11: 30 years).
RECENT_YEARS = 30
# A source that moved more than this share between snapshots flags every change.
LARGE_SOURCE_CHANGE = 0.05
# A species whose records changed by more than this share, and by at least MIN_RECORD_CHANGE records.
LARGE_RECORD_CHANGE = 0.5
MIN_RECORD_CHANGE = 20
# ... or whose share of observations (against specimens and other kinds) moved by more than this.
KIND_SHIFT = 0.25
# A species new to the snapshot with this many records at once: more likely a dataset or a name than a sighting.
MANY_RECORDS_AT_ONCE = 50
# Largest record changes listed in species_changes.json.
TOP_JUMPS = 500

OBSERVATION = ("HUMAN_OBSERVATION", "OBSERVATION", "MACHINE_OBSERVATION")
SPECIMEN = ("PRESERVED_SPECIMEN", "MATERIAL_SAMPLE")

CHANGE_TYPES = ("newly_recorded", "not_in_snapshot", "key_changed", "renamed", "no_recent_record",
                "recent_record_again", "districts_added", "districts_removed", "iucn_changed")
DISTRICT_TYPES = ("districts_added", "districts_removed")
FEED_COLS = ("change, species_key, species_key_before, name, name_before, grp, records_before, records_after, "
             "last_year_before, last_year_after, districts_added, districts_removed, iucn_before, iucn_after, reason, flags")


# ---------------------------------------------------------------- inputs

def sources(manifest):
    """The sources fingerprint of a snapshot, from its manifest (or the same fields before the manifest is written).
    queries is None for snapshots built before query hashes were kept."""
    gbif = ((manifest.get("health") or {}).get("sources") or {}).get("gbif_api") or {}
    return {"records": {d["query"]: d.get("records") for d in manifest.get("downloads") or []},
            "queries": manifest.get("queries"),
            "boundaries": ((manifest.get("boundaries") or {}).get("sha256") or "")[:12] or None,
            "gbif_india_records": (gbif.get("fingerprint") or {}).get("india_records")}


def folder_sources(folder: Path):
    """The sources fingerprint from the snapshot's manifest.json; unknown ({}) when it has none."""
    manifest = Path(folder) / "manifest.json"
    return sources(json.loads(manifest.read_text())) if manifest.exists() else {}


def iucn_input(s3=None):
    """The Red List table the master list keeps (pipeline/iucn.py): local, else R2 cache/master/. (None, None) if
    neither has it. No request to IUCN or GBIF."""
    path, meta = iucn.CACHE / iucn.PARQUET, iucn.CACHE / iucn.META
    for p in (path, meta):
        r2.restore(s3, f"cache/master/{p.name}", p)
    if path.exists() and meta.exists():
        return path, json.loads(meta.read_text())
    return None, None


def fingerprint(paths, extra):
    """Same files, settings and code give the same output, so a second run does nothing."""
    blob = json.dumps({"files": [sha256(p) if p and Path(p).exists() else None for p in paths],
                       "code": sha256(Path(__file__)), **extra}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- state

def state(folder: Path, run_id, sources, iucn_path=None, iucn_meta=None):
    """Write species_state.parquet and .json for the snapshot in folder. Skipped when built from the same inputs."""
    folder = Path(folder)
    ref_year = int(run_id[:4])
    inputs = fingerprint([folder / f for f in SNAPSHOT_FILES] + [iucn_path],
                         {"run_id": run_id, "sources": sources, "iucn": iucn_meta, "recent": RECENT_YEARS})
    meta_path = folder / STATE_META
    if meta_path.exists() and (folder / STATE).exists():
        old = json.loads(meta_path.read_text())
        if old.get("inputs") == inputs:
            return old
    species, ledger, decade = (folder / f for f in SNAPSHOT_FILES)
    kinds = lambda basis: ", ".join(f"'{b}'" for b in basis)
    # IUCN (NE: not assessed; NULL: no Red List table this month): the Red List name equal to the GBIF name, the
    # assessed name before a synonym, same kingdom when both know it. Simpler than the master list, which also tries
    # the names other sources give.
    iucn_sql = (f"""SELECT s.species_key, arg_min(i.category, CASE WHEN i.accepted THEN 0 ELSE 1 END) AS iucn
                    FROM '{species}' s JOIN '{iucn_path}' i ON i.name = s.name
                         AND (i.kingdom IS NULL OR s.kingdom IS NULL OR i.kingdom = s.kingdom)
                    GROUP BY 1""" if iucn_path else "SELECT NULL::VARCHAR AS species_key, NULL::VARCHAR AS iucn WHERE false")
    con = duckdb.connect()
    con.sql(f"""
        CREATE TABLE st AS
        WITH k AS (SELECT species_key, sum(n_records) AS records,
                          sum(n_records) FILTER (WHERE basis IN ({kinds(OBSERVATION)})) AS obs,
                          sum(n_records) FILTER (WHERE basis IN ({kinds(SPECIMEN)})) AS spec
                   FROM '{decade}' GROUP BY 1),
        l AS (SELECT species_key, sum(n_records) AS placed, list(district_lgd ORDER BY district_lgd) AS districts,
                     list(DISTINCT state_lgd ORDER BY state_lgd) AS states, min(first_year) AS first_year,
                     max(last_year) AS last_year,
                     count(*) FILTER (WHERE last_year >= {ref_year - RECENT_YEARS}) AS recent
              FROM '{ledger}' GROUP BY 1),
        iu AS ({iucn_sql})
        SELECT species_key, name, {GROUP_SQL} AS grp, kingdom, family,
               coalesce(k.records, 0)::BIGINT AS records, coalesce(k.obs, 0)::BIGINT AS records_observation,
               coalesce(k.spec, 0)::BIGINT AS records_specimen,
               coalesce(k.records - coalesce(k.obs, 0) - coalesce(k.spec, 0), 0)::BIGINT AS records_other,
               coalesce(l.placed, 0)::BIGINT AS records_placed, coalesce(l.districts, []) AS districts,
               len(coalesce(l.districts, [])) AS n_districts, coalesce(l.states, []) AS states,
               l.first_year, l.last_year, coalesce(l.recent, 0) AS districts_recent,
               {"coalesce(iu.iucn, 'NE')" if iucn_path else "NULL::VARCHAR"} AS iucn
        FROM '{species}' LEFT JOIN k USING (species_key) LEFT JOIN l USING (species_key) LEFT JOIN iu USING (species_key)
        ORDER BY species_key
    """)
    con.sql(f"COPY st TO '{folder / STATE}' (FORMAT parquet, COMPRESSION zstd)")
    n, records, placed = first(con, "SELECT count(*), sum(records), sum(records_placed) FROM st")
    meta = {"run_id": run_id, "built": now(), "ref_year": ref_year, "recent_years": RECENT_YEARS, "inputs": inputs,
            "rows": n, "sources": sources, "iucn": iucn_meta,
            "totals": {"species": n, "records": int(records or 0), "records_placed": int(placed or 0),
                       "districts": value(con, f"SELECT count(DISTINCT district_lgd) FROM '{ledger}'")}}
    meta_path.write_text(json.dumps(meta, indent=1))
    return meta


def previous_state(folder: Path, prefix, s3, iucn_path=None, iucn_meta=None):
    """The state of a published snapshot: its own state files (local, else R2 <prefix>/), else built from its snapshot
    files. A snapshot made before this module has no state, and its IUCN column then uses today's table.
    Returns the folder, or None when the snapshot is not found."""
    folder = Path(folder)
    for name in (STATE, STATE_META):
        r2.restore(s3, f"{prefix}/{name}", folder / name)
    if (folder / STATE).exists() and (folder / STATE_META).exists():
        return folder
    for name in (*SNAPSHOT_FILES, "manifest.json"):
        r2.restore(s3, f"{prefix}/{name}", folder / name)
    if not all((folder / f).exists() for f in SNAPSHOT_FILES):
        return None
    state(folder, folder.name, folder_sources(folder), iucn_path, iucn_meta)
    return folder


# ---------------------------------------------------------------- change feed

def shifts(before, after):
    """Sources that moved between two snapshots (shifts), and those one side does not know (unknown)."""
    moved, unknown = [], []
    for k in ("queries", "boundaries"):
        if not before.get(k) or not after.get(k):
            unknown.append(k)
        elif before[k] != after[k]:
            moved.append(k)
    counts = [(f"records:{q}", (before.get("records") or {}).get(q), n) for q, n in (after.get("records") or {}).items()]
    counts.append(("gbif_india_records", before.get("gbif_india_records"), after.get("gbif_india_records")))
    for k, b, a in counts:
        if not b or a is None:
            unknown.append(k)
        elif abs(a - b) / b > LARGE_SOURCE_CHANGE:
            moved.append(k)
    return moved, unknown


def compare(old, new):
    """Write species_changes.parquet and .json in the new snapshot folder, against the old one (None: baseline,
    an empty feed). Skipped when both states are unchanged since the last comparison."""
    new = Path(new)
    after = json.loads((new / STATE_META).read_text())
    before = json.loads((Path(old) / STATE_META).read_text()) if old else None
    key = {"from": before and before["inputs"], "to": after["inputs"], "code": sha256(Path(__file__))}
    if (new / FEED_META).exists() and (new / FEED).exists():
        done = json.loads((new / FEED_META).read_text())
        if done.get("inputs") == key:
            return done

    con = duckdb.connect()
    con.sql(f"CREATE TABLE n AS SELECT * FROM '{new / STATE}'")
    con.sql(f"CREATE TABLE o AS SELECT * FROM '{Path(old) / STATE}'" if old else "CREATE TABLE o AS FROM n WHERE false")
    moved, unknown = shifts(before["sources"], after["sources"]) if before else ([], [])
    ref_old, ref_new = (before or after)["ref_year"], after["ref_year"]
    recent_old, recent_new = ref_old - RECENT_YEARS, ref_new - RECENT_YEARS
    # A key that left and a key that arrived with the same name (one each): the same species under a new key.
    con.sql("""
        CREATE TABLE moved AS
        WITH gone AS (FROM o ANTI JOIN n USING (species_key)), fresh AS (FROM n ANTI JOIN o USING (species_key))
        SELECT g.species_key AS old_key, f.species_key AS new_key FROM gone g JOIN fresh f USING (name)
        WHERE g.name IN (SELECT name FROM gone GROUP BY 1 HAVING count(*) = 1)
          AND f.name IN (SELECT name FROM fresh GROUP BY 1 HAVING count(*) = 1)
    """)
    obs_share = lambda t: f"{t}.records_observation / nullif({t}.records, 0)"
    con.sql(f"""
        CREATE TABLE pair AS
        SELECT o.species_key IS NOT NULL AS was, n.species_key IS NOT NULL AS now,
               coalesce(n.species_key, o.species_key) AS species_key, o.species_key AS species_key_before,
               coalesce(n.name, o.name) AS name, o.name AS name_before, coalesce(n.grp, o.grp) AS grp,
               o.records AS records_before, n.records AS records_after,
               abs({obs_share('n')} - {obs_share('o')}) AS kind_move,
               o.last_year AS last_year_before, n.last_year AS last_year_after,
               list_filter(coalesce(n.districts, []), lambda x: NOT list_contains(coalesce(o.districts, []), x)) AS districts_added,
               list_filter(coalesce(o.districts, []), lambda x: NOT list_contains(coalesce(n.districts, []), x)) AS districts_removed,
               o.iucn AS iucn_before, n.iucn AS iucn_after
        FROM (SELECT o.*, coalesce(m.new_key, o.species_key) AS nk FROM o LEFT JOIN moved m ON m.old_key = o.species_key) o
        FULL JOIN n ON o.nk = n.species_key
    """)
    both = "was AND now"
    big = f"abs(records_after - records_before) >= {MIN_RECORD_CHANGE}"
    species_flags = {
        "records_jump": f"{both} AND {big} AND abs(records_after - records_before) > {LARGE_RECORD_CHANGE} * greatest(records_before, 1)",
        "kind_shift": f"{both} AND {big} AND kind_move > {KIND_SHIFT}",
        "many_records_at_once": f"NOT was AND records_after >= {MANY_RECORDS_AT_ONCE}",
        "latest_record_removed": f"{both} AND last_year_after < last_year_before",
        # IUCN is matched by name, so a new name can change the category found.
        "name_changed": f"{both} AND name <> name_before",
    }
    con.sql(f"""ALTER TABLE pair ADD COLUMN flags VARCHAR[];
                UPDATE pair SET flags = list_filter([{', '.join(f"CASE WHEN {c} THEN '{f}' END" for f, c in species_flags.items())}],
                                                    lambda x: x IS NOT NULL)""")
    iucn_known = bool(before and before.get("iucn") and after.get("iucn"))
    when = {
        "newly_recorded": "NOT was",
        "not_in_snapshot": "NOT now",
        "key_changed": f"{both} AND species_key <> species_key_before",
        "renamed": f"{both} AND species_key = species_key_before AND name <> name_before",
        "no_recent_record": f"{both} AND last_year_after < {recent_new} AND last_year_before >= {recent_old}",
        "recent_record_again": f"{both} AND last_year_after >= {recent_new} AND last_year_before < {recent_old}",
        "districts_added": f"{both} AND len(districts_added) > 0",
        "districts_removed": f"{both} AND len(districts_removed) > 0",
        "iucn_changed": f"{both} AND {iucn_known} AND iucn_before <> iucn_after",
    }
    # Reason, by year only: a record dated in or after the previous snapshot's year is a new record.
    dated = (f"CASE WHEN last_year_after IS NULL THEN NULL WHEN last_year_after >= {ref_old} THEN 'new record' "
             "ELSE 'older record, newly published' END")
    reason = {"newly_recorded": dated, "recent_record_again": dated,
              "not_in_snapshot": "'records removed, moved or renamed at the source'",
              "districts_removed": "'records removed, moved or renamed at the source'",
              "no_recent_record": "CASE WHEN last_year_after < last_year_before THEN 'latest record removed at the source' "
                                  "ELSE 'time passed' END"}
    # Flags for the whole snapshot: any source moved; boundaries only touch district changes.
    common = ["large_source_change"] if any(m != "boundaries" for m in moved) else []

    def flags(change):
        extra = common + (["boundaries_changed"] if "boundaries" in moved and change in DISTRICT_TYPES else [])
        return f"list_concat(flags, {extra!r}::VARCHAR[])"

    # The baseline (no previous snapshot) has no changes.
    con.sql(f"""
        CREATE TABLE feed AS
        {" UNION ALL ".join(f"SELECT '{c}' AS change, * EXCLUDE (was, now, kind_move, flags), {reason.get(c, 'NULL')} AS reason, "
                            f"{flags(c)} AS flags FROM pair WHERE {before is not None} AND {when[c]}" for c in CHANGE_TYPES)}
    """)
    con.sql(f"COPY (SELECT {FEED_COLS} FROM feed ORDER BY change, species_key) TO '{new / FEED}' (FORMAT parquet, COMPRESSION zstd)")
    counts = dict.fromkeys(CHANGE_TYPES, 0) | dict(con.sql("SELECT change, count(*) FROM feed GROUP BY 1").fetchall())
    jumps = con.sql(f"""SELECT species_key, name, records_before, records_after, flags FROM pair
                        WHERE list_has_any(flags, ['records_jump', 'kind_shift'])
                        ORDER BY abs(records_after - records_before) DESC, species_key LIMIT {TOP_JUMPS}""").fetchall()
    summary = {
        "from": before and before["run_id"], "to": after["run_id"], "baseline": before is None, "built": now(),
        "inputs": key,
        "thresholds": {"recent_years": RECENT_YEARS, "large_source_change": LARGE_SOURCE_CHANGE,
                       "large_record_change": LARGE_RECORD_CHANGE, "min_record_change": MIN_RECORD_CHANGE,
                       "kind_shift": KIND_SHIFT, "many_records_at_once": MANY_RECORDS_AT_ONCE},
        "counts": counts, "rows": sum(counts.values()),
        "flagged": value(con, "SELECT count(*) FROM feed WHERE len(flags) > 0"),
        "sources": {"shifts": moved, "unknown": unknown, "from": before and before["sources"], "to": after["sources"]},
        "totals": {"from": before and before["totals"], "to": after["totals"]},
        "record_jumps": [[k, nm, int(b), int(a), list(f)] for k, nm, b, a, f in jumps],
    }
    (new / FEED_META).write_text(json.dumps(summary, indent=1))
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["state", "compare"])
    p.add_argument("snapshots", nargs="+", help="folders or run ids under data/snapshots")
    a = p.parse_args()
    folders = [Path(s) if Path(s).is_dir() else SNAPSHOTS / s for s in a.snapshots]
    if a.cmd == "compare" and len(folders) != 2:
        p.error("compare needs two snapshots: old, new")
    iucn_path, iucn_meta = iucn_input()
    for f in folders:
        meta = state(f, f.name, folder_sources(f), iucn_path, iucn_meta)
        print(json.dumps({k: meta[k] for k in ("run_id", "rows", "totals", "inputs")}))
    if a.cmd == "compare":
        s = compare(*folders)
        print(json.dumps({k: s[k] for k in ("from", "to", "counts", "rows", "flagged", "sources")}, indent=1))
        print(f"largest record changes: {s['record_jumps'][:5]}")


if __name__ == "__main__":
    main()
