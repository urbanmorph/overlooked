"""BSI's free regional and family books on lichens, algae and fungi: the species they treat, as names for the India
list (source BSI). BSI has no free national checklist for these groups (October 2026); these books cover a region
(Sikkim, Dehradun) or a group (Meliolales, Hymenochaetaceae, Russulaceae, marine algae).

Credit (BSI web policy: reproduction free of charge, accurately, with prominent acknowledgement): Botanical Survey of
India, Ministry of Environment, Forest and Climate Change, Government of India. https://bsi.gov.in

The books are scans; pipeline.bsi_checklist downloads them and reads them with OCR (cached locally and in R2
cache/bsi/checklists/, saved every 10 minutes, a stopped run continues). They are descriptive monographs, not
checklists, so names are taken from the lines that start a species account and then checked with GBIF's name match:
only a name GBIF knows as a species (exact, or a close spelling of it) is kept, under GBIF's spelling, so OCR misreads
do not reach the list. Every name and its check are written for review.

Output: data/bsi/bsi_monographs.csv (pipeline.bsi_checklist FIELDS) and bsi_monographs_qc.csv; R2 cache/bsi/.

Usage: .venv/bin/python -m pipeline.bsi_monographs [--publish] [--minutes N] [--only KEY ...]
"""

import re
import time
from urllib.parse import quote

from pipeline.bsi_checklist import BOOKS

MONOGRAPHS = [
    {"key": "macrolichens_sikkim", "group": "lichens", "url": BOOKS + quote("Macrolichens of Sikkim.pdf"),
     "title": "Macrolichens of Sikkim", "states": "Sikkim"},
    {"key": "algae_dehradun", "group": "algae", "url": BOOKS + quote("Algal Flora of Dehradun District, Uttaranchal.pdf"),
     "title": "Algal Flora of Dehradun District, Uttaranchal", "states": "Uttarakhand"},
    {"key": "phycologia_indica_1", "group": "algae", "url": BOOKS + quote("Phycologia Indica.pdf"),
     "title": "Phycologia Indica (Icones of Indian Marine Algae), Volume 1", "states": ""},
    {"key": "phycologia_indica_2", "group": "algae",
     "url": BOOKS + quote("Phycologia Indica (Icones of Indian Marine Algae) vol 2.pdf"),
     "title": "Phycologia Indica (Icones of Indian Marine Algae), Volume 2", "states": ""},
    {"key": "meliolales", "group": "fungi", "url": BOOKS + quote("Meliolales of India.pdf"),
     "title": "Meliolales of India", "states": ""},
    {"key": "hymenochaetaceae", "group": "fungi", "url": BOOKS + quote("Hymenochaetaceae of India.pdf"),
     "title": "Hymenochaetaceae of India", "states": ""},
    {"key": "russulaceae_kumaon", "group": "fungi", "url": BOOKS + quote("Russulaceae of Kumaon Himalaya.pdf"),
     "title": "Russulaceae of Kumaon Himalaya", "states": "Uttarakhand"},
]


def ocr_all(publish=False, minutes=None, only=None):
    """Download and OCR every book (or those in only); returns {key: pages}, without the books the time limit
    stopped."""
    import requests

    from pipeline import bsi_checklist as bc
    from pipeline import health, r2
    from pipeline.util import log
    s3 = None
    if publish:
        from dotenv import load_dotenv
        load_dotenv(bc.ROOT / ".env", override=True)
        s3 = r2.client()
    http = requests.Session()
    http.headers["User-Agent"] = health.ua()
    deadline = time.monotonic() + minutes * 60 if minutes is not None else None
    books = {}
    for spec in [m for m in MONOGRAPHS if not only or m["key"] in only]:
        bc.fetch_pdf(http, spec, s3)
        left = None if deadline is None else max(0, (deadline - time.monotonic()) / 60)
        pages = bc.ocr(spec, s3, left)
        if pages is None:
            log("stopped at the time limit; run again to continue")
            break
        log(f"{spec['key']}: {len(pages)} pages read")
        books[spec["key"]] = pages
    return books, s3, http


# A line that starts a species account: an optional number, Genus epithet (or both in capitals), an optional
# infraspecific part, then an author (a capital letter or an opening bracket).
ACCOUNT = re.compile(r"^\s*(?:\d+\.\s*)?([A-Z][a-z]{2,}|[A-Z]{3,})\s+([a-z]{3,}|[A-Z]{3,})"
                     r"((?:\s+(?:var|subsp|f)\.\s+[a-z]{3,}))?\s+[(A-Z]")
KINGDOMS = {"lichens": {"Fungi"}, "fungi": {"Fungi"}, "algae": {"Plantae", "Chromista", "Bacteria", "Protozoa"}}
SPECIES_RANKS = {"SPECIES", "SUBSPECIES", "VARIETY", "FORM"}
MIN_CONFIDENCE = 90
MATCH = "https://api.gbif.org/v1/species/match"


def candidates(lines):
    """Names (Genus epithet [var. x]) from the lines that start a species account, in order, once each."""
    out = []
    for line in lines:
        m = ACCOUNT.match(line)
        if m:
            g, e, infra = m.groups()
            name = f"{g.capitalize()} {e.lower()}{(infra or '').lower()}"
            if name not in out:
                out.append(name)
    return out


def verify(names, group, http, cache, pause=1.0, save=None):
    """[(name as read, GBIF's name or None, the match)]: kept when GBIF matches it to a species-rank name of the
    book's kingdom, exactly or with a close spelling (confidence MIN_CONFIDENCE or more). cache: {name: match},
    filled as answers arrive; save() is called every 100 new answers."""
    out, new = [], 0
    for name in names:
        if name not in cache:
            r = http.get(MATCH, params={"name": name, "strict": "true"}, timeout=60)
            r.raise_for_status()
            cache[name] = r.json()
            new += 1
            if save and new % 100 == 0:
                save()
            time.sleep(pause)
        m = cache[name]
        ok = (m.get("matchType") in ("EXACT", "FUZZY") and m.get("rank") in SPECIES_RANKS
              and m.get("kingdom") in KINGDOMS[group] and (m.get("confidence") or 0) >= MIN_CONFIDENCE)
        out.append((name, m.get("canonicalName") if ok else None, m))
    return out


def book_rows(spec, pages, checked):
    """Rows (pipeline.bsi_checklist FIELDS) for one book: each name GBIF confirmed, once, at its first page."""
    rows, seen = [], set()
    for n in sorted(pages, key=int):
        for name in candidates(t for *_, t in pages[n]["lines"]):
            gbif = checked.get(name)
            if gbif and gbif not in seen:
                seen.add(gbif)
                rows.append({"source": "BSI", "checklist": spec["title"], "group": spec["group"], "name": gbif,
                             "rank": "species", "status": "accepted", "states": spec["states"], "page": int(n),
                             "edition": "Botanical Survey of India", "url": spec["url"]})
    return rows


def run(publish=False, minutes=None, only=None):
    import json

    from pipeline import bsi_checklist as bc
    from pipeline import r2
    from pipeline.util import log
    books, s3, http = ocr_all(publish, minutes, only)
    match_file = bc.CACHE / "monograph_gbif_match.json"
    match_key = f"{bc.R2_DIR}/checklists/{match_file.name}"
    cache = json.loads(match_file.read_text()) if match_file.exists() else (r2.get_json(s3, match_key) if s3 else None) or {}

    def save():
        match_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = match_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False))
        tmp.replace(match_file)
        if s3 is not None:
            r2.sync_file(s3, match_file, match_key, immutable=False)

    rows, qc = [], []
    try:
        for spec in MONOGRAPHS:
            if spec["key"] not in books:
                continue
            pages = books[spec["key"]]
            names = candidates(t for n in sorted(pages, key=int) for *_, t in pages[n]["lines"])
            checks = verify(names, spec["group"], http, cache, save=save)
            book = book_rows(spec, pages, {c: g for c, g, _ in checks if g})
            qc += [{"checklist": spec["title"], "ocr_name": c, "name": g or "", "match": m.get("matchType"),
                    "kept": bool(g)} for c, g, m in checks]
            log(f"{spec['key']}: {len(names)} names read, {len(book)} species kept")
            rows += book
    finally:
        save()
    if len(books) < len([m for m in MONOGRAPHS if not only or m["key"] in only]):
        log("not every book is read yet; the table is not written")
        return 1
    out, qc_out = bc.OUT / "bsi_monographs.csv", bc.OUT / "bsi_monographs_qc.csv"
    bc.write_csv(rows, out)
    bc.write_csv(qc, qc_out, ["checklist", "ocr_name", "name", "match", "kept"])
    log(f"{len(rows)} species from {len(books)} books -> {out}")
    if s3 is not None:
        for f in (out, qc_out):
            log(f"{f.name}: {'uploaded' if r2.sync_file(s3, f, f'{bc.R2_DIR}/{f.name}', immutable=False) else 'unchanged in R2'}")
    return 0


def main():
    import argparse
    import sys
    p = argparse.ArgumentParser()
    p.add_argument("--publish", action="store_true", help="read and write the R2 cache, keep the table in R2")
    p.add_argument("--minutes", type=float, help="stop cleanly after this time")
    p.add_argument("--only", nargs="*", help="book keys")
    a = p.parse_args()
    sys.exit(run(a.publish, a.minutes, a.only))


if __name__ == "__main__":
    main()
