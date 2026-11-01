"""Extract species names from the ZSI Fauna of India Checklist PDFs (first pass: names only).

Moved from fnf (scripts/17_zsi_checklist_parse.py) on 1 Nov 2026, with two fixes that bring back names the parser
lost: an authority's year may be in square or round brackets ("(Cramer, [1780])", "Walker, (1859)", most of the
Lepidoptera checklist), an authority may start with a particle ("(de Nicéville, 1887)"), and
the dictionary pass reads past letters OCR confuses (fold: "grayll" is grayii, "Lxobrychus" is Ixobrychus) when
exactly one Catalogue of Life name fits.

The 121 checklists come from different teams, so layouts differ (numbered lists, tables with
distribution columns, family headings). This pass relies on one shape they all share: a
scientific name followed by its authority with a year, e.g.
    Araneus bilunifer Pocock, 1900*
    Anathana ellioti (Waterhouse, 1850)
    Endelus (Endelus) assamensis Obenberger, 1922
Family = the nearest "...idae" word before the name. Text after the "References" heading is
ignored. Pages whose text is drawn as vector outlines (9 checklists, 817 pages: beetles, flies,
molluscs, birds, annelids and others) are read with
Tesseract OCR at 300 dpi, cached per page.

Two more passes recover names the main pattern misses:
- abbreviated genera ("T. optatus" under "Genus Truncopes", mites and nematodes) are expanded
  from the most recent genus with that initial;
- on OCR'd pages only, a dictionary pass accepts a known genus followed within six words by an
  epithet that forms a real Catalogue of Life name (the bird table splits genus and epithet
  across lines, with the authority between), after folding OCR look-alikes, when one name fits.
  It cannot invent names; its rows have no authority.
Each row records which pass found it (extraction = pattern | dictionary).

Quality check per checklist: names found vs the species count stated in its own introduction.

Source and credit (ZSI website policy: reproduction free of charge, accurately, not misleading,
source prominently acknowledged):
    Zoological Survey of India. Fauna of India Checklist. https://zsi.gov.in

Input:  the PDFs and OCR cache in fnf (FNF, default ~/Projects/biodiversity/fnf): data/raw/zsi/checklists/*.pdf,
        data/raw/zsi/ocr*/, data/raw/zsi/checklist_links.json; data/fnf/col_xr_2026-09-25/animals.parquet
        (pipeline/zsi_match.py builds it)
Output: data/fnf/zsi/zsi_checklist.csv, data/fnf/zsi/zsi_checklist_qc.csv (local, gitignored)
Usage:  .venv/bin/python -m pipeline.zsi_parse [name-prefix ...]; then python -m pipeline.zsi_match
"""

import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FNF = Path(os.environ.get("FNF", Path.home() / "Projects" / "biodiversity" / "fnf"))
ZSI = FNF / "data" / "raw" / "zsi"
SRC = ZSI / "checklists"
OCR = ZSI / "ocr"
OCR4 = ZSI / "ocr_psm4"
MODES = ZSI / "ocr_mode.json"
COL_PQ = ROOT / "data" / "fnf" / "col_xr_2026-09-25" / "animals.parquet"
OUT = ROOT / "data" / "fnf" / "zsi" / "zsi_checklist.csv"
QC = ROOT / "data" / "fnf" / "zsi" / "zsi_checklist_qc.csv"

UP = "A-ZÀ-ÖØ-ÞĀĂĄĆČĎĐĒĘĚĞĪŁŃŇŌŐŒŘŚŞŠŢŤŪŮŰŹŻŽ"
LO = "a-zß-öø-ÿāăąćčďđēęěğīıłńňōőœřśşšţťūůűźżž"
YEAR = r"(?:1[789]\d\d|20[0-2]\d)"
NAME = (rf"(?P<name>[{UP}][{LO}]+(?: \([{UP}][{LO}]+\))? (?!(?:et|in|and|from|of|ex|van|von|de|da|du|del|der|den|di|la|le|sensu|sp|spp|are|as)\b)[{LO}][{LO}\-]+"
        rf"(?: (?!(?:et|in|and|from|of|ex|van|von|de|da|du|del|der|den|di|la|le|sensu|sp|spp|are|as)\b)[{LO}][{LO}\-]{{2,}})?)")
AUTH = rf"(?P<auth>\(?(?:(?:de|da|du|van|von|der|den|di|la|le)\s)*[{UP}][^\d()\[\]\n]{{0,90}}?,? ?(?:\[{YEAR}\]|\({YEAR}\)|{YEAR})[a-z]?\)?)"   # [1780]: not printed on the work; Walker, (1859)
ENTRY = re.compile(rf"(?<![{LO}{UP}]){NAME} {AUTH}(?P<mark>\s?[*#†$@]+)?")
FAMILY = re.compile(rf"\b([{UP}][{LO}]+idae)\b")
REFS = re.compile(r"^\s*(References|REFERENCES|Literature cited|LITERATURE CITED|Bibliography)\b", re.MULTILINE)
STATED = re.compile(r"([\d,]{2,7})\s+(?:valid\s+|extant\s+|known\s+)?(?:species|spp)", re.IGNORECASE)
VERSION = re.compile(r"VERSION\s+(\d+\.\d+)", re.IGNORECASE)
DOI = re.compile(r"doi\.org/(10\.26515/\S+)", re.IGNORECASE)
CYRILLIC = str.maketrans("аеорсухіАВЕКМНОРСТХ", "aeopcyxiABEKMHOPCTX")
_N = rf"[{UP}][{LO}]+(?: \([{UP}][{LO}]+\))? [{LO}][{LO}\-]+(?: [{LO}][{LO}\-]{{2,}})?"
SPLIT_NAME = re.compile(rf"\s*({_N})\s*(\[?{YEAR}\]?\)?)?\s*")
AUTH_TAIL = re.compile(rf"(\(?[{UP}][^()|\d\n]{{0,60}}?,\s*(?:\[?{YEAR}\]?\)?)?)\s*$")
NOT_AUTH = re.compile(r"\b(?:species|genus|genera|family|described|recorded|reported|India|from|were|was|is|are)\b")
# the next heading read as an authority: "Malabar coast Genus Karumballichirus Poore, 2019"
NOT_AUTH_HEAD = re.compile(r"\b(?:Genus|Subgenus|Family|FAMILY|Subfamily|Order|Redesignated|Redesinated)\b|:")


ABBREV = re.compile(
    rf"\bGenus (?P<head>[{UP}][{LO}]+)"
    rf"|(?<![{LO}{UP}.])(?P<full>[{UP}][{LO}]{{2,}})(?= (?:\([{UP}][{LO}]+\) )?(?!(?:and|et|from|ex|van|von|del|der|den|sensu)\b)[{LO}]{{3,}})"
    rf"|(?<![{LO}{UP}])(?P<abbr>[{UP}])\. (?:\([{UP}][{LO}]*\.?\) )?(?=[{LO}]{{3,}})")
WORD = re.compile(rf"[{UP}{LO}][{UP}{LO}\-]{{2,}}")   # also OCR-garbled words with capitals inside
_COL = {}


def expand_abbrev(text, last):
    """Mites, nematodes and others write "T. optatus" under "Genus Truncopes": put the genus back.
    `last` maps an initial to the most recent genus with that initial; it carries across pages."""
    out, pos = [], 0
    for m in ABBREV.finditer(text):
        g = m.group("head") or m.group("full")
        if g:
            last[g[0]] = g
        elif m.group("abbr") in last:
            out += [text[pos:m.start()], last[m.group("abbr")] + " "]
            pos = m.end()
    return "".join(out) + text[pos:]


def fold(word):
    """A word with the letters OCR confuses made equal: i, l, I, 1 and | are one letter; rn is m; vv is w."""
    return re.sub(r"[il1|]", "i", word.lower()).replace("rn", "m").replace("vv", "w")


def col_names():
    """Animal and protist binomials in the Catalogue of Life (cache built by pipeline/zsi_match.py)."""
    if not _COL:
        import duckdb
        names = duckdb.sql(f"SELECT DISTINCT canonical_name FROM '{COL_PQ}' WHERE rank = 'species'").fetchall()
        _COL["names"] = {n for (n,) in names}
        _COL["genera"] = {n.split(" ")[0] for n in _COL["names"]}
    return _COL


def folded(col):
    """{folded genus: {folded epithet: [names]}} for the dictionary pass, built once per name set."""
    if "folded" not in col:
        idx = {}
        for n in col["names"]:
            if " " not in n:
                continue                   # a few Catalogue of Life species names have one word
            g, e = n.split(" ", 1)
            idx.setdefault(fold(g), {}).setdefault(fold(e), []).append(n)
        col["folded"] = idx
    return col["folded"]


def one_edit(a, b):
    """True when a and b differ by one letter changed, added or removed."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


# An epithet as OCR may print it: lower case, or garbled with capitals inside ("eplsCcOpus", "CUurruca").
EPITHET_LIKE = re.compile(r"[a-z][A-Za-z\-]+|[A-Z][A-Za-z]*[A-Z][A-Za-z]*")


def dictionary_names(text, col=None):
    """OCR'd tables (birds) can split genus and epithet across lines with the authority between.
    Accept a genus followed within six words by an epithet that forms a real name: exactly; else after folding OCR
    look-alikes; else, for a word of 6 letters or more, one letter from a name of that genus. The last two only
    when one name fits."""
    col = col or col_names()
    idx, words = folded(col), [(w.group(), w.start()) for w in WORD.finditer(text)]
    found = []
    for k, (w, at) in enumerate(words):
        if not (w[0].isupper() and w[1:].islower()) or (w not in col["genera"] and fold(w) not in idx):
            continue
        epithets = idx.get(fold(w), {})
        for w2, _ in words[k + 1:k + 7]:
            if not EPITHET_LIKE.fullmatch(w2):
                continue
            if f"{w} {w2}" in col["names"]:
                found.append((f"{w} {w2}", at))
                break
            f2 = fold(w2)
            fits = epithets.get(f2, [])
            if not fits and len(f2) >= 6:
                fits = [n for e, ns in epithets.items() if one_edit(e, f2) for n in ns]
            if len(fits) == 1:
                found.append((fits[0], at))
                break
            if fits:
                break                      # a look-alike of two names: not guessed
    return found


def needs_ocr(page):
    """Vector-outline pages keep only a running header as real text."""
    return len(page.get_text().strip()) < 300 and len(page.get_drawings()) > 100


def ocr(pdf_name, i, page, mode):
    """mode "auto": MuPDF's Tesseract call at 300 dpi (suits the beetle and fly tables).
    mode "psm4": 600 dpi greyscale, Tesseract page mode 4 (suits molluscs, birds, bryozoans)."""
    cache = (OCR if mode == "auto" else OCR4) / Path(pdf_name).stem / f"{i:04d}.txt"
    if cache.exists():
        return cache.read_text()
    cache.parent.mkdir(parents=True, exist_ok=True)
    if mode == "auto":
        t = page.get_text(textpage=page.get_textpage_ocr(language="eng", dpi=300, full=True))
    else:
        import pymupdf

        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "p.png"
            page.get_pixmap(dpi=600, colorspace=pymupdf.csGRAY).save(png)
            t = subprocess.run(["tesseract", str(png), "-", "--psm", "4"], capture_output=True,
                               text=True, check=True).stdout
    cache.write_text(t)
    return t


def join_split_names(t):
    """Bird table: the name sits on its own line, its authority at the end of the line above."""
    out = []
    for line in t.split("\n"):
        m = SPLIT_NAME.fullmatch(line)
        a = AUTH_TAIL.search(out[-1]) if m and out else None
        if a:
            line = f"{m.group(1)} {a.group(1)}{' ' + m.group(2) if m.group(2) else ''}"
        out.append(line)
    return "\n".join(out)


def choose_mode(pdf, doc, pages):
    """Try both OCR modes on three sample pages; keep the one that finds more names."""
    modes = json.loads(MODES.read_text()) if MODES.exists() else {}
    if pdf.name not in modes:
        sample = pages[len(pages) // 4::max(1, len(pages) // 4)][:3]
        score = {m: sum(len(ENTRY.findall(flat(join_split_names(ocr(pdf.name, i, doc[i], m)))))
                        for i in sample) for m in ("auto", "psm4")}
        modes[pdf.name] = max(score, key=score.get)
        print(f"  OCR mode {modes[pdf.name]} {score}", flush=True)
        MODES.write_text(json.dumps(modes, indent=1))
    return modes[pdf.name]


def flat(t):
    t = unicodedata.normalize("NFKC", t)        # ﬁ ﬂ ﬃ ligatures -> plain letters
    t = t.translate(CYRILLIC)                  # look-alike Cyrillic letters typed into Latin names
    t = re.sub(r"-\n(?=[a-z])", "", t)          # words split over lines
    return re.sub(r"[ \t ]*\n[ \t \n]*", " ", t).replace("  ", " ")


def parse(pdf, url):
    import pymupdf

    doc = pymupdf.open(pdf)
    head = flat("\n".join(doc[i].get_text() for i in range(min(4, len(doc)))))
    stated = [int(m.group(1).replace(",", "")) for sent in re.split(r"(?<=\.) (?=[A-Z])", head)
              if re.search(r"\bIndia", sent) and not re.search(r"endemic|world|global", sent, re.IGNORECASE)
              for m in STATED.finditer(sent) if int(m.group(1).replace(",", "")) < 200000]
    ver, doi = VERSION.search(head), DOI.search(head)
    rows, seen, family, last_genus = [], set(), "", {}
    ocr_pages = {i for i, p in enumerate(doc) if needs_ocr(p)}
    mode = choose_mode(pdf, doc, sorted(ocr_pages)) if ocr_pages else ""
    for i, page in enumerate(doc):
        raw = join_split_names(ocr(pdf.name, i, page, mode)) if i in ocr_pages else page.get_text()
        refs = REFS.search(raw)
        if refs and i > 2:
            raw = raw[:refs.start()]
        text = expand_abbrev(flat(raw), last_genus)
        hits = [(m.start(), m.group("name"), m.group("auth").strip(), (m.group("mark") or "").strip(), "pattern")
                for m in ENTRY.finditer(text)
                if not NOT_AUTH.search(m.group("auth")) and not NOT_AUTH_HEAD.search(m.group("auth"))]
        if i in ocr_pages:
            hits += [(at, name, "", "", "dictionary") for name, at in dictionary_names(text)]
        pos = 0
        for at, name, auth, mark, how in sorted(hits):
            fams = FAMILY.findall(text, pos, at)
            family = fams[-1] if fams else family
            pos = max(pos, at)
            if name in seen:
                continue
            seen.add(name)
            rows.append({"checklist": pdf.name, "family": family, "name": name,
                         "rank": "subspecies" if len(re.sub(r" \(.*?\)", "", name).split()) == 3 else "species",
                         "authority": auth, "mark": mark, "page": i + 1, "extraction": how,
                         "version": ver.group(1) if ver else "", "doi": doi.group(1).rstrip(".") if doi else "",
                         "source_url": url})
        # a heading after the page's last name (Cercopithecidae at the foot of a page) carries over
        fams = FAMILY.findall(text, pos)
        family = fams[-1] if fams else family
        if refs and i > 2:
            break
    qc = {"checklist": pdf.name, "pages": len(doc), "names": len(rows),
          "species": sum(r["rank"] == "species" for r in rows),
          "ocr_mode": mode, "stated_max": max(stated) if stated else "", "stated_all": " ".join(map(str, stated[:6]))}
    return rows, qc


def main():
    links = {name: url for _, name, url in json.loads((ZSI / "checklist_links.json").read_text())}
    base = "https://zsi.gov.in/public/uploads/documents/checklist/hindi/"
    pdfs = sorted(SRC.glob("*.pdf"))
    if sys.argv[1:]:
        pdfs = [p for p in pdfs if any(p.name.startswith(a) for a in sys.argv[1:])]
    rows, qcs = [], []
    for pdf in pdfs:
        r, q = parse(pdf, links.get(pdf.name, base + pdf.name))
        rows += r
        qcs.append(q)
        print(f"{pdf.name}: {q['names']} names, stated {q['stated_all']}", flush=True)
    for path, data in ((OUT, rows), (QC, qcs)):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)
    print(f"wrote {len(rows)} names from {len(pdfs)} checklists")


if __name__ == "__main__":
    main()
