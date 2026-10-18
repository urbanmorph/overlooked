"""ZSI Animal Discoveries: listing, page parsers for the two layouts, cache and restart, names for the layer.

Fixtures in tests/fixtures/zsi/ are the text layers of real pages (page number -> text):
2009 and 2016 use numbered entries ("1. Genus species Author"); 2019 and 2024 use narrative entries
("The species X was described by ..."). 2016 has a legacy font that turns some words into junk."""

import json
from pathlib import Path

import pymupdf
import pytest

from pipeline import zsi_discoveries as zd

FIX = Path(__file__).parent / "fixtures" / "zsi"


def pages(year):
    return {int(p): t for p, t in json.loads((FIX / f"animal_discoveries_{year}.json").read_text()).items()}


def by_name(entries):
    return {e["name"]: e for e in entries}


def test_numbered_2009_species_records_groups_and_states():
    got = by_name(zd.parse(pages(2009), 2009))
    assert list(got) == ["Batrachostomus moniliger roonwali", "Spinometra dehradunensis", "Filimanus perplexa",
                         "Brachioppiella periculosa", "Scutovertex laminipes", "Peloptulus foveolatus"]
    bird = got["Batrachostomus moniliger roonwali"]
    assert (bird["kind"], bird["rank"], bird["group"], bird["family"], bird["states"]) == \
        ("new_to_science", "infraspecific", "Aves", "Podargidae", "KARNATAKA")
    fluke = got["Spinometra dehradunensis"]
    assert (fluke["kind"], fluke["rank"], fluke["group"], fluke["states"]) == \
        ("new_to_science", "species", "Platyhelminthes", "UTTARAKHAND")
    fish = got["Filimanus perplexa"]           # after the "NEW RECORDS FROM INDIA" divider
    assert (fish["kind"], fish["group"], fish["family"], fish["states"]) == \
        ("new_record", "Pisces", "Polynemidae", "ANDAMAN & NICOBAR")
    mite = got["Brachioppiella periculosa"]    # heading "ACARI : ORIBATEI"
    assert (mite["kind"], mite["group"], mite["states"]) == ("new_record", "Arachnida", "UTTARAKHAND")
    assert all(e["year"] == 2009 for e in got.values())


def test_numbered_2016_skips_junk_lines_and_switches_to_records():
    got = by_name(zd.parse(pages(2016), 2016))
    new = [n for n, e in got.items() if e["kind"] == "new_to_science"]
    assert new == ["Basine cornutodefecta", "Brunia pseudoantica", "Byrsia neoaurantiaca", "Cernyia neocretacea"]
    assert got["Byrsia neoaurantiaca"]["states"] == "JAMMU & KASHMIR"
    rec = {n: e["group"] for n, e in got.items() if e["kind"] == "new_record"}
    # Protozoa "2." is font junk; Cnidaria restarts at 1.
    assert rec == {"Arcella excavata": "Protozoa", "Acropora branchi": "Cnidaria", "Acropora lovelli": "Cnidaria"}


def test_narrative_2019_new_species_and_records():
    got = by_name(zd.parse(pages(2019), 2019))
    assert {n: e["kind"] for n, e in got.items()} == {
        "Monocystis indicus": "new_to_science", "Monocystis satoi": "new_to_science",
        "Ophichthus machidai": "new_record",      # "The species earlier known from ...": name from the heading
        "Cypselurus opisthopus": "new_record"}
    assert got["Monocystis satoi"]["states"] == "WEST BENGAL"
    assert got["Ophichthus machidai"]["group"] == "Pisces"     # "Class ACTINOPTERYGII"
    assert got["Ophichthus machidai"]["family"] == "Ophichthidae"
    assert got["Cypselurus opisthopus"]["states"] == "KERALA"


def test_narrative_2024_two_page_spreads_and_subgenera():
    got = by_name(zd.parse(pages(2024), 2024))
    assert list(got) == ["Mucropetraliella stemmatum", "Otostigmus coorgensis", "Asphondylia mangiferi",
                         "Lasioptera sharma", "Forcipomyia arcuatilis", "Forcipomyia sternaspina"]
    assert all(e["kind"] == "new_to_science" and e["rank"] == "species" for e in got.values())
    assert got["Otostigmus coorgensis"]["group"] == "Chilopoda"
    assert {got[n]["group"] for n in ("Asphondylia mangiferi", "Lasioptera sharma", "Forcipomyia sternaspina")} == {"Diptera"}
    assert [got[n]["states"] for n in ("Asphondylia mangiferi", "Lasioptera sharma", "Forcipomyia arcuatilis")] == \
        ["ANDHRA PRADESH", "GOA", "WEST BENGAL"]
    assert got["Lasioptera sharma"]["family"] == "Cecidomyiidae"


def test_name_from_genus_sentence_and_ligatures():
    text = ("Zootaxa, 5258 (3): 270–284, 2023 The genus Capulopsyche and the species keralensis was described by "
            "A. B. Author based on a Holotype collected from Idukki, Kerala, India.\n"
            "The species Cnemaspis Ѻavigularis was described by C. D. Author based on a Holotype collected "
            "from Karnataka, India.\n"
            "This year 300 new species have been described from all over the country.\n")
    got = by_name(zd.parse({1: text}, 2023))
    assert list(got) == ["Capulopsyche keralensis", "Cnemaspis flavigularis"]
    assert got["Capulopsyche keralensis"]["states"] == "KERALA"


def test_narrative_variants_seen_in_the_books():
    text = "\n".join([
        # 2018: a common name after the binomial is not a subspecies
        "The species Channa royi commonly known as Andaman emerald snakehead was described by A. Author "
        "from South Andaman, India.",
        # 2020: entries with only the paper's citation; the name is in the heading above
        "Aneuroscelio andal Veenakumari &", "Mohanraj. Annales Zoologici, 70 (4): 573-627,", "2020.",
        "Citation: Veenakumari Kamalanathan and Prashanth Mohanraj, Annales Zoologici 70(4), 573-627.",
        # 2019: "speices", subgenus "(s. lat.)", and "The species was described" under a heading
        "The speices Oscheius indicus was described by P. Kumar from Uttarakhand, India.",
        "The species Neoserica (s. lat.) reuteri was described by K. Sreedevi from Kerala, India.",
        "Cnemaspis shevaroyensis Khandekar, Gaitonde and Agarwal. Zootaxa, 4690 (1): 068-100, 2019",
        "The species was described by A. Khandekar from Tamil Nadu, India.",
        # 2023, 2024 typos: "as described", "was described C.K. Mandal"
        "The species Forcipomyia (Lepidohelea) buccina as described by G. S. Pal from West Bengal, India.",
        "The species Haemadipsa gopali was described C.K. Mandal from Odisha, India.",
        # summary sentences are not entries
        "A total of 12 new species of Annelida have been described from the various states of India.",
    ])
    got = by_name(zd.parse({1: text}, 2020))
    assert list(got) == ["Channa royi", "Aneuroscelio andal", "Oscheius indicus", "Neoserica reuteri",
                         "Cnemaspis shevaroyensis", "Forcipomyia buccina", "Haemadipsa gopali"]
    assert got["Channa royi"]["rank"] == "species"
    assert got["Cnemaspis shevaroyensis"]["states"] == "TAMIL NADU"


def test_every_zsi_group_maps_to_a_site_group():
    from pipeline.groups import GROUPS
    assert set(zd.ZSI_GROUP.values()) <= set(GROUPS)
    assert set(zd.GROUP_TERMS.values()) <= set(zd.ZSI_GROUP)
    assert zd.ZSI_GROUP["Coleoptera"] == "Insects: beetles" and zd.ZSI_GROUP["Pisces"] == "Fish"
    assert zd.ZSI_GROUP["Arachnida"] == "Spiders & other arachnids"


LISTING_HTML = """
<a href="https://zsi.gov.in/public/uploads/documents/importantLinks/english/Animal_Discoveries_2024_1.pdf">x</a>
<a href="https://zsi.gov.in/public/uploads/documents/importantLinks/english/Animal_Discoveries_2023_(2)_compressed2.pdf">x</a>
<a href="https://zsi.gov.in/public/uploads/documents/importantLinks/english/ZSI_ENews_June_2026.pdf">x</a>
<a class="page-link" href="https://zsi.gov.in/impo-link/7?page=2" rel="next">Next</a>
"""
LISTING_HTML_2 = """
<a href="https://zsi.gov.in/public/uploads/documents/importantLinks/english/Animal_Discover_2009.pdf">x</a>
<a href="https://zsi.gov.in/public/uploads/documents/importantLinks/english/Animal_Discoveries-2011.pdf">x</a>
"""


class Resp:
    def __init__(self, text="", ctype="text/html; charset=utf-8", body=b""):
        self.text, self.headers, self.body, self.status_code = text, {"Content-Type": ctype}, body, 200

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        yield self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeHttp:
    """ZSI's site: a language form on every page, two listing pages, and PDFs."""

    def __init__(self, pdf_bytes=b""):
        self.calls, self.pdf_bytes = [], pdf_bytes

    def get(self, url, **kw):
        self.calls.append(url)
        if url.endswith(".pdf"):
            return Resp(ctype="application/pdf", body=self.pdf_bytes)
        if url.endswith("?page=2"):
            return Resp(LISTING_HTML_2)
        if "impo-link/7" in url:
            return Resp(LISTING_HTML)
        return Resp('<input type="hidden" name="_token" value="tok123">')

    def post(self, url, data=None, **kw):
        self.calls.append(("POST", url, data))
        return Resp()


def test_listing_switches_to_english_and_follows_pages(monkeypatch):
    monkeypatch.setattr(zd.time, "sleep", lambda s: None)
    http = FakeHttp()
    links = zd.listing(http)
    assert links == {
        2024: "https://zsi.gov.in/public/uploads/documents/importantLinks/english/Animal_Discoveries_2024_1.pdf",
        2023: "https://zsi.gov.in/public/uploads/documents/importantLinks/english/Animal_Discoveries_2023_(2)_compressed2.pdf",
        2009: "https://zsi.gov.in/public/uploads/documents/importantLinks/english/Animal_Discover_2009.pdf",
        2011: "https://zsi.gov.in/public/uploads/documents/importantLinks/english/Animal_Discoveries-2011.pdf"}
    assert ("POST", zd.LANGUAGE, {"_token": "tok123", "language": "en"}) in http.calls


def tiny_pdf(text):
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 72), text, fontsize=9)
    return doc.tobytes()


def test_sync_parses_once_and_second_run_does_no_work(tmp_path, monkeypatch):
    monkeypatch.setattr(zd, "SRC", tmp_path)
    monkeypatch.setattr(zd.time, "sleep", lambda s: None)
    monkeypatch.setattr(zd, "listing", lambda http: {2024: "https://zsi.gov.in/x/Animal_Discoveries_2024_1.pdf"})
    http = FakeHttp(tiny_pdf("The species Lasioptera sharma was described by D. Vasanthakumar from Goa, India."))
    out = zd.sync(http)
    assert [e["name"] for e in out[2024]] == ["Lasioptera sharma"]
    assert out[2024][0]["link"] == "https://zsi.gov.in/x/Animal_Discoveries_2024_1.pdf"
    assert sum(1 for c in http.calls if str(c).endswith(".pdf")) == 1
    http.calls.clear()
    assert zd.sync(http) == out
    assert not [c for c in http.calls if str(c).endswith(".pdf")]      # cached: no download, no parse


def test_sync_time_limit_starts_no_new_edition(tmp_path, monkeypatch):
    monkeypatch.setattr(zd, "SRC", tmp_path)
    monkeypatch.setattr(zd.time, "sleep", lambda s: None)
    monkeypatch.setattr(zd, "listing", lambda http: {2024: "https://zsi.gov.in/x/a.pdf"})
    http = FakeHttp(tiny_pdf("The species Lasioptera sharma was described by D. Vasanthakumar from Goa, India."))
    assert zd.sync(http, minutes=-1) == {}
    assert not [c for c in http.calls if str(c).endswith(".pdf")]
    assert list(zd.sync(http)) == [2024]                  # the next run does it


def test_sync_keeps_a_year_for_the_next_run_when_zsi_sends_html(tmp_path, monkeypatch):
    monkeypatch.setattr(zd, "SRC", tmp_path)
    monkeypatch.setattr(zd.time, "sleep", lambda s: None)
    monkeypatch.setattr(zd, "listing", lambda http: {2024: "https://zsi.gov.in/x/a.pdf"})

    class Soft404(FakeHttp):
        def get(self, url, **kw):
            return Resp("<html>home</html>")

    assert zd.sync(Soft404()) == {}
    assert not list(tmp_path.glob("*.json")) and not list(tmp_path.glob("*.pdf"))


def test_ocr_pages_are_cached_and_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(zd, "SRC", tmp_path)
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 72), "text layer", fontsize=9)
    doc.new_page()                                   # scanned page: no text layer
    pdf = tmp_path / "animal_discoveries_2030.pdf"
    doc.save(pdf)
    seen = []

    def fake_ocr(page):
        seen.append(page.number)
        return "ocr text"

    monkeypatch.setattr(zd, "ocr_page", fake_ocr)
    assert zd.page_texts(pdf, 2030) == {1: "text layer\n", 2: "ocr text"}
    assert zd.page_texts(pdf, 2030)[2] == "ocr text" and seen == [1]       # second read: from the cache


def test_ocr_progress_is_kept_when_a_run_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(zd, "SRC", tmp_path)
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    pdf = tmp_path / "animal_discoveries_2030.pdf"
    doc.save(pdf)

    def dies_on_third(page):
        if page.number == 2:
            raise TimeoutError("killed")
        return f"p{page.number + 1}"

    monkeypatch.setattr(zd, "ocr_page", dies_on_third)
    with pytest.raises(TimeoutError):
        zd.page_texts(pdf, 2030)
    assert json.loads(zd.ocr_file(2030).read_text()) == {"1": "p1", "2": "p2"}


def test_names_rows_for_the_new_species_layer(monkeypatch):
    link = "https://zsi.gov.in/x/2024.pdf"
    entry = dict(year=2024, kind="new_to_science", rank="species", name_check="ok", group="Diptera", family="",
                 states="GOA", link=link)
    monkeypatch.setattr(zd, "sync", lambda http, s3=None: {2023: [dict(entry, name="Old one", year=2023)], 2024: [
        dict(entry, name="Lasioptera sharma"),
        dict(entry, name="Acropora branchi", kind="new_record"),
        dict(entry, name="Batrachostomus moniliger roonwali", rank="infraspecific"),
        dict(entry, name="Tarsal spurs", name_check="needs_review"),
    ]})
    assert zd.names(None, None, 2024) == [{"name": "Lasioptera sharma", "year": 2024, "source": "ZSI Animal Discoveries",
                                           "journal": "", "state": "", "zsi_group": "Diptera", "link": link}]
