"""BSI national checklists: OCR cache and restart, page layout, and the entry parser."""

import json

import pymupdf
import pytest

from pipeline import bsi_checklist as bc


def blank_pdf(path, n):
    doc = pymupdf.open()
    for _ in range(n):
        doc.new_page()
    doc.save(path)


def test_ocr_resumes_and_saves_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "CACHE", tmp_path)
    blank_pdf(tmp_path / "x.pdf", 3)
    spec = {"key": "x"}
    seen = []

    def fake(page):
        seen.append(page.number)
        if page.number == 2:
            raise TimeoutError("killed")
        return {"w": 595, "lines": [[10, 10, 50, f"page {page.number + 1}"]]}

    with pytest.raises(TimeoutError):
        bc.ocr(spec, ocr_page=fake)
    saved = json.loads((tmp_path / "x_ocr.json").read_text())
    assert sorted(saved) == ["1", "2"]          # kept although the run failed
    seen.clear()
    pages = bc.ocr(spec, ocr_page=lambda p: seen.append(p.number) or {"w": 595, "lines": []})
    assert seen == [2] and sorted(pages) == ["1", "2", "3"]
    seen.clear()
    bc.ocr(spec, ocr_page=lambda p: seen.append(p.number))
    assert seen == []                           # second run: no new work


def test_ocr_stops_at_time_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "CACHE", tmp_path)
    blank_pdf(tmp_path / "x.pdf", 3)
    pages = bc.ocr({"key": "x"}, minutes=0, ocr_page=lambda p: {"w": 1, "lines": []})
    assert pages is None                        # unfinished: caller must not parse a partial book
    assert json.loads((tmp_path / "x_ocr.json").read_text()) == {}


def test_reading_order_two_columns_and_paragraphs():
    page = {"w": 600, "lines": [
        [40, 30, 200, "FLORAE INDICAE ENUMERATIO"],
        [320, 100, 500, "Right top"],
        [40, 100, 280, "Left one"],
        [40, 114, 280, "Left two"],
        [40, 140, 280, "Left new para"],
        [150, 140, 280, "tail"],
        [320, 114, 500, "Right second"],
        [300, 780, 320, "197"],
    ]}
    got = bc.reading_order(page, columns=2, header=r"ENUMERATIO")
    assert got == [("Left one", "top"), ("Left two", False), ("Left new para tail", True),
                   ("Right top", "top"), ("Right second", False)]


def test_reading_order_drops_top_band_and_ignores_fragments_for_pitch():
    page = {"w": 600, "lines": [[180, 38, 260, "Fiore indicus"], [330, 38, 400, "Esumeretia"],
                                [40, 100, 200, "one"], [210, 103, 280, "piece"], [40, 107.5, 120, "bit"],
                                [40, 114, 280, "two"], [40, 128, 280, "three"], [40, 150, 280, "new"]]}
    assert bc.reading_order(page, 1, top=55) == [("one piece", "top"), ("bit", False), ("two", False),
                                                 ("three", False), ("new", True)]


def test_bare_year_is_kept_but_footer_page_number_dropped():
    page = {"w": 595, "lines": [[75, 242, 500, "Polyscias scutellaria (Burm.f.) Fosberg in Taxon 14: 84."],
                                [75, 256, 110, "1965."], [75, 270, 400, "Crassula scutellaria Burm.f., Fl. ind. 76."],
                                [290, 790, 310, "151"]]}
    assert [t for t, _ in bc.reading_order(page)] == [
        "Polyscias scutellaria (Burm.f.) Fosberg in Taxon 14: 84.", "1965.", "Crassula scutellaria Burm.f., Fl. ind. 76."]


BLOCK = [  # Flowering Plants of India, Dicotyledons (2009): one block per taxon
    ("ARALIACEAE", True),
    ("PANAX L., Sp. pl. 1058, 1753.", True),
    ("Panax bipinnatifidus Seem. in J. Bot. 6: 54. 1868; Bennet & B.K. Sharma in Indian Forester 109: 540. 1983.", True),
    ("Aralia bipinnatifida (Seem.) C.B. Clarke in Hook.f, Fl. Brit. India 2: 722. 1879,", False),
    ("var. bipinnatifidus,", False),
    ("E Himalaya.", False),
    ("var. angustifolius (Burkill) J. Wen in Punja (Ed.), Util. biotech. (Proc.", True),
    ("Intern. Ginseng Workshop : 73, 2001.", False),
    ("Panax assamicus R. N. Banerjee in Bull. Bot. Surv. India 10: 23. 1968.", False),
    ("Hotter parts of India, Sikkim.", False),
    ("Panax pseudoginseng Wall. in Trans. Med. Soc. Calcutta 4: 117. 1829; R.N. Banerjee in Rec. Bot. Surv.", True),
    ("India 20: 112. 1973.", False),
    ("Plains of Uttar Pradesh, W Ghats, Kerala & Tamil Nadu.", False),
    ("Chloris dolichostachya Lagasca, Gen. & Sp. Pl. 5. 1816.", True),
    ("Chloris incompleta Roth, Nov. Pl. Sp. 60. 1821;", True),
    ("Hook. f., Fl. Brit. India 7: 290. 1896.", False),
    ("Introduced.", False),
]


def test_block_layout_accepted_synonyms_and_states():
    rows = bc.parse_entries([(t, p, 150) for t, p in BLOCK], layout="block")
    got = [(r["family"], r["name"], r["rank"], r["status"], r["authority"], r["states"]) for r in rows]
    assert got == [
        ("Araliaceae", "Panax bipinnatifidus", "species", "accepted", "Seem.", ""),
        ("Araliaceae", "Aralia bipinnatifida", "species", "synonym", "(Seem.) C.B. Clarke", ""),
        ("Araliaceae", "Panax bipinnatifidus var. bipinnatifidus", "variety", "accepted", "", ""),
        ("Araliaceae", "Panax bipinnatifidus var. angustifolius", "variety", "accepted", "(Burkill) J. Wen", "Sikkim"),
        ("Araliaceae", "Panax assamicus", "species", "synonym", "R. N. Banerjee", "Sikkim"),
        ("Araliaceae", "Panax pseudoginseng", "species", "accepted", "Wall.", "Kerala;Tamil Nadu;Uttar Pradesh"),
        ("Araliaceae", "Chloris dolichostachya", "species", "accepted", "Lagasca", ""),
        ("Araliaceae", "Chloris incompleta", "species", "synonym", "Roth", ""),
    ]
    assert rows[0]["page"] == 150


DISTRIB = [  # Florae Indicae Enumeratio: Asteraceae (1995) and Census of Indian Pteridophytes (1984)
    ("LIGULARIA Cass. in Bull. Sci. Soc. Philom. 198. 1816.", True),
    ("Ligularia amplexicaulis DC., Prodr. 6: 314. 1838. Senecio amplexicaulis Wall. ex Clarke,", True),
    ("Comp. Ind. 204. 1876.", False),
    ("Distrib.: INDIA: Jammu & Kashmir, Uttar", True),
    ("Pradesh, Sikkim; BHUTAN, ECUADOR.", False),
    ("Ligularia hookeri subsp. clarkei f. angusti-", True),
    ("folium (R. Good) R. Mathur, Comb. nov.", False),
    ("Distrib.: INDIA: Sikkim.", True),
    ("PTERIS L. Sp. Pl. 1073. 1753.", True),
    ("P. asperula J. Sm. ex Hieron. Hedw. 55 : 361. 1914. P. quadriaurita", True),
    ("Distrib. : S. E. India, Burma.", False),
    ("PTERIDACEAE Ching", True),
    ("Pteris L. Sp. Pl. 2 : 1073. 1753.", True),
    ("Lectotype : P. longifolia L. Sp. Pl. 2 : 1074. 1753.", True),
    ("P. confusa T. G. Walker in Kew Bull. 14 : 329. 1960.", True),
    ("Distrib. : India (Kerala), Sri Lanka.", True),
    ("P. cretica L. Mant. Pl. 130. 1767.", False),          # no gap after the distribution
    ("Pycnodoria cretica (L.) Small, Ferns 1938.", True),   # synonym at the top of a new page
    ("Distrib. : India (Sikkim).", False),
    ("Cosmopolitan weed. Tropical", False),                 # place text, not a name
    ("Bidens comosa (Gray) Wiegand in Bull.", False),       # a name line with no numbers
    ("Torrey Bot. Club 436. 1897.", False),
    ("Distrib.: INDIA: Himachal Pradesh.", False),
]


def test_distrib_layout_expands_abbreviated_genus():
    rows = bc.parse_entries([(t, p, 9) for t, p in DISTRIB], layout="distrib", known={"Pteris", "Bidens"})
    got = [(r["name"], r["rank"], r["status"], r["authority"], r["states"]) for r in rows]
    assert got == [
        ("Ligularia amplexicaulis", "species", "accepted", "DC.", "Jammu and Kashmir;Sikkim;Uttar Pradesh"),
        ("Ligularia hookeri subsp. clarkei f. angustifolium", "form", "accepted", "(R. Good) R. Mathur", "Sikkim"),
        ("Pteris asperula", "species", "accepted", "J. Sm. ex Hieron.", ""),
        ("Pteris confusa", "species", "accepted", "T. G. Walker", "Kerala"),
        ("Pteris cretica", "species", "accepted", "L.", "Sikkim"),
        ("Bidens comosa", "species", "accepted", "(Gray) Wiegand", "Himachal Pradesh"),
    ]


@pytest.mark.parametrize("name,ok", [
    ("Panax ginseng", True), ("Hotter parts", False), ("Plains of", False), ("Panax gin5eng", False),
    ("Pa ginseng", False), ("Panax gi", False), ("Ligularia hookeri subsp. clarkei", True),
])
def test_junk_names(name, ok):
    assert bc.plausible(name) is ok


def test_dedupe_keeps_first_and_prefers_accepted():
    rows = [{"checklist": "a", "name": "X y", "status": "synonym"},
            {"checklist": "a", "name": "X y", "status": "accepted"},
            {"checklist": "a", "name": "X y", "status": "accepted"},
            {"checklist": "b", "name": "X y", "status": "accepted"}]
    assert [(r["checklist"], r["status"]) for r in bc.dedupe(rows)] == [("a", "accepted"), ("b", "accepted")]


def test_block_layout_ocr_family_heads_and_running_distribution():
    lines = [
        ("Asclepiadaceac", True),                        # OCR of a family running head
        ("Barleria prionitis L., Sp. pl. 636. 1753.", True),
        ("var, prionitis,", False),
        ("Throughout trapica) India.", False),           # looks like a name, but is a distribution
        ("var. diacantha Blatt. & Hallb. in J. Bombay Nat. Hist. Soc. 26: 841. 1919.", True),
        ("Rajasthan.", False),
        ("ASCLEPIADACEAE", False),                      # family head right after a distribution
        ("Asclepias curassavica L., Sp. pl. 215. 1753.", True),
        ("Cultivated.", False),
    ]
    rows = bc.parse_entries([(t, p, 1) for t, p in lines], layout="block",
                            families=["Acanthaceae", "Asclepiadaceae"])
    assert [(r["family"], r["name"], r["states"]) for r in rows] == [
        ("Asclepiadaceae", "Barleria prionitis", ""),
        ("Asclepiadaceae", "Barleria prionitis var. prionitis", ""),
        ("Asclepiadaceae", "Barleria prionitis var. diacantha", "Rajasthan"),
        ("Asclepiadaceae", "Asclepias curassavica", ""),
    ]


@pytest.mark.parametrize("text,fam", [
    ("ACANTHACEAE", "Acanthaceae"), ("Acanthaceac", "Acanthaceae"), ("APIACEAE [UMBELLIFERAE]", "Apiaceae"),
    ("Assam.", None), ("Acanthus ilicifolius L.", None), ("PANAX L., Sp. pl. 1058. 1753.", None),
    ("ERIACHNE", None), ("Roscoea ;", None), ("MYRIOSTACHYA (Bin) Hook. f, Fl Brit", None),
    ("ARACEAE (PALMAE)", "Araliaceae"),
])
def test_family_heads(text, fam):
    assert bc.family_of(text, ["Acanthaceae", "Apiaceae", "Araliaceae"]) == fam


def test_ocr_names_corrected_against_reference():
    fix = bc.Corrector(["Hygrophila ringens", "Hygrophila heinei", "Dicliptera nasikensis", "Barleria prionitis",
                        "Barleria prattensis", "Strobilanthes glomerata", "Strobilanthes glomerulata"])
    assert fix("Hygrophila ringens") == ("Hygrophila ringens", "exact")
    assert fix("Hyprophila ringens") == ("Hygrophila ringens", "corrected")
    assert fix("Ticliptora nasikensis var. paniculata") == ("Dicliptera nasikensis var. paniculata", "corrected")
    assert fix("Hygraphila heinei var. heinel") == ("Hygrophila heinei var. heinei", "corrected")
    assert fix("Strobilanthes glomerlata") == ("Strobilanthes glomerlata", "ambiguous")   # two close names
    assert fix("Novogenus mysticus") == ("Novogenus mysticus", "unmatched")
    assert bc.Corrector([])("Hyprophila ringens") == ("Hyprophila ringens", "no reference")


def test_correct_keeps_accepted_and_drops_unreadable_synonyms():
    rows = [{"checklist": "c", "page": 1, "name": "Hyprophila ringens", "status": "accepted"},
            {"checklist": "c", "page": 1, "name": "Crtlthertia muyrigntha", "status": "synonym"},
            {"checklist": "c", "page": 1, "name": "Novogenus mysticus", "status": "accepted"},
            {"checklist": "c", "page": 2, "name": "Hygrophila heinei", "status": "synonym"}]
    kept, qc = bc.correct(rows, bc.Corrector(["Hygrophila ringens", "Hygrophila heinei"]))
    assert [(r["name"], r["status"]) for r in kept] == [
        ("Hygrophila ringens", "accepted"), ("Novogenus mysticus", "accepted"), ("Hygrophila heinei", "synonym")]
    assert [(q["ocr_name"], q["name"], q["match"], q["kept"]) for q in qc] == [
        ("Hyprophila ringens", "Hygrophila ringens", "corrected", True),
        ("Crtlthertia muyrigntha", "Crtlthertia muyrigntha", "unmatched", False),
        ("Novogenus mysticus", "Novogenus mysticus", "unmatched", True)]


def test_one_block_per_taxon_survives_a_misread_distribution():
    lines = [("Acanthus ebracteatus Vahl, Symb. bot 2: 75. 1791; C.B. Clarke in Hook. f., Fl.", True),
             ("Brit. India 4: 421. 1 RRA.", False),          # year misread: citation not seen as closed
             ("Andaman Islancs.", False),
             ("Acanthus ilicifolius L., Sp. pl. 639. 1753.", True),
             ("Dilivaria ilicifolia (L.) Juss., Gen. pl. 103. 1789.", False),
             ("Acanthopsis ilicifolia Nees in DC., Prodr. 11: 274. 1847.", "top"),   # synonym at a page top
             ("Andaman & Nicobar Islands, W Bengal.", False)]
    rows = bc.parse_entries([(t, p, 51) for t, p in lines], "block", one_per_block=True)
    assert [(r["name"], r["status"]) for r in rows] == [
        ("Acanthus ebracteatus", "accepted"), ("Acanthus ilicifolius", "accepted"),
        ("Dilivaria ilicifolia", "synonym"), ("Acanthopsis ilicifolia", "synonym")]
