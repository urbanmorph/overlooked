"""BSI Plant Discoveries: new plant species and new records for India, from BSI's annual reports.

Source and credit (BSI web policy: reproduction free of charge, accurately, with prominent
acknowledgement): Botanical Survey of India. Plant Discoveries <year>. Ministry of Environment,
Forest and Climate Change, Government of India. https://bsi.gov.in

The parser is ported from the fnf project (scripts/06_bsi_plant_discoveries.py). Three layouts: 2007-2012
are lists of names with citations (list_entries); 2013-2014 and 2015+ have a description per taxon (parse),
with 2013-2014 mostly scanned (OCR, resumable: ocr). The monthly sync
reads BSI's listing page (1 request), downloads only editions not parsed yet, and keeps parsed
entries in the cache (local data/cache/bsi/, and R2 cache/bsi/), so each PDF is parsed once.

Usage:
    python -m pipeline.bsi listing
    python -m pipeline.bsi sync [--publish] [--minutes N] [--seed path/to/fnf/bsi_plant_discoveries.csv]
"""

import csv
import re
from pathlib import Path

import pymupdf

from pipeline import util
from pipeline.util import log

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "cache" / "bsi"
REF = ROOT / "pipeline" / "ref"

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
GROUPS = ["SEED PLANTS", "PTERIDOPHYTES", "BRYOPHYTES", "LICHENS", "ALGAE", "FUNGI", "MICROBES"]
GROUP_ALIASES = {"LICHEN": "LICHENS"}
BANNER_GROUP = {g: g for g in GROUPS} | {"LICHEN": "LICHENS", "ANGIOSPERMS": "SEED PLANTS",
                                         "GYMNOSPERMS": "SEED PLANTS", "FUNGUS": "FUNGI", "ALGA": "ALGAE"}
BANNER = re.compile(r"(?:^|/)\s*(" + "|".join(BANNER_GROUP) + r")\s*$", re.I)
RUNNING_HEADERS = re.compile(r"^\s*(Plant Discoveries|\d{1,3}|=====PAGE \d+=====)\s*$")
BODY_START = re.compile(r"^(This|A novel|The (?:fungal |lichen |algal |bryophyte |moss |new )?(species|genus|variety|new|taxon|subspecies|form|family|lichen|fungus|alga|strain))\b")
# Family in brackets; 2015 prints it in caps with stray gaps, e.g. "(O RCH ID ACEAE)".
HEAD_END = re.compile(r"\(([A-Z][A-Za-z]*(?:\s[A-Za-z]+){0,12})\)\.?\s*$")
# Some fungi headings omit the family and end with the citation year instead.
YEAR_END = re.compile(r"\b(?:19|20)\d\d\.?\s*$")
# "reported for the first time"; 2013-2014 also "reported from India for the first time", "first time reported".
NEW_RECORD = re.compile(r"earlier known|reported (?:from \w+ )?for the first time|first time reported|new record", re.I)
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



def tesseract(page):
    """Tesseract OCR (English) of one page at 300 dpi."""
    return page.get_text(textpage=page.get_textpage_ocr(language="eng", dpi=300, full=True))


def ocr_dir(pdf_path):
    return SRC / "ocr" / Path(pdf_path).stem


def page_file(page):
    return f"p{page.number + 1:04d}.txt"


def page_text(page, cache_dir):
    """Text layer if present, else Tesseract OCR (English) cached per page."""
    text = page.get_text()
    if text.strip():
        return text, False
    cached = cache_dir / page_file(page)
    if not cached.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(tesseract(page))
    return cached.read_text(), True


SAVE_EVERY = 600  # seconds between saves of OCR progress to R2


def ocr(pdf_path, s3=None, minutes=None, ocr_page=None):
    """OCR every page without a text layer that is not cached yet. Each page is written to
    data/cache/bsi/ocr/<pdf stem>/ as it is done; the pages also go to R2 as one JSON file
    (cache/bsi/ocr/<pdf stem>.json) every SAVE_EVERY seconds and on exit, also when the run fails.
    A new run first restores pages from R2. Returns True when every page is done, False when the
    time limit (minutes) stopped it."""
    import json
    import tempfile
    import time
    from pipeline import r2
    ocr_page = ocr_page or tesseract
    d = ocr_dir(pdf_path)
    key = f"cache/bsi/ocr/{d.name}.json"
    remote = (r2.get_json(s3, key) if s3 is not None else None) or {}
    for name, text in remote.items():
        if not (d / name).exists():
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(text)
    doc = pymupdf.open(pdf_path)
    todo = [p.number for p in doc if not (d / page_file(p)).exists() and not p.get_text().strip()]
    if todo:
        log(f"{d.name}: OCR {len(todo)} scanned pages")
    deadline = time.monotonic() + minutes * 60 if minutes is not None else None
    next_save, dirty = time.monotonic() + SAVE_EVERY, False

    def save():
        if s3 is None or not d.exists():
            return
        pages = {f.name: f.read_text() for f in sorted(d.glob("p*.txt"))}
        if pages == remote:
            return
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / f"{d.name}.json"
            f.write_text(json.dumps(pages, ensure_ascii=False))
            r2.sync_file(s3, f, key, immutable=False)
        remote.clear()
        remote.update(pages)

    try:
        for i, n in enumerate(todo):
            if deadline is not None and time.monotonic() > deadline:
                log(f"{d.name}: time limit, {len(todo) - i} pages left for the next run")
                return False
            page = doc[n]
            text = ocr_page(page)
            d.mkdir(parents=True, exist_ok=True)
            (d / page_file(page)).write_text(text)
            dirty = True
            if (i + 1) % 10 == 0:
                log(f"{d.name}: OCR {i + 1}/{len(todo)} pages")
            if time.monotonic() > next_save:
                save()
                next_save, dirty = time.monotonic() + SAVE_EVERY, False
    finally:
        if dirty:
            save()
    return True


def english_lines(pdf_path):
    group = None
    ocr_cache = ocr_dir(pdf_path)
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
NOT_EPITHET = {"of", "de", "in", "at", "and", "from", "the", "et", "ex", "for", "to", "on", "by", "with", "near",
               # words after a place or a sentence start ("India based on", "Many more are", "State wise")
               "based", "district", "during", "has", "having", "while", "spanning", "through", "together",
               "more", "wise", "this", "laboratory", "subsp", "var", "is", "are", "was"}
NOT_GENUS = {"The", "This", "These", "It", "In", "A", "An", "Its", "Dr", "Prof", "Mr", "Mrs", "Ms", "Shri",
             # Places and words that start sentences of a description; India, Kerala, Odisha and Karnataka
             # are also genus names elsewhere ("India based on the collection made ...").
             "India", "Holotype", "West", "East", "North", "South", "Western", "Eastern", "Central", "Southern",
             "Northern", "Botanical", "Herbarium", "National", "Survey", "Department", "University", "Mycology",
             "Many", "State", "Using", "As", "Led"} | {w for s in STATES for w in s.split()}
# A description sentence before any citation year or family: the tail of the previous entry's description
# ("India based on the collection made ... deposited in ... (CAL)."), not a heading.
DESCRIPTION = re.compile(r"\b(?:deposited|holotype|isotypes?|collections? made)\b", re.I)
CITED = re.compile(r"\b(?:19|20)\d\d\b|\([A-Z][A-Za-z]*(?:aceae|ACEAE)\)")


def find_heading(text, line_starts=()):
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
    # Junk before a heading (OCR, section introductions) often has no full stop: line starts.
    passes = [(sentence_starts, True, True), (word_starts, True, True),
              (sentence_starts, True, False), (line_starts, True, False), (line_starts, False, False),
              (sentence_starts, False, False)]
    for starts, need_epithet, need_known in passes:
        for st in reversed(starts):
            m = NAME.match(text, st)
            if not m or m.group(1) in NOT_GENUS:
                continue
            if not need_epithet and text[m.end():m.end() + 1] == ".":
                continue   # a journal abbreviation ("Nordic J. Bot.31: 162"), not a genus
            cited = CITED.search(text, st)
            if DESCRIPTION.search(text, st, cited.start() if cited else len(text)):
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


# 2013-2014 (mostly scanned, bilingual) differ from 2015+: microbe descriptions start "A Gram-stain-negative
# ...", the "T" of type strains is a superscript on its own line, and a variety's name has the species
# author before "var.".
EARLY_PROSE_LAST = 2014
EARLY_BODY_START = re.compile(BODY_START.pattern + r"|^An? [^.]{0,60}\b(?:[Gg]ram|bacteri|rod.shaped|strain)")


def entry(year, name, group, kind, heading, family, states=(), iucn="", text=""):
    rank = "genus" if " " not in name else ("infraspecific" if re.search(r"\s(var|subsp|f)\.\s", name) else "species")
    genus, _, epithet = name.partition(" ")
    epithet = epithet.split(" ")[0]
    if genus in NOT_GENUS or epithet in NOT_EPITHET:
        name_check = "needs_review"    # a sentence fragment ("India based on ...")
    elif genus in KNOWN_GENERA:
        name_check = "ok"
    elif epithet and epithet != "distributed" and len(genus) > 3 and len(epithet) > 3:
        name_check = "unknown_genus"   # often a genuinely new genus; verify
    else:
        name_check = "needs_review"    # author surname, sentence fragment or OCR junk
    return {
        "year": year, "name_check": name_check, "group": group, "kind": kind, "rank": rank, "name": name,
        "heading": heading, "family": family, "states": "; ".join(states),
        "iucn_proposed": iucn, "text": text,
        "source": f"Botanical Survey of India, Plant Discoveries {year}",
    }


# ---------- 2007-2012: lists of names with citations, no descriptions ----------

LIST_LAYOUT_LAST = 2012
LIST_GROUPS = {"flowering plants": "SEED PLANTS", "seed plants": "SEED PLANTS", "seed plant": "SEED PLANTS",
               "ferns and fern-allies": "PTERIDOPHYTES", "ferns and fern allies": "PTERIDOPHYTES",
               "ferns and fern": "PTERIDOPHYTES", "ferns": "PTERIDOPHYTES", "pteridophytes": "PTERIDOPHYTES",
               "bryophytes": "BRYOPHYTES", "lichens": "LICHENS", "lichens & algae": "LICHENS",
               "fungi": "FUNGI", "algae": "ALGAE", "microbes": "MICROBES"}
# Section headings: "New Species (Seed Plant)", "NEW DISTRIBUTIONAL RECORDS", "GENUS", "Forma (Seed Plant)".
SECTION = re.compile(r"^(?=[A-Z])(?i:(?:new\s+)?(?:genus|genera|species|subspecies|variet|forma|records?|distribut|notho|infra|to science)\w*)\b[^0-9]{0,60}$")
# Some group banners are images; the group's introduction then opens it ("Ferns (Pteridophytes) live ...").
GROUP_INTRO = re.compile(r"^(?:The\s+)?(Ferns|Bryophytes|Lichens|Fungi|Algae|Microbes)\b(?!\s*[:&])")
# The family in brackets: "(ERICACEAE)", "(HEPATICAE: GEOCALYCACEAE)", "(LEGUMINOSAE-PAPILIONOIDEAE)",
# "(]UNCACEAE)" (a misprinted J), "(RAM ALIN ACEAE)", "(Cyperaceae)".
CAPS_FAMILY = re.compile(r"\((\]?[A-Z][A-Z][A-Za-z \-:]{2,}|[A-Z][a-z]+aceae)\)")
LIST_NAME = re.compile(r"([A-Z][a-z][a-zI]*)\s+(?:(×|x)\s*)?([a-z][a-z-]+)")
LIST_GENUS = re.compile(r"([A-Z][a-z]+|[A-Z]{4,})\s+(?=[A-Z(])")
INFRA = re.compile(r"\s(?:notho)?(var|subsp|ssp|forma|f)\.?\s+([a-z][a-z-]{2,})")
# The citation year ends an entry: "2008.", "2007 [2008].", "1.2007 (publ. 2008)."
CITATION_END = re.compile(r"\b(?:19|20)\d\d\s*[\])]?\.?\s*$")


def page_lines(page):
    """Lines of a page rebuilt from its words. Some editions print headings and names in fake bold
    (the same text drawn several times, slightly offset); each word is kept once (its longest copy)."""
    kept = []
    for w in sorted(page.get_text("words"), key=lambda w: w[0] - w[2]):
        if not any(abs(k[1] - w[1]) < 3 and min(k[2], w[2]) - max(k[0], w[0]) > 0.5 * (w[2] - w[0]) for k in kept):
            kept.append(w)
    lines, y = [], None
    for w in sorted(kept, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        mid = (w[1] + w[3]) / 2
        if not lines or abs(mid - y) > 3:
            lines.append([])
            y = mid
        lines[-1].append(w)
    return [" ".join(w[4] for w in sorted(ln, key=lambda w: w[0])) for ln in lines]


def list_name(text, genus_section):
    """The name an entry starts with ("Genus epithet [var. x]"), or None for a non-entry line."""
    if genus_section:
        m = LIST_GENUS.match(text)
        return m.group(1).capitalize() if m and m.group(1).capitalize() not in NOT_GENUS else None
    m = LIST_NAME.match(text)
    if not m or m.group(1) in NOT_GENUS or m.group(3) in NOT_EPITHET:
        return None
    name = f"{m.group(1)} × {m.group(3)}" if m.group(2) else f"{m.group(1)} {m.group(3)}"
    fam = CAPS_FAMILY.search(text)
    for inf in INFRA.finditer(text[:fam.start()] if fam else text):
        if inf.group(2) not in {"var", "subsp", "ssp", "forma"}:
            marker = {"forma": "f", "ssp": "subsp"}.get(inf.group(1), inf.group(1))
            return f"{name} {marker}. {inf.group(2)}"
    return name


def complete(text):
    """An entry is complete once it ends with its citation year or its family."""
    return bool(CITATION_END.search(text) or re.search(CAPS_FAMILY.pattern + r"\.?\s*$", text))


def list_family(text):
    m = CAPS_FAMILY.search(text)
    if not m:
        return ""
    parts = [p.replace(" ", "") for p in re.split(r"[:\-]", m.group(1).replace("]", "J"))]
    return next((p for p in parts if p.upper().endswith("ACEAE")), parts[0]).capitalize()


def list_entries(lines, year):
    """Entries of the 2007-2012 editions: one heading per taxon ("Name Author, citation. (FAMILY)"),
    under section headings for the kind (new to science / new record), rank and plant group."""
    entries, cur, seen = [], [], set()
    group, kind, genus_section = None, "new_to_science", False

    def flush():
        text = re.sub(r"\s+", " ", " ".join(cur)).strip()
        cur.clear()
        name = list_name(text, genus_section)
        if name and complete(text) and name not in seen:
            seen.add(name)
            entries.append(entry(year, name, group, kind, text, list_family(text)))

    for line in lines:
        line = line.strip(" •\t")
        if not line or re.fullmatch(r"\d{1,3}", line) or (cur and line == cur[-1]):   # 2009 repeats a line
            continue
        g = LIST_GROUPS.get(line.lower().rstrip(" :"))
        if g or SECTION.match(line):
            flush()
            paren = re.search(r"\(([^)]+)\)", line)
            group = g or LIST_GROUPS.get(paren.group(1).lower() if paren else "", group)
            if not g:
                kind = ("new_record" if "RECORD" in line.upper() else "new_to_science") if line[:3].upper() == "NEW" else kind
                genus_section = bool(re.search(r"GENUS|GENERA", line.upper())) and "SPECIES" not in line.upper()
            continue
        intro = GROUP_INTRO.match(line)
        if intro:
            flush()
            group = LIST_GROUPS[intro.group(1).lower()]
            cur.append(line)   # the introduction is collected and dropped (it names no taxon)
            continue
        if list_name(line, genus_section) and (not cur or complete(" ".join(cur)) or not list_name(cur[0], genus_section)):
            flush()
        cur.append(line)
    flush()
    return entries


def parse(pdf_path, year):
    if year <= LIST_LAYOUT_LAST:
        return list_entries([ln for page in pymupdf.open(pdf_path) for ln in page_lines(page)], year)
    early = year <= EARLY_PROSE_LAST
    lines = list(english_lines(pdf_path))
    body_start = EARLY_BODY_START if early else BODY_START
    starts = [i for i, (l, _) in enumerate(lines) if body_start.match(l)]
    entries = []
    prev_body_start = -1
    for k, i in enumerate(starts):
        lo = max(prev_body_start + 1, i - 7)
        # 2013 sets the "T" of type strains as a superscript, which lands on a line of its own.
        window = [l for l, _ in lines[lo:i] if not (early and len(l) < 3)]
        offsets = [sum(len(l) + 1 for l in window[:j]) for j in range(len(window))]
        head = find_heading(" ".join(window), offsets)
        if head is None:
            continue
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        # The next entry's header lines belong to the next entry, not this body.
        body_lines = [l for l, _ in lines[i:end]]
        while body_lines and not re.search(r"[.)]\s*$", body_lines[-1]):
            body_lines.pop()
        body = re.sub(r"\s+", " ", " ".join(body_lines))
        name_part, name = head
        if early and name.count(" ") == 1:
            full = list_name(name_part, False) or ""
            name = full if full.startswith(name + " ") else name   # "Musa mannii Baker var. namdangensis"
        fam = HEAD_END.search(name_part)
        family = fam.group(1) if fam else ""
        if family.replace(" ", "").isupper():
            family = family.replace(" ", "").capitalize()
        iucn = IUCN.findall(body)
        kind = "new_record" if NEW_RECORD.search(body) else "new_to_science"
        entries.append(entry(year, name, lines[i][1], kind, name_part, family, collection_states(body),
                             iucn[-1] if iucn else "", body))
        prev_body_start = i
    return entries



LISTING = "https://bsi.gov.in/page/en/national-wild-life-action-plan"  # BSI's "Plant discoveries" page
FIRST_YEAR = 2007


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
        # File names vary: "Plant Discovered_2007", "Discovery - 2013", "Plant Discoveries 2022 for upload final".
        m = re.search(r"Discover[a-z]*[^/]*?((?:19|20)\d\d)[^/]*$", href, re.I)
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
    """Fetch one PDF. False when BSI does not answer with a PDF (it answers missing files with its home page)."""
    import time
    try:
        return util.stream(http, url, dest, kind="pdf")
    finally:
        time.sleep(1)  # about 1 request per second


def fetch_edition(http, year, urls, s3=None):
    """The edition's PDF, downloaded once: from the local cache, else R2, else BSI. When a year has
    two files (BSI posts a full and a short version), keep the larger. None if none is a PDF."""
    from pipeline import r2
    best = SRC / f"Plant Discoveries {year} best.pdf"
    key = f"cache/bsi/{best.name}"
    if r2.restore(s3, key, best):
        log(f"{year}: PDF from R2")
    if not best.exists():
        for url in urls:
            pdf = SRC / f"Plant Discoveries {year}.pdf"
            if download(http, url, pdf) and (not best.exists() or pdf.stat().st_size > best.stat().st_size):
                pdf.replace(best)
                log(f"{year}: downloaded {best.stat().st_size:,} bytes from {url}")
            pdf.unlink(missing_ok=True)   # the smaller of two files
    if not best.exists():
        return None
    if s3 is not None:
        r2.sync_file(s3, best, key)
    return best


def sync(http, s3=None, minutes=None):
    """Parse every edition from FIRST_YEAR that is not in the cache. Returns {year: entries}.
    Scanned editions are OCRed first (resumable); with a time limit (minutes) an unfinished
    edition is left for the next run."""
    import json
    import time
    from pipeline import r2
    SRC.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + minutes * 60 if minutes is not None else None
    links = listing(http)
    out = {}
    for year in sorted(y for y in links if y >= FIRST_YEAR):
        f = cache_file(year)
        if not f.exists() and s3 is not None:
            obj = r2.get_json(s3, f"cache/bsi/{f.name}")
            if obj is not None:
                f.write_text(json.dumps(obj, ensure_ascii=False))
        if not f.exists():
            pdf = fetch_edition(http, year, links[year], s3)
            if pdf is None:
                log(f"{year}: no PDF could be downloaded; kept for the next run")
                continue
            left = None if deadline is None else max(0, (deadline - time.monotonic()) / 60)
            if not ocr(pdf, s3, left):
                log(f"{year}: OCR not finished; kept for the next run")
                continue
            entries = parse(pdf, year)
            f.write_text(json.dumps(entries, ensure_ascii=False))
            log(f"{year}: parsed {len(entries)} entries")
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
    p.add_argument("--minutes", type=float, help="stop cleanly after this time; OCR progress is kept")
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
    res = sync(http, s3, a.minutes)
    print({y: len(v) for y, v in res.items()})


if __name__ == "__main__":
    main()
