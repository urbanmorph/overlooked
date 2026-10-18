"""ZSI Animal Discoveries: new animal species and new records for India, from ZSI's annual books.

Source and credit (ZSI website policy, Terms and Conditions: "Material featured on this website may be
reproduced free of charge ... reproduced accurately ... the source must be prominently acknowledged"):
Zoological Survey of India. Animal Discoveries <year>: New Species and New Records. Ministry of
Environment, Forest and Climate Change, Government of India. https://zsi.gov.in

ZSI posts the editions (2009 to the latest) on its "Animal Discovery" page (LISTING, two pages; the site
shows English links after its language form is set to English). All editions have a text layer; the
few pages without one (covers, some plates) are read with OCR, cached page by page.

Two layouts:
  numbered   2009-2016: "12. Genus species Author ..." entries; numbering restarts per section; new
             records follow a "NEW RECORDS" divider page.
  narrative  2017 on: "The species Genus species was described by ..." for new species, "... earlier
             known from ... reported for the first time from India" for new records.
The section (ZSI_GROUP keys) comes from the last group heading before the entry.

Cache: data/cache/zsi/discoveries/ and R2 cache/zsi/discoveries/: each PDF, its OCR pages and the parsed
entries (one JSON per year). A second run reads the cache and does no new work.

Usage:
    python -m pipeline.zsi_discoveries listing
    python -m pipeline.zsi_discoveries sync [--publish] [--reparse] [--minutes N] [--env .env]
"""

import bisect
import json
import re
import time
from pathlib import Path

from pipeline import bsi

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "cache" / "zsi" / "discoveries"
R2_DIR = "cache/zsi/discoveries"
LISTING = "https://zsi.gov.in/impo-link/7"          # "Animal Discovery" under Important links
LANGUAGE = "https://zsi.gov.in/change-language"
FIRST_YEAR = 2009                                   # earliest edition ZSI posts (the series began in 2007)
NARRATIVE_FROM = 2017
SAVE_EVERY = 600                                    # seconds between R2 saves of OCR progress
SOURCE = "ZSI Animal Discoveries"

# Totals each edition states in its summary or introduction: (new species, new records). For the check
# in report(); where an edition gives two figures, the one in its summary table.
STATED = {2009: (55, 46), 2010: (28, 257), 2011: (193, 66), 2012: (133, 109), 2013: (248, 54), 2014: (176, 61),
          2015: (262, 105), 2016: (313, 83), 2017: (300, 174), 2018: (372, 139), 2019: (368, 116),
          2020: (407, 150), 2021: (406, 134), 2022: (467, 195), 2023: (442, 199), 2024: (459, 224)}

# ZSI section -> Overlooked group (pipeline/groups.py GROUPS), for names GBIF does not match later.
ZSI_GROUP = {
    "Protozoa": "Other", "Porifera": "Other", "Cnidaria": "Other", "Ctenophora": "Other", "Myxozoa": "Other",
    "Platyhelminthes": "Other", "Nematoda": "Other", "Acanthocephala": "Other", "Rotifera": "Other",
    "Gastrotricha": "Other", "Nematomorpha": "Other", "Annelida": "Other", "Bryozoa": "Other", "Tardigrada": "Other",
    "Echinodermata": "Other", "Chaetognatha": "Other", "Hemichordata": "Other", "Protochordata": "Other",
    "Myriapoda": "Other", "Chilopoda": "Other", "Diplopoda": "Other", "Onychophora": "Other",
    "Mollusca": "Molluscs", "Crustacea": "Crabs, shrimps & kin", "Arachnida": "Spiders & other arachnids",
    "Collembola": "Other", "Protura": "Other", "Diplura": "Other",
    "Insecta": "Insects: other", "Coleoptera": "Insects: beetles", "Lepidoptera": "Insects: moths",
    "Hymenoptera": "Insects: bees, wasps, ants", "Diptera": "Insects: flies", "Hemiptera": "Insects: true bugs",
    "Odonata": "Insects: dragonflies & damselflies",
    **{o: "Insects: other" for o in (
        "Orthoptera", "Trichoptera", "Ephemeroptera", "Plecoptera", "Thysanoptera", "Isoptera", "Blattodea",
        "Mantodea", "Phasmida", "Dermaptera", "Neuroptera", "Megaloptera", "Psocodea", "Siphonaptera",
        "Strepsiptera", "Embioptera", "Zygentoma", "Mecoptera", "Raphidioptera", "Archaeognatha", "Zoraptera")},
    "Pisces": "Fish", "Amphibia": "Amphibians", "Reptilia": "Reptiles", "Aves": "Birds",
    "Mammalia": "Mammals: other (whales, dolphins...)", "Chiroptera": "Mammals: bats",
    "Rodentia": "Mammals: rodents, shrews, hares",
}
# Heading words (lower case) -> ZSI section. Section headings, class and order lines, and 2009-2016
# lines such as "THIRTY SEVEN NEW DISCOVERIES OF INSECTS" or "EIGHT SPECIES OF CNIDARIA".
GROUP_TERMS = {t.lower(): t for t in ZSI_GROUP} | {
    "protista": "Protozoa", "apicomplexa": "Protozoa", "ciliophora": "Protozoa", "sarcomastigophora": "Protozoa",
    "trematoda": "Platyhelminthes", "trematodes": "Platyhelminthes", "cestoda": "Platyhelminthes",
    "monogenea": "Platyhelminthes", "turbellaria": "Platyhelminthes", "digenea": "Platyhelminthes",
    "nemathelminthes": "Nematoda", "nematodes": "Nematoda",
    "oligochaeta": "Annelida", "polychaeta": "Annelida", "hirudinea": "Annelida", "leech": "Annelida",
    "leeches": "Annelida", "earthworms": "Annelida",
    "gastropoda": "Mollusca", "bivalvia": "Mollusca", "cephalopoda": "Mollusca", "molluscs": "Mollusca",
    "araneae": "Arachnida", "acari": "Arachnida", "acarina": "Arachnida", "mites": "Arachnida",
    "spiders": "Arachnida", "scorpiones": "Arachnida", "opiliones": "Arachnida", "pseudoscorpiones": "Arachnida",
    "decapoda": "Crustacea", "amphipoda": "Crustacea", "isopoda": "Crustacea", "copepoda": "Crustacea",
    "ostracoda": "Crustacea", "malacostraca": "Crustacea", "brachyura": "Crustacea", "cladocera": "Crustacea",
    "centipedes": "Chilopoda", "centepedes": "Chilopoda", "millipedes": "Diplopoda",
    "insects": "Insecta", "homoptera": "Hemiptera", "heteroptera": "Hemiptera", "psocoptera": "Psocodea",
    "phthiraptera": "Psocodea",
    "fishes": "Pisces", "fish": "Pisces", "actinopterygii": "Pisces", "chondrichthyes": "Pisces",
    "condrichthyes": "Pisces", "elasmobranchii": "Pisces", "teleostei": "Pisces",
    "amphibians": "Amphibia", "anura": "Amphibia", "caudata": "Amphibia", "gymnophiona": "Amphibia",
    "reptiles": "Reptilia", "squamata": "Reptilia", "sauria": "Reptilia", "serpentes": "Reptilia",
    "testudines": "Reptilia", "birds": "Aves", "mammals": "Mammalia",
    "ascidiacea": "Protochordata", "urochordata": "Protochordata", "tunicata": "Protochordata",
}
LABEL = re.compile(r"^(?:[\d.]+\s*)?(?:Phylum|Sub-?phylum|Class|Sub-?class|Super-?order|Order|Sub-?order|Infra-?order)?\s*:?\s*", re.I)
# "THIRTY SEVEN NEW DISCOVERIES OF INSECTS", "SPECIES OF NEMATODA", "ONE GENUS AND 61 SPECIES" / "OF LEPIDOPTERA"
COUNTED = re.compile(r"^(?:[A-Z\d][A-Z\d\s-]*?\s)?(?:(?:NEW\s+)?(?:SPECIES|DISCOVER(?:Y|IES))\s+)?OF\s+([A-Z]+)\s*$")
FAMILY = re.compile(r"^(?:Family|FAMILY)\s*:?\s*([A-Z][A-Za-z]+(?:IDAE|idae))\b|^([A-Z]+IDAE)\s*$")
DIVIDER = re.compile(r"^\s*NEW\s+RECORDS?(?:\s+(?:FROM|TO)\s+INDIA)?\s*:?\s*$")

NOT_NAME = bsi.NOT_EPITHET | {"is", "was", "were", "has", "have", "had", "are", "sp", "spp", "nov", "gen", "new",
                              "species", "which", "also", "described", "earlier", "known", "reported", "recorded",
                              "records", "commonly"}
LATIN_END = re.compile(r"(?:us|a|um|i|ae|is|es|x|on|or|ar|e|ys|as|os)$")   # not "commonly known as"
PARTICLES = {"de", "van", "von", "da", "der", "del", "la", "le", "et", "and", "in", "du", "dos"}
EPI = r"[a-z][a-z-]{2,}"
# Genus (Subgenus) epithet [subspecies]; subgenus also "(A.)", "(s. str.)", and with no space before it.
NAME = re.compile(rf"([A-Z][a-z]+)(?:\s*\(([A-Z][a-z]*\.?|s\.\s?(?:str|l|lat)\.)\))?\s+({EPI})(?:\s+({EPI}))?")
JUNK = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")   # 2016's legacy font comes out as control characters
LIGATURES = str.maketrans({"\ufb01": "fi", "\ufb02": "fl", "\u047a": "fl", "\u00a0": " "})  # \u047a: 2021 "fl"


def log(*a):
    print(*a, flush=True)


# ---------- listing, download, page text (cached locally and in R2) ----------

def listing(http):
    """{year: PDF URL} from ZSI's Animal Discovery pages. The site serves Hindi-folder links until its
    language form is set to English (one GET for the form token, one POST), as a visitor would."""
    import html
    from urllib.parse import urljoin
    r = http.get("https://zsi.gov.in/home", timeout=90)
    r.raise_for_status()
    token = re.search(r'name="_token" value="([^"]+)"', r.text)
    if token:
        time.sleep(1)
        http.post(LANGUAGE, data={"_token": token.group(1), "language": "en"}, timeout=90)
    links, url = {}, LISTING
    while url:
        time.sleep(1)
        r = http.get(url, timeout=90)
        r.raise_for_status()
        if "text/html" not in r.headers.get("Content-Type", ""):
            raise RuntimeError("ZSI listing page did not return HTML")
        for href in re.findall(r'href="([^"]+\.pdf)"', r.text, re.I):
            href = html.unescape(href)
            m = re.search(r"Animal[ _%20-]*Discover[a-z]*[^/]*?((?:19|20)\d\d)", href.rsplit("/", 1)[-1], re.I)
            if m:
                links.setdefault(int(m.group(1)), urljoin(LISTING, href))
        nxt = re.search(r'href="([^"]+)"\s+rel="next"', r.text)
        url = html.unescape(nxt.group(1)) if nxt else None
    return links


def pdf_file(year):
    return SRC / f"animal_discoveries_{year}.pdf"


def cache_file(year):
    return SRC / f"animal_discoveries_{year}.json"


def ocr_file(year):
    return SRC / f"animal_discoveries_{year}_ocr.json"


def fetch_pdf(http, url, year, s3=None):
    """The edition's PDF from the local cache, else R2, else ZSI (checked to be a PDF). None if ZSI
    did not send one; the year is then tried again on the next run."""
    from pipeline import r2
    dest = pdf_file(year)
    key = f"{R2_DIR}/{dest.name}"
    if not dest.exists() and s3 is not None and r2.exists(s3, key):
        s3.download_file(r2.bucket(), key, str(dest))
        log(f"{year}: PDF from R2")
    if not dest.exists():
        part = dest.with_suffix(".part")
        ok = bsi.download(http, url.replace(" ", "%20"), part)
        time.sleep(1)
        if not ok:
            part.unlink(missing_ok=True)
            return None
        part.rename(dest)
        log(f"{year}: downloaded {dest.stat().st_size:,} bytes from {url}")
    if s3 is not None:
        r2.sync_file(s3, dest, key)
    return dest


def needs_ocr(text):
    """No text layer, or one in a legacy font that comes out as control characters (2016)."""
    return not text.strip() or len(JUNK.findall(text)) > 20


def ocr_page(page):
    """Tesseract text in reading order; two columns when many lines start right of the middle."""
    from pipeline import bsi_checklist
    got = bsi_checklist.ocr_page(page)
    right = sum(x0 >= got["w"] / 2 for x0, *_ in got["lines"])
    cols = 2 if right >= 0.2 * max(len(got["lines"]), 1) else 1
    return "\n".join(t for t, _ in bsi_checklist.reading_order(got, columns=cols))


def page_texts(pdf, year, s3=None):
    """{page number: text}: the text layer, or OCR where needs_ocr(). OCR pages are kept in
    ocr_file(year) (and R2), saved every SAVE_EVERY seconds and on exit, also on failure."""
    import pymupdf
    from pipeline import r2
    f = ocr_file(year)
    key = f"{R2_DIR}/{f.name}"
    done = json.loads(f.read_text()) if f.exists() else None
    if done is None:
        done = (r2.get_json(s3, key) if s3 is not None else None) or {}
    dirty, next_save = False, time.monotonic() + SAVE_EVERY

    def save():
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(done, ensure_ascii=False))
        tmp.replace(f)
        if s3 is not None:
            r2.sync_file(s3, f, key, immutable=False)

    out = {}
    try:
        for page in pymupdf.open(pdf):
            n = page.number + 1
            text = page.get_text()
            if needs_ocr(text):
                if str(n) not in done:
                    done[str(n)] = ocr_page(page)
                    dirty = True
                    log(f"{year}: OCR page {n}")
                text = done[str(n)]
            out[n] = text
            if dirty and time.monotonic() > next_save:
                save()
                dirty, next_save = False, time.monotonic() + SAVE_EVERY
    finally:
        if dirty:
            save()
        elif s3 is not None and f.exists():
            r2.sync_file(s3, f, key, immutable=False)    # skipped when R2 already holds this file
    return out


# ---------- parsing ----------

def heading_group(line):
    """The ZSI section a heading line names, or None."""
    m = COUNTED.match(line)
    if m:
        return GROUP_TERMS.get(m.group(1).lower())
    words = LABEL.sub("", line).strip(" .:")
    first = re.split(r"\s*[:/]\s*", words)[0].strip()
    return GROUP_TERMS.get(first.lower()) if first and len(first.split()) == 1 else None


def heading_family(line):
    m = FAMILY.match(line)
    return (m.group(1) or m.group(2)).capitalize() if m else None


def clean_name(m):
    """(name, rank) from a NAME match; None if it is not a name. Subgenus dropped; a third word is
    a subspecies unless it is an author particle."""
    g, _sub, epi, third = m.groups()
    if g in bsi.NOT_GENUS or epi in NOT_NAME:
        return None
    if third and third not in NOT_NAME | PARTICLES and LATIN_END.search(third):
        return f"{g} {epi} {third}", "infraspecific"
    return f"{g} {epi}", "species"


def name_check(name):
    genus, _, rest = name.partition(" ")
    epithet = rest.split(" ")[0]
    if genus in bsi.KNOWN_GENERA:
        return "ok"
    if len(genus) > 3 and len(epithet) > 3 and epithet not in NOT_NAME:
        return "unknown_genus"   # often a genuinely new genus; verify
    return "needs_review"


def lines_of(pages):
    """[(page, line)] in reading order: ligatures fixed, control characters and blank lines dropped."""
    return [(p, ln.strip()) for p in sorted(pages)
            for ln in JUNK.sub(" ", pages[p].translate(LIGATURES)).splitlines() if ln.strip()]


def context(lines):
    """Per line index: (section, family) in force at that line (last heading before it), and
    {genus: family} from "Family: X" lines followed by "Genus: Y" (two-page spreads print the family
    after some entries, so the genus says more than the order of the lines)."""
    group = family = ""
    out, genus_family, since = [], {}, 99
    for k, (_p, ln) in enumerate(lines):
        group = heading_group(ln) or group
        fam = heading_family(ln)
        family, since = (fam, 0) if fam else (family, since + 1)
        if since <= 8 and ln.startswith("Genus"):
            # "Genus: Lasioptera Meigen 1818", or "Genus" with the name on the next line (2019)
            g = re.match(r"^Genus\s*:?\s*([A-Z][a-z]+)", ln) or (
                k + 1 < len(lines) and re.match(r"([A-Z][a-z]+)", lines[k + 1][1]))
            if g:
                genus_family.setdefault(g.group(1), family)
        out.append((group, family))
    return out, genus_family


def entry(year, name, rank, kind, group, family, body):
    return {"year": year, "name": name, "name_check": name_check(name), "kind": kind, "rank": rank,
            "group": group, "family": family, "states": "; ".join(bsi.collection_states(body)),
            "text": body[:600], "source": f"Zoological Survey of India, Animal Discoveries {year}"}


NUMBERED = re.compile(rf"^(\d{{1,3}})\s*\.\s+({NAME.pattern})(.*)$")
AUTHOR_NEXT = re.compile(r"^\s*,?\s*\(?\s*(?:[A-Z]|van\s|de\s|von\s|d')")
FIELD = re.compile(r"^(?:Locality|Journal|Book|Year|Described by|Recorded by)\s*:")


def ocr_clean(line):
    """OCR specks between the words of an entry line: "10. Homalotylus _ biharensis — Krishnachaitanya"."""
    line = re.sub(r"(?<=[a-z])!", "i", line)
    return re.sub(r"\s{2,}", " ", re.sub(r"[_=~—–’‘\"|;]+|(?<=\s)\.(?=\s)", " ", line)).strip()


def parse_numbered(lines, year):
    """2009-2016: "N. Genus species Author" entries. Figure captions also start with numbers
    ("5. Mesosoma dorsal view"); an entry looks like one (an author after the name, or a "Locality :"
    field below it) or continues the numbering. OCR misreads numbers ("47." for "17."), so the
    numbering alone does not decide.
    Entries after the "NEW RECORDS" divider are new records."""
    ctx, genus_family = context(lines)
    divider = next((i for i, (_p, ln) in enumerate(lines) if DIVIDER.match(ln)), len(lines))
    starts, last = [], 0
    for i, (_p, ln) in enumerate(lines):
        if not re.match(r"\d{1,3}\s*\.", ln):
            continue
        m = NUMBERED.match(ocr_clean(ln))
        if not m or not clean_name(NAME.match(m.group(2))):
            # Name broken over lines: "2. Apsilochorema (Apsilochorema) . . ." / "shalimarensis" / "Parey ..."
            m = NUMBERED.match(ocr_clean(" ".join(x for _p, x in lines[i:i + 3])))
        got = clean_name(NAME.match(m.group(2))) if m else None
        if not got:
            continue
        n = int(m.group(1))
        if re.search(r"[;,]\s*\d{1,2}\s*\.", m.group(7)):
            continue      # figure caption: "1. Tarsal spurs; 2. Cephalic plate ..."
        rest = m.group(7).strip() or (lines[i + 1][1] if i + 1 < len(lines) else "")
        looks = AUTHOR_NEXT.match(rest) or (not rest.startswith(".") and any(FIELD.match(x) for _p, x in lines[i + 1:i + 12]))
        if looks or n == last + 1:
            starts.append((i, *got))
            last = n
    out = []
    for k, (i, name, rank) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        body = re.sub(r"\s+", " ", " ".join(ln for _p, ln in lines[i:end]))
        # Where the collection was: the "Locality :" field (2009-2015), else the text after the
        # citation that follows the name (2016: "..., Nature Book India, N. Delhi (2016).").
        loc = re.search(r"Locality\s*:\s*([^:]*?)(?=\b(?:Journal|Book|Year)\s*:|$)", body)
        cite = re.search(r"\(?(?:19|20)\d\d\)?\.\s", body[:300])
        where = loc.group(1) if loc else body[cite.end():] if cite else body
        kind = "new_record" if i > divider else "new_to_science"
        fam = genus_family.get(name.split()[0]) or ctx[i][1]
        out.append(dict(entry(year, name, rank, kind, ctx[i][0], fam, where), text=body[:600]))
    return out


# "was described by"; also "as described by" and "was described C.K. Mandal" (typos in 2023, 2024).
DESCRIBED = re.compile(r"\b(?:w?as|were|is|has\s+been|have\s+been)\s+described\b")
CITATION = re.compile(r"^Citation\s*:", re.M)    # 2020: some entries give only the paper's citation
RECORDED = re.compile(r"\bearlier\s+known\b|\breported\s+for\s+the\s+first\s+time\b|\bfirst\s+record", re.I)
SPECIES_WORD = re.compile(r"\b(?:[Ss]ub)?[Ss](?:pecies|peies|pcies|peices)\b|\bThe\s+(?=[A-Z][a-z]+\s+[a-z])")
SENTENCE_END = re.compile(r"\.\s+(?=[A-Z])")   # not "(s. lat.) reuteri"
NAME_AFTER = re.compile(rf"\s*{NAME.pattern}")
HEAD_LINE = re.compile(rf"^{NAME.pattern}\s*,?\s+\(?(?:[A-Z]|van |de |von )")


def name_before(window):
    """The name in "The species X ..." / "the genus G and the species x" closest before an anchor."""
    found = None
    for m in SPECIES_WORD.finditer(window):
        n = NAME_AFTER.match(window, m.end())
        if n:
            found = clean_name(n)
        else:
            e = re.match(rf"\s+({EPI})\b", window[m.end():])
            g = re.findall(r"\bgenus\s+([A-Z][a-z]+)", window[:m.start()])
            if e and g:
                found = clean_name(NAME.match(f"{g[-1]} {e.group(1)}"))
    return found


def parse_narrative(lines, year):
    """2017 on: anchors "... was described by" or "Citation:" (new species) and "earlier known /
    reported for the first time" (new records). The name comes from the anchor's sentence, else from
    the entry heading line above it ("Genus species Author, year")."""
    ctx, genus_family = context(lines)
    text, offs = "", []
    for _p, ln in lines:
        offs.append(len(text))
        text += ln + "\n"
    anchors = sorted([(m.start(), "new_to_science") for m in DESCRIBED.finditer(text)] +
                     [(m.start(), "new_to_science") for m in CITATION.finditer(text)] +
                     [(m.start(), "new_record") for m in RECORDED.finditer(text)])
    found, seen = [], set()
    for pos, kind in anchors:
        i = bisect.bisect_right(offs, pos) - 1
        start = max([m.end() for m in SENTENCE_END.finditer(text, max(pos - 400, 0), pos)] or [max(pos - 400, 0)])
        got = name_before(text[start:pos])
        # No name in the sentence: take the entry heading above, for "The species was described by"
        # and "Citation:" entries and for new records; not for summary sentences ("12 new species of
        # Annelida have been described").
        if got is None and (kind == "new_record" or text.startswith("Citation", pos)
                            or re.search(r"The\s+(?:new\s+)?species\s*$", text[start:pos])):
            heads = (HEAD_LINE.match(lines[j][1]) for j in range(i, max(i - 25, -1), -1))
            got = next((clean_name(h) for h in heads if h and clean_name(h)), None)
        if got is None or got[0] in seen:
            continue      # one entry often has two anchors ("earlier known ...; reported for the first time")
        stop = SENTENCE_END.search(text, pos)
        if kind == "new_to_science" and RECORDED.search(text, pos, stop.start() if stop else len(text)):
            kind = "new_record"   # "was described by X from Japan; has been reported for the first time from India"
        seen.add(got[0])
        found.append((start, i, got, kind))
    out = []
    for k, (start, i, (name, rank), kind) in enumerate(found):
        end = found[k + 1][0] if k + 1 < len(found) else len(text)
        fam = genus_family.get(name.split()[0], "")
        out.append(entry(year, name, rank, kind, ctx[i][0], fam, re.sub(r"\s+", " ", text[start:end])))
    return out


def parse(pages, year):
    """Entries of one edition from {page number: text}, one per name (the first)."""
    lines = lines_of(pages)
    first = {}
    for e in parse_numbered(lines, year) if year < NARRATIVE_FROM else parse_narrative(lines, year):
        first.setdefault(e["name"], e)
    return list(first.values())


# ---------- sync, quality check, names for the new-species layer ----------

def report(year, entries):
    new = sum(1 for e in entries if e["kind"] == "new_to_science")
    rec = len(entries) - new
    stated = STATED.get(year)
    note = f" (edition states {stated[0]} new species, {stated[1]} new records)" if stated else ""
    log(f"{year}: {new} new species, {rec} new records parsed{note}")
    return new, rec


def sync(http, s3=None, reparse=False, minutes=None):
    """Parse every edition from FIRST_YEAR that is not in the cache. Returns {year: entries}.
    With `minutes`, no new edition is started after that time; the rest wait for the next run."""
    from pipeline import r2
    SRC.mkdir(parents=True, exist_ok=True)
    links = listing(http)
    deadline = time.monotonic() + minutes * 60 if minutes is not None else None
    out = {}
    for year in sorted(y for y in links if y >= FIRST_YEAR):
        f = cache_file(year)
        key = f"{R2_DIR}/{f.name}"
        if not f.exists() and s3 is not None and not reparse:
            obj = r2.get_json(s3, key)
            if obj is not None:
                f.write_text(json.dumps(obj, ensure_ascii=False))
        if reparse or not f.exists():
            if deadline is not None and time.monotonic() > deadline:
                log(f"{year}: time limit reached; kept for the next run")
                continue
            pdf = fetch_pdf(http, links[year], year, s3)
            if pdf is None:
                log(f"{year}: ZSI did not send a PDF; kept for the next run")
                continue
            entries = [dict(e, link=links[year]) for e in parse(page_texts(pdf, year, s3), year)]
            report(year, entries)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(entries, ensure_ascii=False))
            tmp.replace(f)
        if s3 is not None:
            r2.sync_file(s3, f, key, immutable=False)
        out[year] = json.loads(f.read_text())
    return out


def names(http, s3, first_year):
    """Rows for the new-species layer: species new to science (not subspecies), from first_year."""
    out = []
    for year, entries in sync(http, s3).items():
        if year < first_year:
            continue
        for e in entries:
            if e["kind"] == "new_to_science" and e["rank"] == "species" and e["name_check"] != "needs_review":
                out.append({"name": e["name"], "year": int(e["year"]), "source": SOURCE, "journal": "", "state": "",
                            "zsi_group": e.get("group") or "", "link": e["link"]})
    return out


def main():
    import argparse
    from pipeline import health
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["listing", "sync"])
    p.add_argument("--publish", action="store_true")
    p.add_argument("--reparse", action="store_true", help="parse cached PDFs again (after a parser change)")
    p.add_argument("--minutes", type=float, help="start no new edition after this many minutes")
    p.add_argument("--env", default=ROOT / ".env", type=Path, help="file with the R2_* keys and GBIF_EMAIL")
    a = p.parse_args()
    import requests
    from dotenv import load_dotenv
    load_dotenv(a.env, override=True)        # contact email for the User-Agent; R2 keys for --publish
    http = requests.Session()
    http.headers["User-Agent"] = health.ua()
    if a.cmd == "listing":
        log(json.dumps(listing(http), indent=1))
        return
    s3 = None
    if a.publish:
        from pipeline import r2
        s3 = r2.client()
    res = sync(http, s3, reparse=a.reparse, minutes=a.minutes)
    log("summary:")
    for year, entries in res.items():
        report(year, entries)


if __name__ == "__main__":
    main()
