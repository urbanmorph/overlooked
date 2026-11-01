"""Candidates for pipeline/ref/name_overrides.csv, for a reviewer (pipeline/name_review.py): the public list with
IUCN's range added. Strongest when IUCN has assessed the species and its range does not include India (iucn_india
false, from the internal IUCN extract): those come first. Nothing is changed: the reviewer adds the rows
that are right. Internal: the IUCN column comes from IUCN's API, which may not be published.

Usage: .venv/bin/python -m scripts.override_candidates [master.parquet] [out.csv]
Default: the newest local master list and data/review/name_override_candidates.csv.
"""

import csv
import json
import sys
from pathlib import Path

from pipeline.name_review import candidates

ROOT = Path(__file__).resolve().parent.parent


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
