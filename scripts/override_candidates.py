"""Candidates for pipeline/ref/name_overrides.csv, for a reviewer: species on the India list that no Indian checklist
lists, with a congener that one does, and an older name that GBIF's match places under them (as Pteropus giganteus,
the Indian flying fox's old name, is placed under the Southeast Asian Pteropus vampyrus). Such a species may hold
another species' records under its old name. Strongest when IUCN has assessed it and its range does not include India
(iucn_india false, from the internal IUCN extract): those come first. Nothing is changed: the reviewer adds the rows
that are right. Internal: the IUCN column comes from IUCN's API, which may not be published.

Usage: .venv/bin/python -m scripts.override_candidates [master.parquet] [out.csv]
Default: the newest local master list and data/review/name_override_candidates.csv.
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKLISTS = {"ZSI", "BSI", "WCVP", "Lichens", "Bryophytes"}


def candidates(rows, cache, iucn_india=None):
    """rows: (key, name, sources, states_observed); cache: the GBIF name match ({name: {key, synonym, ...}});
    iucn_india: {name: whether IUCN's range includes India} for the species IUCN assessed."""
    iucn_india = iucn_india or {}
    listed_genus = {}
    for key, name, sources, _ in rows:
        if CHECKLISTS & set(sources):
            listed_genus.setdefault(name.split()[0], []).append(name)
    syn = {}
    for name, m in cache.items():
        if m and m.get("synonym") and m.get("key"):
            syn.setdefault(m["key"], []).append(name)
    out = []
    for key, name, sources, states in rows:
        genus = name.split()[0]
        if key in syn and not CHECKLISTS & set(sources) and listed_genus.get(genus):
            out.append({"key": key, "name": name, "sources": "; ".join(sources), "states": len(states or []),
                        "iucn_india": iucn_india.get(name), "synonyms": "; ".join(sorted(syn[key])),
                        "congeners_on_checklists": "; ".join(sorted(listed_genus[genus]))})
    return sorted(out, key=lambda r: (r["iucn_india"] is not False, -r["states"], r["name"]))


def main():
    import duckdb
    master = Path(sys.argv[1]) if len(sys.argv) > 1 else max((ROOT / "data/layers/master").glob("*/master.parquet"))
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data/review/name_override_candidates.csv"
    rows = duckdb.sql(f"SELECT key, name, sources, states_observed FROM '{master}' WHERE key IS NOT NULL").fetchall()
    cache = json.loads((ROOT / "data/cache/master/gbif_match.json").read_text())
    detail = ROOT / "data/cache/iucn_api/iucn_detail.parquet"
    iucn = dict(duckdb.sql(f"SELECT name, in_india_list FROM '{detail}'").fetchall()) if detail.exists() else {}
    found = candidates(rows, cache, iucn)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, ["key", "name", "sources", "states", "iucn_india", "synonyms", "congeners_on_checklists"])
        w.writeheader()
        w.writerows(found)
    print(f"{len(found)} candidates, {sum(r['iucn_india'] is False for r in found)} of them outside India by IUCN -> {out}")


if __name__ == "__main__":
    main()
