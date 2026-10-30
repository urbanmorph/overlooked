"""The lichens of India: Sinha, G.P., Nayaka, S. and Mishra, G.K. (2024). A comprehensive checklist of lichens from
India - 2024. Cryptogam Biodiversity and Assessment 8(2): 1-134. doi:10.21756/cab.v8i2.01. 3,236 taxa.

Licence: CC BY-NC 4.0 (the article page at cbaj.in). We use the names, their endemic mark and their states as facts
for the India list, credit the paper on every page that counts them, and publish only counts (owner's decision,
30 October 2026).

The PDF has a text layer: Table 4 (pages 8 to 132) has one row per taxon: number, name with authority and its
synonyms (after an equals sign), growth form, substratum, state codes, lichenogeographic regions and END
(endemic). A genus written once in full is shortened to its first letter in the rows after it. Columns are read
by position; every second page is set further right, so each page is placed by its growth-form column.

Cache and idempotency: the PDF and the parsed table are kept in data/cache/lichens/ and in R2 cache/lichens/ (never
served); a second run with the same PDF writes the same table and uploads nothing.

Usage: .venv/bin/python -m pipeline.lichens [--publish]
"""

import argparse
import csv
import re
from pathlib import Path

from pipeline.util import log

ROOT = Path(__file__).resolve().parent.parent
URL = "https://cbaj.in/index.php/journal/article/download/247/89"
PAGE = "https://cbaj.in/index.php/journal/article/view/247"
CACHE = ROOT / "data" / "cache" / "lichens"
R2_DIR = "cache/lichens/"
PDF, TABLE = "lichens_india_2024.pdf", "lichen_checklist.csv"
TAXA = 3236                       # the paper's stated total
FIRST_PAGE, LAST_PAGE = 8, 132    # Table 4 (it ends on page 132, before the discussion)
FIELDS = ["no", "name", "authority", "synonyms", "growth_form", "substratum", "states", "regions", "endemic", "page"]
STATES = {
    "AN": "Andaman and Nicobar Islands", "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh", "AS": "Assam",
    "BH": "Bihar", "CH": "Chandigarh", "CG": "Chhattisgarh", "GO": "Goa", "GU": "Gujarat", "HP": "Himachal Pradesh",
    "JK": "Jammu and Kashmir", "JR": "Jharkhand", "KR": "Karnataka", "KL": "Kerala", "LK": "Lakshadweep",
    "MP": "Madhya Pradesh", "MH": "Maharashtra", "MN": "Manipur", "MZ": "Mizoram", "MG": "Meghalaya",
    "NL": "Nagaland", "OD": "Odisha", "PD": "Puducherry", "PU": "Punjab", "RJ": "Rajasthan", "SK": "Sikkim",
    "TN": "Tamil Nadu", "TP": "Tripura", "UP": "Uttar Pradesh", "UK": "Uttarakhand", "WB": "West Bengal"}
# Column starts on page 8 (points); other pages are shifted by their growth-form column's offset.
GF_X = 266
COLUMNS = [("no", 0), ("taxon", 65), ("growth_form", 262), ("substratum", 312), ("states", 362), ("regions", 430),
           ("status", 482)]
GROWTH = {"CR", "FO", "FR"}
TOP_SLACK = 3        # points a word may sit above its row's number
LAST_ROW_PT = 20     # the last row's height at most (two lines): the discussion follows on the same page


def column(x, shift):
    name = COLUMNS[0][0]
    for n, start in COLUMNS:
        if x >= start + shift:
            name = n
    return name


def page_rows(page, nxt):
    """([(number or None, {column: [words]})], the next row number). None: lines that continue the last row of the
    page before. A number starts a row only when it is the next one, so the text after the table (and numbers in it)
    is left out; the last row ends LAST_ROW_PT below its number. Words keep the PDF's own order (block, line, word):
    italic names sit a little off the line, so sorting by height would mix them."""
    words = page.get_text("words")
    gf = sorted(w[0] for w in words if w[4] in GROWTH)
    if not gf:
        return [], nxt
    shift = gf[len(gf) // 2] - GF_X
    title = min((w[1] for w in words if w[4] == "comprehensive"), default=-1)
    words = [w for w in words if w[1] > title + 20]                      # the running title and the page number
    starts = []                                                          # (top, number)
    for w in sorted(words, key=lambda w: w[1]):
        if column(w[0], shift) == "no" and w[4] == str(nxt) and nxt <= TAXA:
            starts.append((w[1], nxt))
            nxt += 1
    rows = {None: {}} | {no: {} for _, no in starts}
    for w in sorted(words, key=lambda w: (w[5], w[6], w[7])):
        col = column(w[0], shift)
        if col == "no" and any(w[4] == str(no) and abs(w[1] - top) < 1 for top, no in starts):
            continue
        row = None
        for top, no in starts:
            if w[1] >= top - TOP_SLACK:
                row = no
        if row == TAXA and w[1] > starts[-1][0] + LAST_ROW_PT:
            continue
        rows[row].setdefault(col, []).append(w[4])
    return [(no, cells) for no, cells in rows.items() if no is not None or cells], nxt


def split_taxon(text, genus):
    """(full name, authority, synonyms) from the taxon cell; a first-letter genus ('A. archeri') takes the genus
    of the row before; so does one written 'C.ryssoleum' or 'P trichothelioides' (two misprints in the table)."""
    name_part, *syn = re.split(r"\s+[≡=]\s+", text.strip())
    m = re.match(r"^([A-Z][a-zë-]+\s+|[A-Z]\.\s*|[A-Z]\s+)([a-zë-]+)((?:\s+(?:var\.|subsp\.|ssp\.|f\.)\s+[a-zë-]+)?)\s*(.*)$", name_part)
    if not m:
        return None, None, None
    g, epithet, infra, author = m.groups()
    g = g.strip()
    if len(g.rstrip(".")) == 1:
        if not genus or genus[0] != g[0]:
            return None, None, None
        g = genus
    return f"{g} {epithet}{infra}".strip(), author.strip(), "; ".join(s.strip() for s in syn)


def codes_in(words):
    """The two-letter codes of a cell (a footnote mark or a stray number is left out)."""
    return " ".join(w for w in words or [] if re.fullmatch(r"[A-Z]{2}", w))


def parse(pdf):
    """The table rows (dicts with FIELDS)."""
    import pymupdf
    doc = pymupdf.open(pdf)
    rows, genus, nxt = [], None, 1
    for n in range(FIRST_PAGE - 1, LAST_PAGE):
        page, nxt = page_rows(doc[n], nxt)
        for no, cells in page:
            if no is None:
                if rows:   # a row that runs on from the page before
                    for col, ws in cells.items():
                        rows[-1]["cells"].setdefault(col, []).extend(ws)
                continue
            rows.append({"no": no, "page": n + 1, "cells": cells})
    out = []
    for r in rows:
        c = r["cells"]
        name, author, syn = split_taxon(" ".join(c.get("taxon", [])), genus)
        if name:
            genus = name.split()[0]
        codes = c.get("states", [])
        out.append({"no": r["no"], "name": name, "authority": author, "synonyms": syn,
                    "growth_form": codes_in(c.get("growth_form")), "substratum": codes_in(c.get("substratum")),
                    "states": ";".join(STATES[s] for s in codes if s in STATES),
                    "regions": codes_in(c.get("regions")), "endemic": "END" in c.get("status", []),
                    "page": r["page"]})
    return out


def check(rows):
    """Problems: numbers not 1..TAXA in order, and rows with no name."""
    problems = []
    nos = [r["no"] for r in rows]
    if nos != list(range(1, TAXA + 1)):
        missing = sorted(set(range(1, TAXA + 1)) - set(nos))
        extra = sorted(set(nos) - set(range(1, TAXA + 1)))
        problems.append(f"{len(nos)} rows; missing {missing[:20]}; not expected {extra[:20]}")
    problems += [f"row {r['no']} (page {r['page']}): no name" for r in rows if not r["name"]]
    return problems


def write(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)
    return path


def run(http, s3=None, cache=CACHE):
    """Fetch (once), parse, check and keep the table; with s3, both files in R2 (uploaded only when changed)."""
    pdf = cache / PDF
    if not pdf.exists():
        cache.mkdir(parents=True, exist_ok=True)
        r = http.get(URL, timeout=300)
        r.raise_for_status()
        tmp = pdf.with_suffix(".part")
        tmp.write_bytes(r.content)
        tmp.replace(pdf)
        log(f"lichens: downloaded {pdf.name} ({pdf.stat().st_size >> 10} KB)")
    rows = parse(pdf)
    problems = check(rows)
    if problems:
        raise SystemExit("lichens: the table did not read cleanly:\n  " + "\n  ".join(problems[:30]))
    table = write(rows, cache / TABLE)
    log(f"lichens: {len(rows)} taxa, {sum(r['endemic'] for r in rows)} endemic, "
        f"{sum(bool(r['states']) for r in rows)} with states")
    if s3:
        from pipeline import r2
        for p in (pdf, table):
            r2.sync_file(s3, p, R2_DIR + p.name, immutable=False)
    return table


def main():
    import requests

    from pipeline import health
    a = argparse.ArgumentParser()
    a.add_argument("--publish", action="store_true", help="keep the PDF and the table in R2 (cache/lichens/)")
    args = a.parse_args()
    http = requests.Session()
    http.headers["User-Agent"] = health.ua()
    s3 = None
    if args.publish:
        from dotenv import load_dotenv

        from pipeline import r2
        load_dotenv(ROOT / ".env", override=True)
        s3 = r2.client()
    run(http, s3)


if __name__ == "__main__":
    main()
