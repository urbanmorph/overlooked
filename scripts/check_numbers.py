"""Check that the numbers the site shows agree with each other: home tiles, group cards, Changes, Shortlists and the
figures typed into the pages. Reads the published files at /data/ (the live site by default). Prints each problem;
exit 1 when there is one. Run after a weekly publish.

Usage: .venv/bin/python scripts/check_numbers.py [--site https://overlooked-india.pages.dev]
"""

import argparse
import csv
import html
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.master import MEASURES, history_entry

TOTALS = ("documented", "observed")


def old_list(s):
    """A list from before open records (its totals have identified): its numbers are read another way."""
    return "identified" in s["totals"]


def week_base(get, period):
    """The folder of a week's current build (its current.json), or, for a list from before builds, the week's folder.
    get: path -> parsed JSON, or None when there is no such file."""
    return (get(f"layers/master/{period}/current.json") or {}).get("base") or f"layers/master/{period}/"


def check_summary(s):
    """The India totals are the sum of the group rows the cards and the map show."""
    if old_list(s):
        return []
    sums = [sum(r[n] for r in s["india"]) for n in range(len(TOTALS))]
    return [f"summary {s.get('period') or s.get('month')}: totals {k} is {s['totals'][k]}, its groups add up to {v}"
            for k, v in zip(TOTALS, sums) if s["totals"][k] != v]


def check_history(h, summaries):
    """Each list in history.json (the tiles and the chart) has the totals of that list's own summary."""
    out = []
    for e in h["lists"]:
        s = summaries.get(e["period"])
        if s is None or old_list(s):
            continue
        want = history_entry(s)["india"]
        out += [f"history {e['period']}: {m} is {a}, the summary gives {b}"
                for m, a, b in zip(MEASURES, e["india"], want) if a != b]
    return out


def check_changes(ch, ptr, h):
    """changes.json compares the lists latest.json names; its counts are its rows; its waiting line is the history's."""
    out = []
    if ch.get("to") != ptr.get("period"):
        out.append(f"changes: to {ch.get('to')}, latest.json {ptr.get('period')}")
    if ch.get("from") != ptr.get("previous"):
        out.append(f"changes: from {ch.get('from')}, latest.json previous {ptr.get('previous')}")
    for kind, n in (ch.get("counts") or {}).items():
        rows = sum(1 for r in ch.get("rows", []) if r[0] == kind)
        if n != rows:
            out.append(f"changes: {kind} counted {n}, rows {rows}")
    w, wi = ch.get("waiting") or {}, MEASURES.index("waiting_observations")
    by = {e["period"]: e["india"][wi] for e in h["lists"]}
    if w.get("now") is not None and by.get(ch.get("to")) != w["now"]:
        out.append(f"changes: waiting now {w['now']}, history {by.get(ch.get('to'))}")
    if w.get("before") is not None and ch.get("from") in by and by[ch["from"]] != w["before"]:
        out.append(f"changes: waiting before {w['before']}, history {by[ch['from']]}")
    return out


def check_shortlist(latest, rows_in_files):
    """latest.json's counts (the page's band chips and pager) are the rows in the group files."""
    out = [f"shortlist {g['key']}: latest.json says {g['rows']} rows, the files hold {rows_in_files.get(g['key'], 0)}"
           for g in latest["groups"] if g["rows"] != rows_in_files.get(g["key"], 0)]
    if latest["rows"] != sum(g["rows"] for g in latest["groups"]):
        out.append(f"shortlist: latest.json rows {latest['rows']}, groups add up to {sum(g['rows'] for g in latest['groups'])}")
    return out


def waiting_all(s):
    """Observations on iNaturalist that wait for a name, at every rank: named to species, to genus, and above genus."""
    w = s["waiting"]
    return (sum(r[1] for r in w["india"]) + sum(r[1] for r in (w.get("genus") or {}).get("india", []))
            + sum(((w.get("coarse") or {}).get("india") or {}).values()))


def check_lakh(text, n, tolerance=0.05):
    """A figure in the text such as "about 29 lakh" is within 5% of the data."""
    m = re.search(r"([\d.]+) lakh", text)
    if not m:
        return [f"no lakh figure in {text!r}"]
    said = float(m.group(1)) * 1e5
    return [] if abs(said - n) <= tolerance * n else [f"text says {text}, the data says {n / 1e5:.1f} lakh"]


def check_method_table(page, gate):
    """The table of groups on the method page has the numbers of results/gate.csv."""
    out = []
    rows = {r["group"].replace("&", "and"): r for r in gate}
    for cells in re.findall(r"<tr>(.*?)</tr>", page, re.DOTALL):
        td = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", cells, re.DOTALL)]
        if len(td) < 5 or td[0] not in rows:
            continue
        g = rows[td[0]]
        cov = g["g_cov"] if g["verdict"] == "Genus first" else g["sp_cov"]
        for label, shown, want in (("test observations", td[2], g["n"]), ("first name right", td[3], g["top1"]),
                                   ("right name in the list", td[4], cov)):
            if float(shown.rstrip("%").replace(",", "")) != float(want):
                out.append(f"method table {td[0]}: {label} {shown.rstrip('%')}, gate.csv {want}")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--site", default="https://overlooked-india.pages.dev")
    a = p.parse_args()
    http = requests.Session()
    def get(path):
        r = http.get(f"{a.site}/data/{path}", timeout=60)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    ptr = get("layers/master/latest.json")
    base = ptr["base"]
    s = get(base + "summary.json")
    problems = check_summary(s)
    h = get(base + "history.json")
    summaries = {e["period"]: get(week_base(get, e["period"]) + "summary.json") for e in h["lists"]}
    problems += check_history(h, summaries)
    problems += check_changes(get(base + "changes.json"), ptr, h)
    sl = get("layers/shortlist/latest.json")
    files = {}
    for g in sl["groups"]:
        for n in range(1, g.get("pages", 1) + 1):
            name = f"{g['key']}.json" if n == 1 else f"{g['key']}.{n}.json"
            files[g["key"]] = files.get(g["key"], 0) + len(get(f"layers/shortlist/{sl['run']}/g/{name}")["rows"])
    problems += check_shortlist(sl, files)
    queue = re.search(r"queue: '([^']+)'", (ROOT / "site" / "assets" / "shortlist.js").read_text()).group(1)
    problems += check_lakh(queue, waiting_all(s))
    gate = list(csv.DictReader((ROOT / "experiments" / "corpus_v0" / "results" / "gate.csv").open()))
    problems += check_method_table((ROOT / "site" / "method.html").read_text(), gate)
    for line in problems:
        print(line)
    print(f"{len(problems)} problems; checked {base}, {len(h['lists'])} lists in the history, shortlist run {sl['run']}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
