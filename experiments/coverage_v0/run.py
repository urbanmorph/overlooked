"""Coverage study, step 1: the columns this week's list and GBIF snapshot can answer, by group, as a matrix.

Usage: .venv/bin/python experiments/coverage_v0/run.py [--period 2026-10-26] [--recent-from 2016]
Writes experiments/coverage_v0/results/by_group.csv and prints the matrix (shares of each group's species).
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from wel import COLUMNS, by_group, flags  # noqa: E402


def waiting_only(layer: Path):
    """Names not on the list, known only from observations that wait for a name (status 2), per group."""
    groups = json.loads((layer / "summary.json").read_text())["groups"]
    out = {}
    for f in (layer / "w").glob("*.json"):
        n = sum(1 for r in json.loads(f.read_text())["rows"] if r[3] == 2)
        out[groups[int(f.stem)]] = n
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--period", default="2026-10-26")
    p.add_argument("--recent-from", type=int, default=2016)
    a = p.parse_args()
    layer = ROOT / "data" / "layers" / "master" / a.period
    snap = ROOT / "data" / "snapshots" / a.period
    con = duckdb.connect()
    g = by_group(con, flags(con, str(layer / "master.parquet"), str(snap / "ledger.parquet"),
                            str(snap / "unlocated.parquet"), a.recent_from))
    wait = waiting_only(layer)
    total = {k: sum(c[k] for c in g.values()) for k in ["species", *COLUMNS]}
    rows = sorted(g.items(), key=lambda kv: -kv[1]["species"]) + [("All of India", total)]
    out = HERE / "results" / "by_group.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["group", "species", *COLUMNS, "waiting_only"])
        for name, c in rows:
            w.writerow([name, c["species"], *(c[k] for k in COLUMNS),
                        sum(wait.values()) if name == "All of India" else wait.get(name, 0)])
    head = "".join(f"{k[:11]:>12}" for k in COLUMNS)
    print(f"{'group':42}{'species':>9}{head}{'waiting':>9}")
    for name, c in rows:
        shares = "".join(f"{100 * c[k] / c['species']:11.0f}%" for k in COLUMNS)
        n_wait = sum(wait.values()) if name == "All of India" else wait.get(name, 0)
        print(f"{name[:41]:42}{c['species']:9,}{shares}{n_wait:9,}")
    print(f"\nwritten {out.relative_to(ROOT)}; recent = a record placed in a state in {a.recent_from} or later")


if __name__ == "__main__":
    main()
