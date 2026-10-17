"""BSI national checklists: the plant species BSI lists for India, as one names table.

BSI publishes its national checklists only as scanned PDF books (no text layer, no structured
download; the eFlora of India portal and the BSI ENVIS site did not answer in October 2026). This
module downloads the books that BSI offers free on bsi.gov.in, reads them with OCR (Tesseract via
PyMuPDF), and parses each entry: accepted name, synonyms, authority and distribution.

Source and credit (BSI web policy: reproduction free of charge, accurately, with prominent
acknowledgement): Botanical Survey of India, Ministry of Environment, Forest and Climate Change,
Government of India. https://bsi.gov.in

Cache and restart: each PDF and each book's OCR (one JSON per book, page by page) are kept in
data/cache/bsi/checklists/ and in R2 cache/bsi/checklists/. OCR progress is saved every 10 minutes
and on exit, also on failure; a second run reads the cache and does no new work.

OCR misreads names, so each name is checked against Kew WCVP (accepted names and synonyms, CC BY):
a close, unambiguous match replaces the OCR spelling, and every change is listed for review.

Output: data/bsi/bsi_checklist.csv (columns in FIELDS), bsi_checklist_qc.csv (names not found as
read) and bsi_checklist_summary.json (counts by book and group against the totals each book
states); the same three files in R2 cache/bsi/.

Usage:
    python -m pipeline.bsi_checklist [--publish] [--minutes N] [--only KEY ...] [--env .env] [--names WCVP]
"""

import csv
import difflib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "bsi" / "checklists"
OUT = ROOT / "data" / "bsi"
R2_DIR = "cache/bsi"
REF = ROOT / "pipeline" / "ref"
SAVE_EVERY = 600  # seconds
# Kew WCVP binomials (accepted and synonyms) for the spelling check; built by fnf 03_wcvp_india.py.
WCVP_NAMES = ROOT / "data" / "fnf" / "wcvp" / "wcvp_name_lookup.parquet"
FIELDS = ["source", "checklist", "group", "family", "name", "rank", "authority", "status", "states", "page",
          "edition", "url"]
BOOKS = "https://bsi.gov.in/uploads/documents/Public_Information/publication/books/miscellaneous/"

# BSI's national checklists with a free public copy. pages: the PDF pages (1-based, inclusive) that
# hold the enumeration; the introduction and the index are left out. stated: the totals the book's
# introduction gives, for the coverage check.
CHECKLISTS = [
    {"key": "fpi_dicots_v1", "group": "flowering plants", "layout": "block", "columns": 1,
     "title": "Flowering Plants of India: Dicotyledons, Volume 1 (Acanthaceae to Avicenniaceae)",
     "edition": "Karthikeyan, S., Sanjappa, M. & Moorthy, S. (2009). Botanical Survey of India, Kolkata",
     "url": BOOKS + quote("Flowering Plants of India - Dicotyledons vol 1.pdf"),
     "pages": (51, 349), "top": 58, "one_per_block": True,
     "header": r"Botanical Survey of India|Flowering Plants of India|^\s*20\d\d\s*$",
     # Introduction p. xvii: "The present status of these 18 families in India".
     "stated": {"genera": 483, "species": 2509, "subspecies": 34, "varieties": 285, "forms": 10},
     "families": ["Acanthaceae", "Aceraceae", "Actinidiaceae", "Adoxaceae", "Aizoaceae", "Alangiaceae",
                  "Amaranthaceae", "Anacardiaceae", "Ancistrocladaceae", "Annonaceae", "Apiaceae", "Apocynaceae",
                  "Aquifoliaceae", "Araliaceae", "Aristolochiaceae", "Asclepiadaceae", "Asteraceae",
                  "Avicenniaceae"]},
    {"key": "fie_monocots", "group": "flowering plants", "layout": "block", "columns": 2,
     "title": "Florae Indicae Enumeratio: Monocotyledonae",
     "edition": "Karthikeyan, S., Jain, S.K., Nayar, M.P. & Sanjappa, M. (1989). Botanical Survey of India, Calcutta",
     "url": BOOKS + quote("Florae Indicae Enumeratio  Manocotyledonae.pdf"),
     "pages": (9, 309), "top": 58, "header": r"Florae\s+Indicae|Monocotyledonae|^Botanical Survey$|^of India$",
     # Introduction: "The present work contains a total of 674 genera, 4081 species, 46 subspecies,
     # 428 varieties, 4 sub varieties and 19 forma" and "A total of 4010 synonyms".
     "stated": {"genera": 674, "species": 4081, "subspecies": 46, "varieties": 428, "subvarieties": 4,
                "forms": 19, "synonyms": 4010}},
    {"key": "fie_asteraceae", "group": "flowering plants", "layout": "distrib", "columns": 2, "family": "Asteraceae",
     "title": "Florae Indicae Enumeratio: Asteraceae",
     "edition": "Hajra, P.K., Rao, R.R., Singh, D.K. & Uniyal, B.P. (1995). Botanical Survey of India, Calcutta",
     "url": BOOKS + quote("Florae Indicae Enumeratio  Asteraceae.pdf"),
     "pages": (8, 101), "top": 112, "families": [], "header": r"(?i)FLORAE\s+INDICAE|ENUMERATIO|BOTANICAL\s+SURVEY",
     # Introduction: "treatment of 1052 taxa under 177 genera".
     "stated": {"genera": 177, "taxa": 1052}},
    {"key": "census_pteridophytes", "group": "pteridophytes", "layout": "distrib", "columns": 1,
     "title": "A Census of Indian Pteridophytes",
     "edition": "Dixit, R.D. (1984). Flora of India Series 4. Botanical Survey of India, Howrah",
     "url": BOOKS + quote("A Census of Indian Pteridophytes.pdf"),
     "pages": (18, 185), "top": 80, "families": [], "header": r"(?i)CENSUS\s+OF\s+IND|BOTANICAL\s+SURVEY",
     # Introduction: "The present Census comprises of 67 families, 191 genera and more than 1,000 species".
     "stated": {"families": 67, "genera": 191, "species_more_than": 1000}},
]


def log(*a):
    print(*a, flush=True)


# ---------- download and OCR (cached locally and in R2, resumable) ----------

def pdf_path(spec):
    return CACHE / f"{spec['key']}.pdf"


def fetch_pdf(http, spec, s3=None):
    """The book's PDF: from the local cache, else R2, else BSI (checked to be a PDF: BSI answers
    missing files with its home page and HTTP 200). Written to a .part file first."""
    from pipeline import r2
    dest = pdf_path(spec)
    key = f"{R2_DIR}/checklists/{dest.name}"
    if not dest.exists() and s3 is not None and r2.exists(s3, key):
        dest.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(r2.bucket(), key, str(dest))
        log(f"{spec['key']}: PDF from R2")
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(".part")
        with http.get(spec["url"], stream=True, timeout=600) as r:
            r.raise_for_status()
            if "pdf" not in r.headers.get("Content-Type", "").lower():
                raise RuntimeError(f"{spec['url']} did not return a PDF")
            with open(part, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        part.rename(dest)
        log(f"{spec['key']}: downloaded {dest.stat().st_size:,} bytes from BSI")
        time.sleep(1)
    if s3 is not None:
        r2.sync_file(s3, dest, key)
    return dest


def ocr_file(spec):
    return CACHE / f"{spec['key']}_ocr.json"


def ocr_page(page):
    """Lines of one page as [x0, y0, x1, text], from Tesseract at 300 dpi."""
    tp = page.get_textpage_ocr(language="eng", dpi=300, full=True)
    lines = []
    for b in page.get_text("dict", textpage=tp)["blocks"]:
        for ln in b.get("lines", []):
            text = re.sub(r"\s+", " ", " ".join(s["text"] for s in ln["spans"])).strip()
            if text:
                x0, y0, x1, _ = ln["bbox"]
                lines.append([round(x0, 1), round(y0, 1), round(x1, 1), text])
    return {"w": round(page.rect.width, 1), "lines": lines}


def ocr(spec, s3=None, minutes=None, ocr_page=ocr_page):
    """OCR every page of the book not yet in the cache. Returns {page number (str): page} when the
    book is complete, None when the time limit stopped it (progress is kept for the next run)."""
    import pymupdf
    from pipeline import r2
    f = ocr_file(spec)
    key = f"{R2_DIR}/checklists/{f.name}"
    done = json.loads(f.read_text()) if f.exists() else None
    if done is None:
        done = (r2.get_json(s3, key) if s3 is not None else None) or {}
    doc = pymupdf.open(pdf_path(spec))
    todo = [n for n in range(1, len(doc) + 1) if str(n) not in done]
    deadline = time.monotonic() + minutes * 60 if minutes is not None else None
    next_save, dirty = time.monotonic() + SAVE_EVERY, not f.exists()

    def save():
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(done, ensure_ascii=False))
        tmp.replace(f)
        if s3 is not None:
            r2.sync_file(s3, f, key, immutable=False)

    try:
        for i, n in enumerate(todo):
            if deadline is not None and time.monotonic() > deadline:
                log(f"{spec['key']}: time limit, {len(todo) - i} pages left for the next run")
                return None
            done[str(n)] = ocr_page(doc[n - 1])
            dirty = True
            if (i + 1) % 25 == 0:
                log(f"{spec['key']}: OCR {i + 1}/{len(todo)} pages")
            if time.monotonic() > next_save:
                save()
                next_save, dirty = time.monotonic() + SAVE_EVERY, False
    finally:
        if dirty:
            save()
        elif s3 is not None:
            r2.sync_file(s3, f, key, immutable=False)   # skipped when R2 already holds this file
    return done


# ---------- page layout ----------

TOP = "top"   # first line of a column: a paragraph may start there, or run on from the last column


def reading_order(page, columns=1, header=None, top=0):
    """Lines in reading order as (text, starts_paragraph). Pieces on one baseline are joined; a
    paragraph starts after a gap wider than 1.5 line pitches (True), and maybe at the top of each
    column (TOP).
    Running headers (above `top`, or matching the regex `header`) and bare page numbers are dropped."""
    mid = page["w"] / 2
    cols = [[] for _ in range(columns)]
    for x0, y0, x1, text in page["lines"]:
        # Page numbers sit in the footer (below 1.2 page widths on these A4 scans); a bare year
        # higher up ("1965.") is the end of a citation.
        folio = y0 > 1.2 * page["w"] and re.fullmatch(r"[\divxlc]{1,7}\.?", text.strip(), re.I)
        if y0 < top or (header and re.search(header, text)) or folio:
            continue
        cols[int(columns == 2 and x0 >= mid)].append((y0, x0, text))
    out = []
    for col in cols:
        merged = []
        for y0, x0, text in sorted(col):
            if merged and abs(y0 - merged[-1][0]) < 5:
                merged[-1][2].append((x0, text))
            else:
                merged.append([y0, x0, [(x0, text)]])
        ys = [m[0] for m in merged]
        # Line pitch: the lower quartile of the gaps, leaving out OCR fragments a few points apart.
        gaps = sorted(g for g in (b - a for a, b in zip(ys, ys[1:])) if g >= 8)
        pitch = gaps[len(gaps) // 4] if gaps else 0
        prev = None
        for y0, _, parts in merged:
            text = " ".join(t for _, t in sorted(parts))
            out.append((text, TOP if prev is None else y0 - prev > 1.5 * pitch))
            prev = y0
    return out


# ---------- entry parser ----------

RANKS = {"var": "variety", "subsp": "subspecies", "ssp": "subspecies", "f": "form", "forma": "form"}
INFRA = r"(?:var|subsp|ssp|forma|f)\.?,?\s+[a-z][a-z-]+"
NAME = re.compile(r"^(?P<g>[A-Z][a-zë]+|[A-Z][.,])\s+(?:(?P<x>[x×])\s+)?(?P<e>[a-z][a-z-]+)(?P<i>(?:\s+" + INFRA + r")*)")
INFRA_LINE = re.compile(r"^(?P<i>(?:" + INFRA + r")(?:\s+" + INFRA + r")*)")
FAMILY = re.compile(r"^([A-Z]{3,}ACEAE|COMPOSITAE|GRAMINEAE|PALMAE|LEGUMINOSAE|CRUCIFERAE|LABIATAE|UMBELLIFERAE|GUTTIFERAE)\b")
GENUS_HEAD = re.compile(r"^([A-Z]{3,})\b(?![.-])")
GENUS_TITLE = re.compile(r"^([A-Z][a-z]{2,})\s+(?:[A-Z]|\(|ex\s)")   # "Pteris L. Sp. Pl. 2: 1073. 1753."
DISTRIB = re.compile(r"^Distr[il1]b\s*[.,:;]*\s*:?\s*")
# A citation is complete when the line ends with a year or a page number (OCR reads '.' as ',').
CLOSED = re.compile(r"(\d{3,4}\)?|nom\.\s*(?:cons|illeg|nud|superfl|rej)\.?\)?)[\s.,]*$")
GEO = re.compile(r"\b(India|Himalayas?|Ghats|hills|Hills|islands|Islands|plains|Plains|parts|regions?|tropics|"
                 r"Introduced|Cultivated|Endemic|Throughout|Peninsular|Deccan|Western|Eastern|Northern|Southern)\b")
NOT_EPITHET = {"of", "de", "in", "at", "and", "from", "the", "et", "ex", "for", "to", "on", "by", "with", "near",
               "parts", "hills", "plains", "regions", "region", "islands", "india", "and", "throughout", "sp", "spp"}
# Words that start the place of publication after an author with no comma ("L. Sp. Pl. 2: 1076").
PUB_WORDS = {"Sp.", "Fl.", "Hedw.", "Journ.", "Trans.", "Bull.", "Proc.", "Ann.", "Kew", "Ferns", "Fern",
             "Syn.", "Gen.", "Enum.", "Mant.", "Nov.", "Icon.", "Hort.", "Pl.", "Prodr.", "Mem.", "Rev.", "Amer.",
             "Ind.", "Comb.", "Basionym:", "Handb.", "Lingnan", "Notes", "Rec.", "Contr.", "Philipp.", "Am."}


def plausible(name):
    """A Latin name, not an OCR fragment or a phrase: genus of 3+ letters, epithets of 3+ lowercase
    letters, no digits, and an epithet that is not an ordinary word."""
    parts = name.split()
    if len(parts) < 2 or not re.fullmatch(r"[A-Z][a-zë]{2,}", parts[0]):
        return False
    words = [p for p in parts[1:] if p not in ("x", "×") and p.rstrip(".") not in RANKS]
    return bool(words) and all(re.fullmatch(r"[a-z][a-z-]{2,}", w) for w in words) and words[0] not in NOT_EPITHET


def authority(rest):
    """The author citation after a name: up to ' in ', the first comma or the first number, and
    before a word that starts a place of publication."""
    a = re.split(r"\s+in\s+|,|;|\s\d", " " + rest)[0]
    toks = a.split()
    for i, t in enumerate(toks):
        if i and t in PUB_WORDS:
            toks = toks[:i]
            break
    return " ".join(toks).strip(" .:") + ("." if toks and toks[-1].endswith(".") else "")


def infra_suffix(text):
    """'var, angustifolius' -> ('var. angustifolius', 'variety'); last rank wins."""
    parts = re.findall(r"(var|subsp|ssp|forma|f)\.?,?\s+([a-z][a-z-]+)", text)
    out = " ".join(f"{'subsp' if r == 'ssp' else 'f' if r == 'forma' else r}. {e}" for r, e in parts)
    return out, (RANKS[parts[-1][0]] if parts else "species")


class States:
    """Indian states and union territories named in a distribution text (pipeline/ref/state_names.csv).
    Abbreviations of two or three letters (UP, MP, TN) are not used: in old texts they are ambiguous."""

    def __init__(self, path=REF / "state_names.csv"):
        from pipeline.unlocated import words
        self.words = words
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        canon = {}
        for r in rows:
            canon.setdefault(r["state_lgd"], r["name"])
        self.names = {words(r["name"]): canon[r["state_lgd"]] for r in rows if len(words(r["name"])) > 3}
        self.re = re.compile(r"\b(" + "|".join(sorted(map(re.escape, self.names), key=len, reverse=True)) + r")\b")

    def __call__(self, text):
        return ";".join(sorted({self.names[m] for m in self.re.findall(self.words(text))}))


STATES = None


def states_of(text):
    global STATES
    STATES = STATES or States()
    return STATES(text)


def family_of(text, families=()):
    """The family named by a heading line, or None. A heading is one word that ends like "-aceae"
    (an upper-case alternative name in brackets may follow: "APIACEAE [UMBELLIFERAE]"). With a family
    list, OCR misreadings ("ARACKAE") are matched to the closest family; without it, only a clean
    "...ACEAE" or "...aceae" word counts."""
    words = re.sub(r"\s*[\[(][A-Z ]+[\])]\.?\s*$", "", text.strip()).split()
    if len(words) > 1 and words[0].isupper() and len(text) <= 40 and not re.search(r"\d", text):
        words = words[:1]                      # "PTERIDACEAE Ching": family and author
    if len(words) != 1 or not re.fullmatch(r"[A-Za-z]{7,}\.?", words[0]):
        return None
    w = words[0].rstrip(".").capitalize()
    if difflib.SequenceMatcher(None, w[-5:].lower(), "aceae").ratio() < 0.7:
        return None
    if families:
        close = difflib.get_close_matches(w, families, n=1, cutoff=0.7)
        return close[0] if close else None
    return w if FAMILY.match(words[0]) or re.fullmatch(r"[A-Z][a-z]+aceae", words[0]) else None


def looks_like_distribution(text):
    """A place line ("Throughout tropical India."): no numbers, and a place word."""
    return not re.search(r"\d", text) and bool(GEO.search(text))


def fix_genus(genus, head, known):
    """OCR of a genus: keep it when known; else take the current genus heading when it is close."""
    if genus in known or not head:
        return genus
    return head if difflib.SequenceMatcher(None, genus.lower(), head.lower()).ratio() >= 0.75 else genus


def edits(a, b):
    """Levenshtein distance."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


class Corrector:
    """Spelling of OCR names against a reference list of binomials (Kew WCVP), the way the ZSI names
    were checked against the Catalogue of Life. A name is changed only when one reference name is
    clearly closest: at most one wrong letter in four in the genus and in the epithet, and no other
    reference name as close. The infraspecific epithet of an autonym follows the species epithet."""

    def __init__(self, names):
        self.names = set(names)
        self.by_genus = {}
        for n in self.names:
            g, _, e = n.partition(" ")
            self.by_genus.setdefault(g, []).append(e)
        self.genera = list(self.by_genus)

    def best(self, sp):
        g, _, e = sp.partition(" ")
        genera = [g] if g in self.by_genus else difflib.get_close_matches(g, self.genera, n=3, cutoff=0.7)
        scored = sorted((edits(g, cg) + edits(e, ce), f"{cg} {ce}")
                        for cg in genera if edits(g, cg) <= len(g) // 4
                        for ce in difflib.get_close_matches(e, self.by_genus[cg], n=3, cutoff=0.6)
                        if edits(e, ce) <= len(e) // 4)
        if not scored:
            return None, "unmatched"
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return None, "ambiguous"
        return scored[0][1], "corrected"

    def __call__(self, name):
        if not self.names:
            return name, "no reference"
        parts = name.split()
        sp, infra = " ".join(parts[:2]), parts[2:]
        if sp in self.names:
            fixed, how = sp, "exact"
        else:
            fixed, how = self.best(sp)
            if fixed is None:
                return name, how
        epithet = fixed.split()[1]
        for i in range(1, len(infra), 2):
            if difflib.SequenceMatcher(None, infra[i], epithet).ratio() >= 0.8:
                infra[i] = epithet
        out = " ".join([fixed, *infra])
        return out, "exact" if out == name else "corrected"


def distrib_paragraphs(lines, known):
    """Join (text, starts_paragraph, page) lines into paragraphs, mending hyphenated words. After a
    "Distrib." paragraph a new entry may follow with no gap; it starts at a citation line (a name or
    a genus heading with numbers), at a name whose genus is known or close to the current genus
    heading, or at a genus alone on its line (OCR splits "Ligularia / dux (Clarke) ...")."""
    paras, in_dist, head = [], False, ""

    def genus_ok(g):
        return g.endswith((".", ",")) or g in known or bool(head and difflib.SequenceMatcher(None, g, head).ratio() >= 0.75)

    for text, start, page in lines:
        t = text.strip()
        nm = NAME.match(t)
        lone = re.fullmatch(r"[A-Z][a-z]{3,}", t)
        if not nm and (gh := GENUS_HEAD.match(t)):
            head = gh[1].capitalize()
        entry = (re.search(r"\d", t) and (nm or INFRA_LINE.match(t) or GENUS_HEAD.match(t) or GENUS_TITLE.match(t))) \
            or (nm and genus_ok(nm["g"])) or (lone and genus_ok(t))
        if start or not paras or DISTRIB.match(t) or (in_dist and entry and not looks_like_distribution(t)):
            paras.append([t, page])
            in_dist = bool(DISTRIB.match(t)) or (in_dist and not entry)
        else:
            prev = paras[-1][0]
            paras[-1][0] = prev[:-1] + t if re.search(r"[a-z]-$", prev) else f"{prev} {t}"
    return paras


def parse_entries(lines, layout, family="", known=frozenset(), families=(), one_per_block=False):
    """Entries from (text, starts_paragraph, page) lines.

    layout "block" (Flowering Plants of India 2009, Florae Indicae Enumeratio Monocotyledonae 1989):
    an accepted name, its synonyms (each starting a line or a paragraph), then a distribution line
    with no citation, which closes the entry. With one_per_block (the 2009 book), each block after a
    gap is a new taxon, so a misread distribution cannot turn the next taxon into a synonym.
    layout "distrib" (Asteraceae 1995, Census of Indian
    Pteridophytes 1984): each paragraph that starts with a name is an accepted entry; synonyms run on
    inside it and are not taken; a "Distrib.:" paragraph closes it.
    """
    rows, group, closed = [], [], True
    genus = ""
    by_initial = {}     # latest genus heading for each initial, for "P. cretica"

    def emit(name, rank, status, rest, page):
        row = {"family": family, "name": name, "rank": rank, "status": status, "authority": authority(rest),
               "states": "", "page": page}
        rows.append(row)
        group.append(row)
        return row

    def close(dist):
        nonlocal group, closed
        st = states_of(dist)
        for r in group:
            r["states"] = st
        group, closed = [], True

    def name_from(m, text):
        g = m["g"]
        if g.endswith((".", ",")):
            # A capitalised old-style epithet ("Clarkei Bak.") can be misread as a heading; the
            # latest heading with the same initial is the genus meant.
            g = genus if genus[:1] == g[0] else by_initial.get(g[0])
            if not g:
                return None
        else:
            g = fix_genus(g, genus, known)
        sp = f"{g} {'× ' if m['x'] else ''}{m['e']}"
        suffix, rank = infra_suffix(m["i"])
        return (f"{sp} {suffix}".strip(), rank, sp, text[m.end():])

    current_species = ""
    if layout == "distrib":
        paras = distrib_paragraphs(lines, known)
        for text, page in paras:
            text = re.sub(r"\s+", " ", text).strip()
            if DISTRIB.match(text):
                close(DISTRIB.sub("", text))
                continue
            if fam := family_of(text, families):
                family = fam
                continue
            g = None if NAME.match(text) else GENUS_HEAD.match(text) or GENUS_TITLE.match(text)
            if g:
                genus = g[1].capitalize()
                by_initial[genus[0]] = genus
                continue
            m = NAME.match(text)
            parsed = name_from(m, text) if m else None
            if parsed and not closed and genus and not m["g"].endswith((".", ",")) and parsed[2].split()[0] != genus:
                continue    # a synonym run on from the previous page or column, not a new entry
            if parsed and plausible(parsed[0]):
                close("") if group else None
                name, rank, current_species, rest = parsed
                emit(name, rank, "accepted", rest, page)
                closed = False
            elif current_species and (mi := INFRA_LINE.match(text)):
                close("") if group else None
                suffix, rank = infra_suffix(mi["i"])
                emit(f"{current_species} {suffix}", rank, "accepted", text[mi.end():], page)
                closed = False
        return rows

    prev_closed = True
    dist = None
    for text, start, page in lines:
        text = re.sub(r"\s+", " ", text).strip()
        fam = family_of(text, families)
        if dist is not None and not fam and not start and (not NAME.match(text) or looks_like_distribution(text)):
            dist += " " + text              # distribution runs on
            continue
        if dist is not None:
            close(dist)
            dist = None
        if fam:
            family = fam
            prev_closed = True
            continue
        m = NAME.match(text)
        parsed = name_from(m, text) if m else None
        head = (start or prev_closed)
        if GENUS_HEAD.match(text) and not m and head:
            genus = GENUS_HEAD.match(text)[1].capitalize()
            by_initial[genus[0]] = genus
            close("") if group else None
            prev_closed = True
            continue
        infra = INFRA_LINE.match(text) if head and current_species and not m else None
        no_digits = not re.search(r"\d", text)
        if DISTRIB.match(text) or (not infra and prev_closed and not closed and no_digits
                                   and (not (parsed and plausible(parsed[0])) or looks_like_distribution(text))):
            dist = DISTRIB.sub("", text)
            prev_closed = True
            continue
        if head and parsed and plausible(parsed[0]):
            name, rank, sp, rest = parsed
            if one_per_block and start is True and not closed:
                close("")       # a new block is a new taxon, even when its distribution was not read
            if closed:
                current_species = sp
                emit(name, rank, "accepted", rest, page)
                closed = False
            else:
                emit(name, rank, "synonym", rest, page)
        elif infra:
            suffix, rank = infra_suffix(infra["i"])
            emit(f"{current_species} {suffix}", rank, "accepted", text[infra.end():], page)
            closed = False
        # A bare infraspecific line ("var. bipinnatifidus,") is complete: the distribution follows.
        prev_closed = bool(CLOSED.search(text)) or bool(infra and no_digits)
    if dist is not None:
        close(dist)
    return rows


# ---------- quality checks and output ----------

def correct(rows, fixer):
    """Apply the reference spelling. Accepted names are always kept (a name missing from the
    reference may be new or local); a synonym the reference cannot confirm is dropped, since italic
    synonyms are what OCR reads worst. Returns (rows kept, review rows for every name not exact)."""
    kept, qc = [], []
    for r in rows:
        name, how = fixer(r["name"])
        keep = r["status"] == "accepted" or how in ("exact", "corrected")
        if how != "exact":
            qc.append({"checklist": r["checklist"], "page": r["page"], "status": r["status"],
                       "ocr_name": r["name"], "name": name, "match": how, "kept": keep})
        if keep:
            kept.append({**r, "name": name})
    return kept, qc


def dedupe(rows):
    """One row per name in each checklist, in first-seen order; an accepted row wins over a synonym."""
    seen, out = {}, []
    for r in rows:
        k = (r["checklist"], r["name"])
        if k not in seen:
            seen[k] = len(out)
            out.append(r)
        elif r["status"] == "accepted" and out[seen[k]]["status"] != "accepted":
            out[seen[k]] = r
    return out


def known_genera():
    f = REF / "known_genera.txt"
    return frozenset(f.read_text().split()) if f.exists() else frozenset()


def plant_families():
    """Family names for matching OCR headings: the families of Kew WCVP's Indian plants and the older
    names the books use (Asclepiadaceae, Aspidiaceae, Gramineae...)."""
    return (REF / "plant_families.txt").read_text().split()


def parse_book(spec, pages, known):
    lo, hi = spec["pages"]
    lines = [(t, s, n) for n in range(lo, hi + 1) if str(n) in pages
             for t, s in reading_order(pages[str(n)], spec["columns"], spec.get("header"), spec.get("top", 0))]
    families = spec["families"] if "families" in spec else plant_families()
    rows = parse_entries(lines, spec["layout"], spec.get("family", ""), known, families, spec.get("one_per_block", False))
    for r in rows:
        r.update(source="BSI", checklist=spec["title"], group=spec["group"], edition=spec["edition"], url=spec["url"])
    return rows


def stated_taxa(stated):
    """Species and infraspecific taxa the book says it lists."""
    return sum(stated.get(k, 0) for k in ("taxa", "species", "species_more_than", "subspecies", "varieties",
                                          "subvarieties", "forms"))


def summary(rows, specs, qc, reference, duplicates):
    out = {"source": "Botanical Survey of India", "files": ["bsi_checklist.csv", "bsi_checklist_qc.csv"],
           "name_reference": reference, "duplicates_removed": duplicates, "checklists": []}
    for s in specs:
        rs = [r for r in rows if r["checklist"] == s["title"]]
        acc = [r for r in rs if r["status"] == "accepted"]
        checks = [q for q in qc if q["checklist"] == s["title"]]
        out["checklists"].append({
            "key": s["key"], "title": s["title"], "edition": s["edition"], "url": s["url"], "group": s["group"],
            "rows": len(rs), "accepted": len(acc),
            "accepted_species": sum(r["rank"] == "species" for r in acc),
            "accepted_infraspecific": sum(r["rank"] != "species" for r in acc),
            "synonyms": len(rs) - len(acc), "with_states": sum(bool(r["states"]) for r in acc),
            "stated_in_book": s["stated"],
            "stated_taxa": stated_taxa(s["stated"]),
            "accepted_share_of_stated": round(len(acc) / stated_taxa(s["stated"]), 3),
            "name_check": {"exact": len(rs) - sum(q["kept"] for q in checks),
                           **{m: sum(q["match"] == m and q["kept"] for q in checks)
                              for m in ("corrected", "unmatched", "ambiguous", "no reference")},
                           "synonyms_dropped": sum(not q["kept"] for q in checks)}})
    by_group = {}
    for r in rows:
        if r["status"] == "accepted":
            by_group.setdefault(r["group"], set()).add(r["name"])
    out["accepted_names_by_group"] = {g: len(v) for g, v in sorted(by_group.items())}
    return out


def reference_names(path):
    """Binomials from Kew WCVP (accepted names and synonyms), or none when the file is missing."""
    if not path or not Path(path).exists():
        log(f"no name reference at {path}: OCR spellings are kept as read")
        return []
    import duckdb
    return [r[0] for r in duckdb.sql(
        f"SELECT DISTINCT name FROM '{path}' WHERE regexp_matches(name, '^[A-Z][a-z-]+ [a-z-]+$')").fetchall()]


def write_csv(rows, path, fields=FIELDS):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in fields} for r in rows)
    tmp.replace(path)


def run(publish=False, minutes=None, only=None, env=ROOT / ".env", names=WCVP_NAMES):
    import requests
    from pipeline import health, r2
    s3 = None
    if publish:
        from dotenv import load_dotenv
        load_dotenv(env, override=True)
        s3 = r2.client()
    http = requests.Session()
    http.headers["User-Agent"] = health.ua()
    deadline = time.monotonic() + minutes * 60 if minutes is not None else None
    known = known_genera()
    rows, specs = [], [s for s in CHECKLISTS if not only or s["key"] in only]
    for spec in specs:
        fetch_pdf(http, spec, s3)
        left = None if deadline is None else max(0, (deadline - time.monotonic()) / 60)
        pages = ocr(spec, s3, left)
        if pages is None:
            log("stopped at the time limit; run again to continue")
            return 1
        book = parse_book(spec, pages, known)
        log(f"{spec['key']}: {sum(r['status'] == 'accepted' for r in book)} accepted, "
            f"{sum(r['status'] == 'synonym' for r in book)} synonyms")
        rows += book
    rows, qc = correct(rows, Corrector(reference_names(names)))
    n = len(rows)
    rows = dedupe(rows)
    out, qc_out, summ_out = OUT / "bsi_checklist.csv", OUT / "bsi_checklist_qc.csv", OUT / "bsi_checklist_summary.json"
    write_csv(rows, out)
    write_csv(qc, qc_out, ["checklist", "page", "status", "ocr_name", "name", "match", "kept"])
    reference = f"Kew WCVP names ({Path(names).name})" if names and Path(names).exists() else None
    summ = summary(rows, specs, qc, reference, n - len(rows))
    summ_out.write_text(json.dumps(summ, indent=1, ensure_ascii=False) + "\n")
    log(json.dumps(summ["accepted_names_by_group"]))
    if s3 is not None:
        for f in (out, qc_out, summ_out):
            log(f"{f.name}: {'uploaded' if r2.sync_file(s3, f, f'{R2_DIR}/{f.name}', immutable=False) else 'unchanged in R2'}")
    return 0


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--publish", action="store_true", help="read and write the R2 cache, publish the CSV")
    p.add_argument("--minutes", type=float, help="stop cleanly after this time")
    p.add_argument("--only", nargs="*", help="checklist keys")
    p.add_argument("--env", default=ROOT / ".env", type=Path, help="file with the R2_* keys")
    p.add_argument("--names", default=WCVP_NAMES, type=Path, help="Kew WCVP name lookup (parquet, column name)")
    a = p.parse_args()
    sys.exit(run(a.publish, a.minutes, a.only, a.env, a.names))


if __name__ == "__main__":
    main()
