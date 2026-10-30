"""The bryophytes of India: Dandotiya, D., Govindapyari, H., Suman, S. and Uniyal, P.L. (2011). Checklist of the
bryophytes of India. Archive for Bryology 88: 1-126. 2,489 taxa (1,786 mosses, 675 liverworts, 25 hornworts, by the
abstract).

Terms: the PDF on the University of Frankfurt's repository (OPUS) states German copyright (Deutsches Urheberrecht)
and no open licence; the owner cleared it for use on 30 October 2026. We use the names as facts for the India list
and publish only counts.

The PDF has a text layer. Three lists ("LIST OF MOSSES / LIVERWORTS / HORNWORTS FOUND IN INDIA"), each numbered from
1, under "GENUS- X" headings; a row is its number, then the name with the genus shortened to its first letter
("A. flavisetum"; misprints such as "R.. celebicum" and "R.duthiei" read the same), then places and remarks. No
authorities and no states, so only the names are kept; the remarks mix "endemic to India" with endemic to a region,
so no endemic mark is taken. The list ends at the references.

Cache and idempotency: the PDF and the parsed table are kept in data/cache/bryophytes/ and in R2 cache/bryophytes/
(never served); a second run with the same PDF downloads nothing and uploads nothing.

Usage: .venv/bin/python -m pipeline.bryophytes [--publish]
"""

import argparse
import csv
import re
from pathlib import Path

from pipeline.util import log

ROOT = Path(__file__).resolve().parent.parent
URL = ("https://publikationen.ub.uni-frankfurt.de/opus4/frontdoor/deliver/index/docId/35029/file/"
       "088_dandotiya_et_al_2011_checklist_india.pdf")
PAGE = "https://publikationen.ub.uni-frankfurt.de/frontdoor/index/index/year/2014/docId/35029"
CACHE = ROOT / "data" / "cache" / "bryophytes"
R2_DIR = "cache/bryophytes/"
PDF, TABLE = "bryophytes_india_2011.pdf", "bryophyte_checklist.csv"
SECTIONS = {"MOSSES": ("mosses", "Bryophyta"), "LIVERWORTS": ("liverworts", "Marchantiophyta"),
            "HORNWORTS": ("hornworts", "Anthocerotophyta")}
TAXA = {"mosses": 1786, "liverworts": 678, "hornworts": 25}   # the last number of each list
# Numbers the paper itself leaves out (none of them is in its text), per list.
SKIPPED = {"mosses": [519, 1087, 1120, 1324, 1325, 1363], "liverworts": [47, 397, 464, 465, 466, 535]}
# Rows whose shortened genus fits no genus heading above them (the paper leaves the heading out): not guessed.
NO_NAME = {("mosses", 1760), ("liverworts", 212), ("liverworts", 214), ("liverworts", 309)}
FIELDS = ["section", "no", "name", "phylum", "genus", "page", "unnamed"]
HEADING = re.compile(r"LIST OF (MOSSES|LIVERWORTS|HORNWORTS) FOUND IN INDIA")
GENUS = re.compile(r"^GENUS\s*-?\s*([A-Z][a-z]+)?$|^GENUS\s*-?\s*([A-Z][a-z]+)\b")
RUNNING = re.compile(r"^(ARCHIVE FOR BRYOLOGY|ISSN|Bryophytes of India|Dandotiya et al)")   # page headers
UNNAMED = re.compile(r"(^|\s|\.)spp?\.?(\s|$)")
MARKER = re.compile(r"^(var|subsp|ssp|susp|f)\.$")
ROW = re.compile(r"^(\d{1,4})(?:\s+(.*))?$")
# A name: the genus in full or shortened (with stray dots or no space), the epithet, an optional variety or subspecies.
NAME = re.compile(r"^([A-Z][a-z]+\s+|[A-Z]\.+\s*|[A-Z]\s+)([a-z][a-z-]+)(?![a-z.-])((?:\s+(?:var|subsp|ssp|susp|f)\.\s*[a-z][a-z-]+)?)")
AHEAD = 5             # a number up to this far past the next one still starts a row (the paper skips a few)


def name_of(text, genus):
    """'Genus epithet [var. x]' from a row's name line, the genus taken from the heading when it is shortened;
    None when the line is not a name of that genus."""
    text = re.sub(r"^([A-Z])[\s.]*\.[\s.]*(?=[a-z])", r"\1. ", text.strip())   # "E .praelongum", "R.. celebicum", "E. .flavescens"
    text = re.sub(r"(?<=[a-z])\.$", "", text)                                       # "C. umbellatus."
    text = re.sub(r"^(\S+\s+)([A-Z])([a-z-]+)", lambda m: m[1] + m[2].lower() + m[3], text)   # "M. Shimlana"
    m = NAME.match(text)
    if not m or not genus:
        return None
    g, epithet, infra = m.groups()
    g = g.strip().rstrip(".")
    if len(g) == 1:
        if g != genus[0]:
            return None
        g = genus
    infra = re.sub(r"\s+", " ", re.sub(r"\.(?=\S)", ". ", infra.strip())).replace("susp.", "subsp.")
    return f"{g} {epithet}{' ' + infra if infra else ''}"


def name_lines(lines):
    """The name of a row from the lines after its number: a name split over lines ("F.", "hygrometrica", "var.",
    "calvescens") is joined. Returns (text, lines used)."""
    text, used = lines[0], 1
    while used < len(lines):
        last, nxt = text.split()[-1], lines[used]
        if re.fullmatch(r"[A-Z]\.?", text) or MARKER.match(last) or (MARKER.match(nxt) and used + 1 < len(lines)):
            text, used = f"{text} {nxt}", used + 1
        else:
            break
    return text, used


def parse(pdf):
    """Rows {section, no, name, phylum, genus, page} in the order of the paper."""
    import pymupdf
    doc = pymupdf.open(pdf)
    lines = [(n, x.strip()) for n, page in enumerate(doc, start=1) for x in page.get_text().splitlines() if x.strip()]
    rows, section, genus, nxt, i, seen = [], None, None, 1, 0, set()
    while i < len(lines):
        n, line = lines[i]
        i += 1
        h = HEADING.search(line)
        if h:
            section, genus, nxt, seen = SECTIONS[h.group(1)], None, 1, set()
            continue
        if not section:
            continue
        if line.upper().startswith("REFERENCES"):
            break
        if RUNNING.match(line):
            i += 1 if i < len(lines) and lines[i][1].isdigit() else 0      # its page number
            continue
        g = GENUS.match(line)
        if g:
            genus = g.group(1) or g.group(2) or (lines[i][1].split()[0] if i < len(lines) else None)
            i += 0 if g.group(1) or g.group(2) else 1
            continue
        r = ROW.match(line)
        # Only the next numbers start a row (the paper skips a few), or one just behind not read yet (printed late).
        if r and nxt - AHEAD <= int(r.group(1)) <= nxt + AHEAD and int(r.group(1)) not in seen:
            no = int(r.group(1))
            seen.add(no)
            nxt = max(nxt, no + 1)
            row = {"section": section[0], "no": no, "phylum": section[1], "genus": genus, "page": n}
            if r.group(2):
                text = r.group(2)
            else:
                text, used = name_lines([x for _, x in lines[i:i + 6]])
                i += used
            unnamed = bool(UNNAMED.search(text))                          # "Fissidens. sp": a species not named
            rows.append({**row, "name": None if unnamed else name_of(text, genus), "unnamed": unnamed})
    return rows


def check(rows, taxa=None, skipped=None, no_name=None):
    """Problems: per section, the numbers 1..last that were not read (but for those the paper skips), and rows with
    no name (but for those known to be unreadable)."""
    taxa, skipped = TAXA if taxa is None else taxa, SKIPPED if skipped is None else skipped
    no_name = NO_NAME if no_name is None else no_name
    problems = []
    for sec, last in taxa.items():
        nos = sorted(r["no"] for r in rows if r["section"] == sec)   # a row printed late counts
        want = [n for n in range(1, last + 1) if n not in skipped.get(sec, [])]
        if nos != want:
            problems.append(f"{sec}: {len(nos)} rows of {len(want)}; not read {sorted(set(want) - set(nos))[:20]}; "
                            f"not expected {sorted(set(nos) - set(want))[:20]}")
    problems += [f"{r['section']} row {r['no']} (page {r.get('page')}): no name" for r in rows
                 if not r["name"] and not r.get("unnamed") and (r["section"], r["no"]) not in no_name]
    return problems


def write(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows({k: r.get(k) for k in FIELDS} for r in rows)
    tmp.replace(path)
    return path


def run(http, s3=None, cache=CACHE):
    """Fetch (once), parse, check and keep the table; with s3, both files in R2 (uploaded only when changed)."""
    pdf = cache / PDF
    if not pdf.exists():
        cache.mkdir(parents=True, exist_ok=True)
        r = http.get(URL, timeout=300)
        r.raise_for_status()
        if "pdf" not in r.headers.get("Content-Type", "").lower():
            raise SystemExit(f"bryophytes: {URL} did not answer with a PDF (a challenge page?); download it by hand to {pdf}")
        tmp = pdf.with_suffix(".part")
        tmp.write_bytes(r.content)
        tmp.replace(pdf)
        log(f"bryophytes: downloaded {pdf.name} ({pdf.stat().st_size >> 10} KB)")
    rows = parse(pdf)
    problems = check(rows)
    if problems:
        raise SystemExit("bryophytes: the list did not read cleanly:\n  " + "\n  ".join(problems[:30]))
    table = write(rows, cache / TABLE)
    log("bryophytes: " + ", ".join(f"{sum(r['section'] == s for r in rows)} {s}" for s in TAXA))
    if s3:
        from pipeline import r2
        for p in (pdf, table):
            r2.sync_file(s3, p, R2_DIR + p.name, immutable=False)
    return table


def main():
    import requests

    from pipeline import health
    a = argparse.ArgumentParser()
    a.add_argument("--publish", action="store_true", help="keep the PDF and the table in R2 (cache/bryophytes/)")
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
