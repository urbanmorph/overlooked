"""BSI Plant Discoveries: new plant species and new records for India, from BSI's annual reports.

Source and credit (BSI web policy: reproduction free of charge, accurately, with prominent
acknowledgement): Botanical Survey of India. Plant Discoveries <year>. Ministry of Environment,
Forest and Climate Change, Government of India. https://bsi.gov.in

The parser is ported from the fnf project (scripts/06_bsi_plant_discoveries.py). The monthly sync
reads BSI's listing page (1 request), downloads only editions not parsed yet, and keeps parsed
entries in the cache (local data/cache/bsi/, and R2 cache/bsi/), so each PDF is parsed once.

Usage:
    python -m pipeline.bsi listing
    python -m pipeline.bsi sync [--publish] [--seed path/to/fnf/bsi_plant_discoveries.csv]
"""

import csv
import re
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "cache" / "bsi"
REF = ROOT / "pipeline" / "ref"

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
GROUPS = ["SEED PLANTS", "PTERIDOPHYTES", "BRYOPHYTES", "LICHENS", "ALGAE", "FUNGI", "MICROBES"]
GROUP_ALIASES = {"LICHEN": "LICHENS"}
BANNER_GROUP = {g: g for g in GROUPS} | {"LICHEN": "LICHENS", "ANGIOSPERMS": "SEED PLANTS",
                                         "GYMNOSPERMS": "SEED PLANTS", "FUNGUS": "FUNGI", "ALGA": "ALGAE"}
BANNER = re.compile(r"(?:^|/)\s*(" + "|".join(BANNER_GROUP) + r")\s*$", re.I)
GROUP_LINE = re.compile(r"^\s*(?:" + "|".join(GROUPS) + r")\s*$")
RUNNING_HEADERS = re.compile(r"^\s*(Plant Discoveries|\d{1,3}|=====PAGE \d+=====)\s*$")
BODY_START = re.compile(r"^(This|A novel|The (?:fungal |lichen |algal |bryophyte |moss |new )?(species|genus|variety|new|taxon|subspecies|form|family|lichen|fungus|alga|strain))\b")
HEAD_START = re.compile(r"^[A-Z][a-z]+(?:\s+(?:[a-z][a-z-]+|×\s*[a-z][a-z-]+))?\b")
# Family in brackets; 2015 prints it in caps with stray gaps, e.g. "(O RCH ID ACEAE)".
HEAD_END = re.compile(r"\(([A-Z][A-Za-z]*(?:\s[A-Za-z]+){0,12})\)\.?\s*$")
# Some fungi headings omit the family and end with the citation year instead.
YEAR_END = re.compile(r"\b(?:19|20)\d\d\.?\s*$")
IUCN = re.compile(r"\((CR|EN|VU|NT|LC|DD|EX|EW|NE)\)")

STATES = {
    "Andaman": "ANDAMAN & NICOBAR", "Nicobar": "ANDAMAN & NICOBAR",
    "Andhra Pradesh": "ANDHRA PRADESH", "Arunachal Pradesh": "ARUNACHAL PRADESH",
    "Assam": "ASSAM", "Bihar": "BIHAR", "Chandigarh": "CHANDIGARH", "Chhattisgarh": "CHHATTISGARH", "Chhatishgarh": "CHHATTISGARH", "Chattisgarh": "CHHATTISGARH",
    "Dadra": "DADRA,NAGAR HAVELI,DAMAN & DIU", "Daman": "DADRA,NAGAR HAVELI,DAMAN & DIU",
    "Delhi": "DELHI", "Goa": "GOA", "Gujarat": "GUJARAT", "Haryana": "HARYANA",
    "Himachal Pradesh": "HIMACHAL PRADESH", "Jammu": "JAMMU & KASHMIR", "Kashmir": "JAMMU & KASHMIR",
    "Jharkhand": "JHARKHAND", "Karnataka": "KARNATAKA", "Kerala": "KERALA", "Ladakh": "LADAKH",
    "Lakshadweep": "LAKSHADWEEP", "Madhya Pradesh": "MADHYA PRADESH", "Maharashtra": "MAHARASHTRA",
    "Manipur": "MANIPUR", "Meghalaya": "MEGHALAYA", "Mizoram": "MIZORAM", "Nagaland": "NAGALAND",
    "Odisha": "ODISHA", "Orissa": "ODISHA", "Puducherry": "PUDUCHERRY", "Pondicherry": "PUDUCHERRY",
    "Punjab": "PUNJAB", "Rajasthan": "RAJASTHAN", "Sikkim": "SIKKIM", "Tamil Nadu": "TAMIL NADU",
    "Telangana": "TELANGANA", "Tripura": "TRIPURA", "Uttar Pradesh": "UTTAR PRADESH",
    "Uttarakhand": "UTTARAKHAND", "West Bengal": "WEST BENGAL", "Darjeeling": "WEST BENGAL",
}
STATE_RE = re.compile(r"\b(" + "|".join(sorted(STATES, key=len, reverse=True)) + r")\b")
# Herbarium addresses ("deposited in ... Coimbatore, Tamil Nadu (MH)") also name states;
# only look for the collection state before the deposit sentence.
DEPOSIT = re.compile(r"\b(holotype|type|specimens?|isotypes?)\b[^.]*\b(deposited|housed|preserved)\b|\bThe type strain\b", re.I)


def _district_lookup():
    """LGD district name -> state, for names unique to one state (e.g. "Mayurbhanj").
    Ambiguous names (Aurangabad, Bilaspur, Hamirpur, ...) are left out."""
    f = REF / "district_state.csv"
    if not f.exists():
        return {}
    pairs = list(csv.DictReader(open(f)))
    by_name = {}
    for r in pairs:
        by_name.setdefault(r["district"], set()).add(r["state"])
    lookup = {n: next(iter(st)) for n, st in by_name.items() if len(st) == 1 and len(n) >= 5}
    # Old names still used in the reports.
    lookup |= {"Burdwan": "WEST BENGAL", "Gurgaon": "HARYANA", "Allahabad": "UTTAR PRADESH"}
    return lookup


DISTRICTS = _district_lookup()
DISTRICT_RE = re.compile(r"\b(" + "|".join(map(re.escape, sorted(DISTRICTS, key=len, reverse=True))) + r")\b") if DISTRICTS else None


def collection_states(body):
    """States named where the collection is described: the first two sentences,
    stopping at the deposit / type-strain sentence (herbarium and culture
    collection addresses also name states)."""
    text = DEPOSIT.split(body)[0]
    text = " ".join(re.split(r"(?<=[a-z)]\.)\s+(?=[A-Z])", text)[:2])
    text = re.sub(r"\bDelhi Village\b", "", text)          # Katchal Island, Andaman & Nicobar
    # PDF text glitches: "W est Bengal", "West Bengalat an altitude"
    text = re.sub(r"\bW est\b", "West", text)
    text = re.sub(r"\b(Bengal|Pradesh|Kerala|Sikkim|Assam|Nadu|Karnataka|Maharashtra)(at|in)\b", r"\1 \2", text)
    found = list(dict.fromkeys(STATES[m] for m in STATE_RE.findall(text)))
    if "CHANDIGARH" in found and re.search(r"Chandigarh,?\s+Punjab", text):
        found.remove("PUNJAB") if "PUNJAB" in found else None  # older usage "Chandigarh, Punjab"
    if not found and DISTRICT_RE:
        found = list(dict.fromkeys(DISTRICTS[m] for m in DISTRICT_RE.findall(text)))
    return found


def page_text(page, cache_dir):
    """Text layer if present, else Tesseract OCR (English) cached per page."""
    text = page.get_text()
    if text.strip():
        return text, False
    cached = cache_dir / f"p{page.number + 1:04d}.txt"
    if not cached.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        tp = page.get_textpage_ocr(language="eng", dpi=300, full=True)
        cached.write_text(page.get_text(textpage=tp))
    return cached.read_text(), True


def english_lines(pdf_path):
    group = None
    ocr_cache = SRC / "ocr" / Path(pdf_path).stem
    for page in pymupdf.open(pdf_path):
        text, ocr = page_text(page, ocr_cache)
        for line in text.splitlines():
            line = line.strip()
            # OCR of the scanned 2023 report scatters short junk lines (Hindi glyphs,
            # image specks) between real lines; keep only substantive ones.
            if ocr and len(line) < 25 and not (HEAD_END.search(line) or YEAR_END.search(line) or BANNER.search(line)):
                continue
            if not line or DEVANAGARI.search(line):
                # Group banners are bilingual ("बीजीय पौधे / SEED PLANTS"); keep the English part.
                m = re.search(r"(" + "|".join(GROUPS) + r"|LICHEN)S?\s*$", line)
                if m:
                    group = GROUP_ALIASES.get(m.group(1), m.group(1))
                continue
            # Banners: "SEED PLANTS", "dod/Fungi" (2020's legacy-font Hindi turns into Latin junk)
            m = BANNER.search(line)
            if m:
                group = BANNER_GROUP[m.group(1).upper()]
                continue
            m = re.match(r"^NUMBER OF (\w+)", line)  # section opener, e.g. "NUMBER OF LICHEN AND ..."
            if m:
                g = m.group(1).rstrip("S") + "S" if m.group(1) != "SEED" else "SEED PLANTS"
                group = GROUP_ALIASES.get(m.group(1), g if g in GROUPS else group)
            if RUNNING_HEADERS.match(line):
                continue
            yield line, group


NAME = re.compile(r"([A-Z][a-z]+)(?:\s+(×?\s*[a-z][a-z-]+))?(?:\s+(var|subsp|f)\.\s+([a-z][a-z-]+))?")
# Genera from Kew WCVP + the GBIF India download (built once; see README). New genera
# described in the reports won't be here, so the check is a preference, not a filter.
KNOWN_GENERA_FILE = REF / "known_genera.txt"
KNOWN_GENERA = set(KNOWN_GENERA_FILE.read_text().split()) if KNOWN_GENERA_FILE.exists() else set()
NOT_EPITHET = {"of", "de", "in", "at", "and", "from", "the", "et", "ex", "for", "to", "on", "by", "with", "near"}
NOT_GENUS = {"The", "This", "These", "It", "In", "A", "An", "Its", "Dr", "Prof", "Mr", "Mrs", "Ms", "Shri"}


def find_heading(text):
    """Return (heading, name) for the entry heading at the end of `text`, or None.

    The text before a body can include the tail of the previous entry, so the
    heading starts at the latest sentence boundary followed by a binomial
    (Genus epithet); failing that, the latest one followed by a capitalised
    word (a new genus, e.g. "Kanjilalia Sanjappa & Pusalkar, ... (Fabaceae)").
    """
    if not (HEAD_END.search(text) or YEAR_END.search(text)):
        return None
    sentence_starts = [0] + [m.end() for m in re.finditer(r"[.)]\s+", text)]
    # Fallback for source typos (a missing full stop before the name): any word start.
    word_starts = [m.start() for m in re.finditer(r"\b[A-Z]", text)]
    passes = [(sentence_starts, True, True), (word_starts, True, True),
              (sentence_starts, True, False), (sentence_starts, False, False)]
    for starts, need_epithet, need_known in passes:
        for st in reversed(starts):
            m = NAME.match(text, st)
            if not m or m.group(1) in NOT_GENUS:
                continue
            if need_known and KNOWN_GENERA and m.group(1) not in KNOWN_GENERA:
                continue
            if need_epithet and (not m.group(2) or m.group(2) in NOT_EPITHET):
                continue
            name = " ".join(x for x in (m.group(1), m.group(2)) if x)
            if m.group(3):
                name += f" {m.group(3)}. {m.group(4)}"
            return text[st:].strip(), name
    return None


def parse(pdf_path, year):
    lines = list(english_lines(pdf_path))
    starts = [i for i, (l, _) in enumerate(lines) if BODY_START.match(l)]
    entries = []
    prev_body_start = -1
    for k, i in enumerate(starts):
        lo = max(prev_body_start + 1, i - 7)
        head = find_heading(" ".join(l for l, _ in lines[lo:i]))
        if head is None:
            continue
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        # The next entry's header lines belong to the next entry, not this body.
        body_lines = [l for l, _ in lines[i:end]]
        while body_lines and not re.search(r"[.)]\s*$", body_lines[-1]):
            body_lines.pop()
        body = re.sub(r"\s+", " ", " ".join(body_lines))
        name_part, name = head
        fam = HEAD_END.search(name_part)
        family = fam.group(1) if fam else ""
        if family.replace(" ", "").isupper():
            family = family.replace(" ", "").capitalize()
        states = collection_states(body)
        iucn = IUCN.findall(body)
        kind = ("new_record" if re.search(r"earlier known|reported for the first time|new record", body, re.I)
                else "new_to_science")
        rank = "genus" if " " not in name else ("infraspecific" if re.search(r"\s(var|subsp|f)\.\s", name) else "species")
        genus, _, epithet = name.partition(" ")
        epithet = epithet.split(" ")[0]
        if genus in KNOWN_GENERA:
            name_check = "ok"
        elif epithet and epithet not in NOT_EPITHET | {"is", "distributed"} and len(genus) > 3 and len(epithet) > 3:
            name_check = "unknown_genus"   # often a genuinely new genus; verify
        else:
            name_check = "needs_review"    # author surname, sentence fragment or OCR junk
        entries.append({
            "year": year, "name_check": name_check, "group": lines[i][1], "kind": kind, "rank": rank, "name": name,
            "heading": name_part, "family": family, "states": "; ".join(states),
            "iucn_proposed": iucn[-1] if iucn else "", "text": body,
            "source": f"Botanical Survey of India, Plant Discoveries {year}",
        })
        prev_body_start = i
    return entries



LISTING = "https://bsi.gov.in/page/en/national-wild-life-action-plan"  # BSI's "Plant discoveries" page
FIRST_YEAR = 2015


def listing(http):
    """PDF links on BSI's Plant Discoveries page, by year. Several files per year are possible."""
    import html
    r = http.get(LISTING, timeout=90)
    r.raise_for_status()
    if "text/html" not in r.headers.get("Content-Type", ""):
        raise RuntimeError("BSI listing page did not return HTML")
    links = {}
    for href in re.findall(r'href="([^"]+\.pdf)"', r.text, re.I):
        href = html.unescape(href)
        m = re.search(r"Plant[ _%20]*Discover[a-z]*[^/]*?((?:19|20)\d\d)", href, re.I)
        if m:
            from urllib.parse import urljoin
            url = urljoin(LISTING, href).replace(" ", "%20")
            if url not in links.get(int(m.group(1)), []):
                links.setdefault(int(m.group(1)), []).append(url)
    return links


def cache_file(year):
    return SRC / f"plant_discoveries_{year}.json"


def seed_from_csv(path):
    """Fill the cache from an earlier parse (same parser), one file per year."""
    import json
    rows = list(csv.DictReader(open(path)))
    years = sorted({int(r["year"]) for r in rows})
    SRC.mkdir(parents=True, exist_ok=True)
    for y in years:
        cache_file(y).write_text(json.dumps([r for r in rows if int(r["year"]) == y], ensure_ascii=False))
    return years


def download(http, url, dest):
    with http.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        if "pdf" not in r.headers.get("Content-Type", "").lower():
            return False  # BSI answers missing files with its home page (HTTP 200)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return True


def sync(http, s3=None):
    """Parse every edition from FIRST_YEAR that is not in the cache. Returns {year: entries}."""
    import json
    from pipeline import r2
    SRC.mkdir(parents=True, exist_ok=True)
    links = listing(http)
    out = {}
    for year in sorted(y for y in links if y >= FIRST_YEAR):
        f = cache_file(year)
        if not f.exists() and s3 is not None:
            obj = r2.get_json(s3, f"cache/bsi/{f.name}")
            if obj is not None:
                f.write_text(json.dumps(obj, ensure_ascii=False))
        if not f.exists():
            # Prefer the larger file when a year has two (BSI posts a full and a short version).
            best = None
            for url in links[year]:
                pdf = SRC / f"Plant Discoveries {year}.pdf"
                if download(http, url, pdf) and (best is None or pdf.stat().st_size > best[1]):
                    best = (url, pdf.stat().st_size)
                    pdf.rename(SRC / f"Plant Discoveries {year} best.pdf")
            if best is None:
                print(f"{year}: no PDF could be downloaded; kept for the next run")
                continue
            entries = parse(SRC / f"Plant Discoveries {year} best.pdf", year)
            f.write_text(json.dumps(entries, ensure_ascii=False))
            print(f"{year}: parsed {len(entries)} entries from {best[0]}")
        if s3 is not None:
            r2.sync_file(s3, f, f"cache/bsi/{f.name}", immutable=False)
        out[year] = json.loads(f.read_text())
    return out


def main():
    import argparse
    import json
    from pipeline import health
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["listing", "sync"])
    p.add_argument("--publish", action="store_true")
    p.add_argument("--seed")
    a = p.parse_args()
    import requests
    http = requests.Session()
    http.headers["User-Agent"] = health.ua()
    if a.cmd == "listing":
        print(json.dumps(listing(http), indent=1))
        return
    if a.seed:
        print("seeded years:", seed_from_csv(a.seed))
    s3 = None
    if a.publish:
        from dotenv import load_dotenv
        from pipeline import r2
        load_dotenv(ROOT / ".env", override=True)
        s3 = r2.client()
    res = sync(http, s3)
    print({y: len(v) for y, v in res.items()})


if __name__ == "__main__":
    main()
