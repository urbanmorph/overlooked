"""BSI Plant Discoveries: listing, OCR restart, and the 2007-2014 layouts (fixtures copied from the reports)."""

import json

import pymupdf
import pytest

from pipeline import bsi, r2


def text_pdf(path, pages):
    """A PDF with a text layer: one list of lines per page (an empty list makes a page with no text)."""
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page(width=1000, height=60 + 14 * len(lines))
        for i, line in enumerate(lines):
            page.insert_text((20, 30 + 14 * i), line, fontsize=9)
    doc.save(path)
    return path


# ---------- listing ----------

class FakeResponse:
    def __init__(self, text, ctype="text/html; charset=UTF-8"):
        self.text, self.headers = text, {"Content-Type": ctype}

    def raise_for_status(self):
        pass


class FakeHttp:
    def __init__(self, text):
        self.text = text

    def get(self, url, **kw):
        return FakeResponse(self.text)


def test_listing_finds_every_file_name_style():
    page = "".join(f'<a href="../../../../uploads/documents/Plant Discoveries/{n}.pdf">x</a>' for n in [
        "Plant Discovered_2007", "Plant Discoveries_2010", "Discovery - 2013", "Discovery-2014",
        "Plant Discoveries 2022 for upload final"])
    got = bsi.listing(FakeHttp(page))
    assert sorted(got) == [2007, 2010, 2013, 2014, 2022]
    assert got[2013] == ["https://bsi.gov.in/uploads/documents/Plant%20Discoveries/Discovery%20-%202013.pdf"]


# ---------- OCR: cached per page, saved to R2 at intervals and on exit, resumable ----------

@pytest.fixture
def fake_r2(monkeypatch):
    store = {}

    def sync_file(s3, path, key, immutable=True):
        new = path.read_text()
        changed = store.get(key) != new
        store[key] = new
        return changed

    monkeypatch.setattr(r2, "sync_file", sync_file)
    monkeypatch.setattr(r2, "get_json", lambda s3, key: json.loads(store[key]) if key in store else None)
    return store


def test_ocr_resumes_and_saves_progress_on_failure(tmp_path, monkeypatch, fake_r2):
    monkeypatch.setattr(bsi, "SRC", tmp_path)
    pdf = text_pdf(tmp_path / "Plant Discoveries 2014 best.pdf", [[], ["has text"], [], []])
    seen = []

    def fake(page):
        seen.append(page.number)
        if page.number == 3:
            raise TimeoutError("killed")
        return f"page {page.number + 1}"

    with pytest.raises(TimeoutError):
        bsi.ocr(pdf, s3="s3", ocr_page=fake)
    assert seen == [0, 2, 3]                      # the page with a text layer is not OCRed
    saved = json.loads(fake_r2["cache/bsi/ocr/Plant Discoveries 2014 best.json"])
    assert saved == {"p0001.txt": "page 1", "p0003.txt": "page 3"}   # kept in R2 although the run failed

    # A new machine (no local cache) continues from R2 and OCRs only the last page.
    monkeypatch.setattr(bsi, "SRC", tmp_path / "fresh")
    seen.clear()
    assert bsi.ocr(pdf, s3="s3", ocr_page=lambda p: seen.append(p.number) or "last") is True
    assert seen == [3]
    assert (tmp_path / "fresh" / "ocr" / "Plant Discoveries 2014 best" / "p0001.txt").read_text() == "page 1"
    seen.clear()
    assert bsi.ocr(pdf, s3="s3", ocr_page=lambda p: seen.append(p.number)) is True
    assert seen == []                             # second run: no new work


def test_ocr_stops_at_time_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(bsi, "SRC", tmp_path)
    pdf = text_pdf(tmp_path / "x.pdf", [[], []])
    assert bsi.ocr(pdf, minutes=0, ocr_page=lambda p: "never") is False
    assert not (tmp_path / "ocr" / "x").exists() or not list((tmp_path / "ocr" / "x").iterdir())


# ---------- 2007-2012: lists of names and citations, no descriptions ----------

# 2007, page 1: totals, then "New Species and Varieties" / "New Records for India", each split by group.
LIST_2007 = """DURING 2007 THE SCIENTISTS OF BSI DISCOVERED
23 species,
6 varieties as new to science,
New Species and Varieties
Flowering Plants
Agapetes arunachalensis Banik & Sanjappa (ERICACEAE). Published in Edinburgh Journal of
Botany 64: 335. 2007.
Agapetes acuminata D. Don ex G. Don var. tipiensis Banik & Sanjappa (ERICACEAE). Published
in Journal of Botanical Research Institute of Texas 1: 903. 2007.
Juncus benghalensis Kunth var. kyangnoslae G. Chhettri, Hynniewta & A.A. Ansari
(]UNCACEAE). Published in Indian Journal of Forestry 30: 539. 2007.
Psychotria henryana Murugan & Gopalan (RUBIACEAE). Published in Nordic Journal of Botany
24: 415. 2007
Bryophytes
Cephalozia schusteri Sushil K. Singh & D.K. Singh (CEPHALOZIACEAE). Published in Lindbergia
32: 1. 2007.
New Records for India
Flowering Plants
Coluria longifolia Maxim. (ROSACEAE). Published in Indian Journal of Forestry 30: 121. 2007.
Lichens
Graphis bulacana Vain. (GRAPHIDACEAE). Published in Indian Journal of Forestry 30: 535.
2007.
Fungi
Bovista cunninghamii Kreisel (GASTEROMYCETES). Published in Bulletin of the Botanical Survey
of India 49: 227. 2007.""".splitlines()


def by_name(entries):
    return {e["name"]: e for e in entries}


def test_list_layout_2007_sections_groups_and_varieties():
    got = by_name(bsi.list_entries(LIST_2007, 2007))
    assert list(got) == ["Agapetes arunachalensis", "Agapetes acuminata var. tipiensis",
                         "Juncus benghalensis var. kyangnoslae", "Psychotria henryana", "Cephalozia schusteri",
                         "Coluria longifolia", "Graphis bulacana", "Bovista cunninghamii"]
    a = got["Agapetes arunachalensis"]
    assert (a["kind"], a["rank"], a["group"], a["family"], a["name_check"]) == (
        "new_to_science", "species", "SEED PLANTS", "Ericaceae", "ok")
    assert a["heading"].endswith("Published in Edinburgh Journal of Botany 64: 335. 2007.")
    assert a["source"] == "Botanical Survey of India, Plant Discoveries 2007"
    assert got["Agapetes acuminata var. tipiensis"]["rank"] == "infraspecific"
    assert got["Cephalozia schusteri"]["group"] == "BRYOPHYTES"
    assert [(got[n]["kind"], got[n]["group"]) for n in ["Coluria longifolia", "Graphis bulacana", "Bovista cunninghamii"]] == [
        ("new_record", "SEED PLANTS"), ("new_record", "LICHENS"), ("new_record", "FUNGI")]


# 2008: section headings carry the group ("Forma" has no "New"); the family follows the citation,
# often on its own line; hybrids are written with a plain "x".
LIST_2008 = """New Genus (Seed Plant)
MUNROCHLOA M. Kumar & M. Ramesh, J. Bot. Res. Inst. Texas 2(1): 373. fig. I. 2008.
(POACEAE).
New Species (Seed Plant)
Actinodaphne andamanica M.Gangop., Bangladesh J. Plant Taxon. 15(2): 89. t. 1. 2008.
(LAURACEAE).
Cinnamomum champokianum Baruah & S.C.Nath, Nordic J. Bot. 25(5-6): 281. figs. 1-2. 2007
[publ. 2008]. (LAURACEAE).
Forma (Seed Plant)
Vanda coerulea Griff. ex Lindl. forma luwangalba Kishor. Orchid Rev. 116(1282): 224. 2008.
(ORCHIDACEAE).
New Genus (Ferns)
PICHISERMOLLIA Fraser-Jenk.,Taxonomic Revision Indian Subcontinental Pteridophytes, 48. 2008.
(POLYPODIACEAE)
New Species and Nothospecies
Aleuritopteris wollenweberi Fraser-Jenk.,Taxonomic Revision Indian Subcontinental Pteridophytes
127. 2008. (PTERIDACEAE)
Aleuritopteris x pangteyi Fraser-Jenk & E. Wollenw. (A. bicolor x A. formosana), Taxonomic
Revision Indian Subcontinental Pteridophytes 130. 2008. (PTERIDACEAE)
New Species (Lichens)
Brigantiaea patwardhanii Chitale & Makhija, Mycotaxon 104: 410. 2008. (BRIGANTIACEAE)
New Records (Flowering Plants)
Aconitum bhutanicum Y. Kadota (RANUNCULACEAE) published by K. Chandra Sekar and S.K.
Srivastava in Indian J. Forest. 31(2): 292. 2008.""".splitlines()


def test_list_layout_2008_citations_new_genus_and_group_in_heading():
    got = bsi.list_entries(LIST_2008, 2008)
    assert [(e["name"], e["kind"], e["rank"], e["group"], e["family"]) for e in got] == [
        ("Munrochloa", "new_to_science", "genus", "SEED PLANTS", "Poaceae"),
        ("Actinodaphne andamanica", "new_to_science", "species", "SEED PLANTS", "Lauraceae"),
        ("Cinnamomum champokianum", "new_to_science", "species", "SEED PLANTS", "Lauraceae"),
        ("Vanda coerulea f. luwangalba", "new_to_science", "infraspecific", "SEED PLANTS", "Orchidaceae"),
        ("Pichisermollia", "new_to_science", "genus", "PTERIDOPHYTES", "Polypodiaceae"),
        ("Aleuritopteris wollenweberi", "new_to_science", "species", "PTERIDOPHYTES", "Pteridaceae"),
        ("Aleuritopteris × pangteyi", "new_to_science", "species", "PTERIDOPHYTES", "Pteridaceae"),
        ("Brigantiaea patwardhanii", "new_to_science", "species", "LICHENS", "Brigantiaceae"),
        ("Aconitum bhutanicum", "new_record", "species", "SEED PLANTS", "Ranunculaceae"),
    ]


# 2010: group banner, an introduction paragraph, then sections; under records, "GENUS" and "SPECIES".
LIST_2010 = """BRYOPHYTES
Bryophytes, the amphibians of the 'Plant Kingdom', and the second largest group of green plants
next only to the angiosperms constitute a fascinating component of biodiversity and are widely
NEW VARIETY
Notoscyphus darjeelingensis Udar & A. Kumar var. sikkimensis D. Singh, D.K. Singh & A.
Kumar, Indian. J. Forest. 33(1): 93. 2010. (JUNGERMANNIACEAE)
NEW DISTRIBUTIONAL RECORDS
GENUS
Tuyamaella S. Hatt. (LEJEUNEACEAE) published by D.K. Singh and Monalisa Dey in Nelumbo 52:
135. 2010.
SPECIES
Cololejeunea macounii (Spruce ex Underw.) A. Evans (LEJEUNEACEAE) published by Monalisa
Dey, Devendra Singh and D.K Singh in Indian J. Forest. 33(3): 615. 2010.
LICHENS
Lichens are symbiotic association of a fungus with a photosynthetic partner usually a green alga
or cyanobacterium. Lichens are widespread, however many species are sensitive to environmental
10
NEW SPECIES
Anomomorpha elegans B.O. Sharma, Makhija & Khadilkar, Lichenologist 42(3): 281. 2010.
(GRAPHIDACEAE)
NEW DISTRIBUTIONAL RECORDS
Chapsa pseudophlyctis (Nyl.) A. Frisch (THELOTREMATACEAE) published by T.A.M. Jagadeesh
Ram and G.P. Sinha in Indian J. Forest. 32(4): 635. 2009.
FUNGI
Fungi distributed worldwide, perform an essential role in nature by decomposing organic matter""".splitlines()


def test_list_layout_2010_paragraphs_skipped_and_records_by_rank():
    got = bsi.list_entries(LIST_2010, 2010)
    assert [(e["name"], e["kind"], e["rank"], e["group"]) for e in got] == [
        ("Notoscyphus darjeelingensis var. sikkimensis", "new_to_science", "infraspecific", "BRYOPHYTES"),
        ("Tuyamaella", "new_record", "genus", "BRYOPHYTES"),
        ("Cololejeunea macounii", "new_record", "species", "BRYOPHYTES"),
        ("Anomomorpha elegans", "new_to_science", "species", "LICHENS"),
        ("Chapsa pseudophlyctis", "new_record", "species", "LICHENS"),
    ]


# 2012 prints headings and names in fake bold: the same text drawn several times, slightly offset.
def test_fake_bold_text_is_read_once(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=200)
    for dx in (0, 0.3, 0.6, 0.9):
        page.insert_text((20 + dx, 40), "NEW SPECIES", fontsize=10)
        page.insert_text((20 + dx, 60), "Alysicarpus sanjappae", fontsize=10)
    page.insert_text((132, 60), "S. Chavan, Sardesai & Pokle, Kew Bulletin 68(1): 183.", fontsize=10)
    page.insert_text((20, 74), "2012. (LEGUMINOSAE: PAPILIONOIDEAE)", fontsize=10)
    doc.save(tmp_path / "b.pdf")
    lines = bsi.page_lines(pymupdf.open(tmp_path / "b.pdf")[0])
    assert lines == ["NEW SPECIES", "Alysicarpus sanjappae S. Chavan, Sardesai & Pokle, Kew Bulletin 68(1): 183.",
                     "2012. (LEGUMINOSAE: PAPILIONOIDEAE)"]
    (e,) = bsi.list_entries(lines, 2012)
    assert (e["name"], e["family"], e["kind"]) == ("Alysicarpus sanjappae", "Leguminosae", "new_to_science")


# 2009: some group banners are images, so a group starts with its introduction ("Ferns (Pteridophytes)
# live ..."); one name is printed twice; families like "(HEPATICAE: GEOCALYCACEAE)".
LIST_2009 = """Zingiber parishii Hook.f. (ZINGIBERACEAE) published by M. Sabu, V.P. Thomas and M.C.
Shameer in Acta Botanica Hungarica 51(3-4): 363-366. 2009.
Ferns (Pteridophytes) live in a wide variety of habitats and often succeed in places where
environmental factors discourage growth of flowering plants.
In the present state of our knowledge India has about 1,200 species of ferns. Many more are
yet to be identified and described.
Thelypteris ratnapurae Fraser Jenk. (THELYPTERIDACEAE) published by Anjali Biswas in Bull.
Bot. Surv. India 50: 207 - 208. 2009.
Bryophytes have long been considered the simplest group of land plants.
New Distribution Records
GENUS RECORDS
SACCOGYNIDIUM Grolle (HEPATICAE: GEOCALYCACEAE) published by D.K. Singh & D.
Singh in Journal of Bryology 31: 50-54. 2009.
STENOLEJUNEA R.M. Schust (HEPATICAE: LEJEUNEACEAE) published by Monolisa Dey,
Devendera Singh and D.K. Singh in Indian Journal of Forestry 32(4): 669-684. 2009.
SPECIES RECORDS
Herbartus armitanus (Steph.) H.A. Mill (HERBERTACEAE) published by Monolisa Dey,
Devendera Singh and D.K. Singh in Indian Journal of Forestry 32(4) : 669-604. 2009.
Sesbania sericea (Willd.) Link (LEGUMINOSAE-PAPILIONOIDEAE) published by M. Mohanan
&. J.V. Sudhakar in Bull. Bot. Surv. India 50:171-172. 2009.
The Fungi - a large group of eukaryotic organisms that includes microorganisms such as
NEW SPECIES
Ephedra sumlingensis P. Sharma & P.L. Uniyal, Bull. Bot. Surv. India 50: 179. 2009.
Ephedra sumlingensis P. Sharma & P.L. Uniyal, Bull. Bot. Surv. India 50: 179. 2009.
(EPHEDRACEAE)""".splitlines()


def test_list_layout_2009_group_introductions_author_lines_and_repeats():
    got = bsi.list_entries(LIST_2009, 2009)
    assert [(e["name"], e["kind"], e["rank"], e["group"], e["family"]) for e in got] == [
        ("Zingiber parishii", "new_to_science", "species", None, "Zingiberaceae"),
        ("Thelypteris ratnapurae", "new_to_science", "species", "PTERIDOPHYTES", "Thelypteridaceae"),
        ("Saccogynidium", "new_record", "genus", "BRYOPHYTES", "Geocalycaceae"),
        ("Stenolejunea", "new_record", "genus", "BRYOPHYTES", "Lejeuneaceae"),
        ("Herbartus armitanus", "new_record", "species", "BRYOPHYTES", "Herbertaceae"),
        ("Sesbania sericea", "new_record", "species", "BRYOPHYTES", "Leguminosae"),
        ("Ephedra sumlingensis", "new_to_science", "species", "FUNGI", "Ephedraceae"),
    ]
    assert got[0]["heading"].endswith("363-366. 2009.")      # the introduction is not part of the entry


# 2011: an entry without its family, a family in title case, and one with stray gaps.
LIST_2011 = """SUBSPECIES
Carex rara Boott subsp. potanicola T. Koyama (Cyperaceae) published by D. Veeranjaneyula,
M.V. Suresh Babu, M Bheemalingppa & B.Ravi Prasad Rao in J. Econ.Taxon. Bot. 35(4): 652.
2011.
Phyllopsora subcrustacea (Malme) Brako, (RAM ALIN ACEAE) published by Gaurav K. Mishra,
Dalip K. Upreti, Sanjeeva Nayaka & Biju Haridas, Mycotaxon 115: 42. 2011
Biospora aeglei Dubey & Pandey, J. Mycopathol. Res. 49(2): 357. 2011.
Cercosporidium ziziphus Dubey & Pandey, J. Mycol. Plant Pathol. 41(2): 337. 2011
(MYCOSPHAERELLACEAE)""".splitlines()


def test_list_layout_2011_family_variants_and_entry_without_family():
    got = bsi.list_entries(LIST_2011, 2011)
    assert [(e["name"], e["rank"], e["family"]) for e in got] == [
        ("Carex rara subsp. potanicola", "infraspecific", "Cyperaceae"),
        ("Phyllopsora subcrustacea", "species", "Ramalinaceae"),
        ("Biospora aeglei", "species", ""),
        ("Cercosporidium ziziphus", "species", "Mycosphaerellaceae"),
    ]


# ---------- 2013-2014: descriptions as from 2015, but mostly scanned and bilingual ----------

# 2013 p.20 and p.22 (OCR): Hindi turned into Latin junk before the heading; a heading wraps after "Nordic J.".
PAGES_2013 = [[
    "ot. ar ea @ wa",
    "4 fear war 3 |",
    "Nanooravia Kiran Raj & Sivad., Nordic J.",
    "Bot.31: 162. 2013. (POACEAE)",
    "This new genus has been described on the basis of Dimeria santapaui M. R. Almeida, which was described previously based",
    "on specimens collected by L. J. Sedgwick and T. R. D. Bell in 1919 from 'North Kanara' (Uttar Kannada Dist.) of Karnataka.",
    "Cara Wr ot sea ofa & veeyfacr dee, BB",
    "uN sreniReFI",
    "Aprosa indo-acuminata Chakrab. & N.P. Balakr., Fl. India 23: 369. 2012. (EUPHORBIACEAE)",
    "This new species has been discovered and described based on collections made from Poongavanam-Sabrimala in Idukki",
    "district of Kerala. The holotype is deposited in the Central National Herbarium, Botanical Survey of India, Howrah (CAL)",
], [
    # 2013 p.134: microbes; the description starts "A marine, Gram-stain-negative ...".
    "Mariniradius V. Bhumika, T. N. R. Srinivas, K. Ravinder & P. Anil Kumar. Int. J. Syst. Evol. Microbiol. 63: 2089. 2013",
    "(CYCLOBACTERIACEAE)",
    "A marine, Gram-stain-negative, oxidase- and catalase- positive, rod shaped  bacterium, designated strain AK6 , was isolated",
    "from marine aquaculture pond water in Andhra Pradesh, India. Phylogenetic analysis showed that strain AK6 form a distinct",
    "new genus for which the name proposed as Mariniradius with type strain  AK6 (= MTCC 11279 = JCM 17389).",
]]

# 2014 (OCR): "first time reported from India"; a variety with the species author before "var.".
PAGES_2014 = [[
    "nt >",
    "Hyphodontia barbajovis (Bull.) J. Erikss (FOMITOPSIDACEAE)",
    "This species has been first time reported from India based on from the collection made from angiospermic log,",
    "near Renuka Lake, Sirmaur district, Himachal Pradesh.",
    "Amaranthus tricolor L. var. acutus S. Das, Phytotaxa 88 (2):27.2013. (AMARANTHACEAE)",
    "This new variety has been discovered and described based on collections made from Salt Lake on EM Bypass, 24-Parganas",
    "(North) district of West Bengal, India. The holotype is deposited in the Central National Herbarium Botanical Survey of",
    "India, Howrah (CAL).The varietal epithet is refers to the acute apex of the bracts, bracteoles and tepals.",
]]


def test_2013_headings_after_ocr_junk_and_microbe_descriptions(tmp_path, monkeypatch):
    monkeypatch.setattr(bsi, "SRC", tmp_path)
    got = bsi.parse(text_pdf(tmp_path / "2013.pdf", PAGES_2013), 2013)
    assert [(e["name"], e["kind"], e["rank"], e["family"]) for e in got] == [
        ("Nanooravia", "new_to_science", "genus", "Poaceae"),
        ("Aprosa indo-acuminata", "new_to_science", "species", "Euphorbiaceae"),
        ("Mariniradius", "new_to_science", "genus", "Cyclobacteriaceae"),
    ]
    assert got[1]["states"] == "KERALA"


def test_2014_first_time_reported_and_variety_after_author(tmp_path, monkeypatch):
    monkeypatch.setattr(bsi, "SRC", tmp_path)
    got = bsi.parse(text_pdf(tmp_path / "2014.pdf", PAGES_2014), 2014)
    assert [(e["name"], e["kind"], e["rank"]) for e in got] == [
        ("Hyphodontia barbajovis", "new_record", "species"),
        ("Amaranthus tricolor var. acutus", "new_to_science", "infraspecific"),
    ]


# ---------- 2015+: description text and place names are not headings ----------

def test_description_tail_is_not_a_heading():
    # 2015: "The species has been published by ..." follows a description that ends "(CAL)."; it is no entry.
    tail = ("India based on the collection made from Dombang and Samthang, North district of Sikkim, India at 2890m. "
            "The specimens are deposited in Central National Herbarium, Botanical Survey of India, Howrah (CAL).")
    assert bsi.find_heading(tail) is None
    assert bsi.find_heading("Holotype is deposited in Madras Herbarium, Botanical Survey of India, Southern "
                            "Regional Centre, Coimbatore, Tamil Nadu (MH), Isotypes are in CAL, BSID.") is None


def test_place_name_is_not_a_genus():
    # 2022: a section intro ends just before a new genus.
    text = "India during the year 2022. Johanseniella Pal & Singh, F.E.M.S. Microbiol. Lett. 369:5.2022"
    assert bsi.find_heading(text)[1] == "Johanseniella"
    assert bsi.entry(2015, "India based", None, "new_to_science", "", "")["name_check"] == "needs_review"


def test_heading_followed_by_description_is_kept():
    # 2025: the heading is cited first; a description sentence after it does not reject it.
    text = ("Graphis moriensis R.Adhikari & Nayaka, The Bryologist 128(3): 554. 2025 (Graphidaceae) Nadia District, "
            "West Bengal. Holotype is deposited in CSIR-National Botanical Research Institute, Lucknow (LWG).")
    assert bsi.find_heading(text)[1] == "Graphis moriensis"


# ---------- the PDF each year links to ----------

class HeadHttp:
    """Answers HEAD with a content type and size per URL; counts the requests."""
    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def head(self, url, **kw):
        self.asked.append(url)
        ctype, size = self.answers[url]
        r = FakeResponse("", ctype)
        r.headers["Content-Length"] = str(size)
        r.status_code = 200
        return r


def test_pdf_links_keep_the_larger_pdf_and_skip_pages_and_known_years(tmp_path, monkeypatch):
    monkeypatch.setattr(bsi, "SRC", tmp_path)
    monkeypatch.setattr(bsi.time, "sleep", lambda s: None)
    http = HeadHttp({"a": ("application/pdf", 10), "b": ("application/pdf", 99), "c": ("text/html", 5)})
    assert bsi.pdf_links(http, {2024: ["a", "b"], 2025: ["c"]}) == {2024: "b"}   # 2025: BSI's home page, no link
    assert bsi.pdf_links(http, {2024: ["a", "b"]}) == {2024: "b"} and len(http.asked) == 3  # known: no new request
    assert bsi.pdf_links(http, {2024: ["a"]}) == {2024: "a"}                       # file gone from the listing: check again


def test_sync_links_each_entry_to_its_editions_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(bsi, "SRC", tmp_path)
    monkeypatch.setattr(bsi.time, "sleep", lambda s: None)
    monkeypatch.setattr(bsi, "listing", lambda http: {2023: ["p23"], 2024: ["p24"]})
    for y in (2023, 2024):
        bsi.cache_file(y).write_text(json.dumps([{"name": "Aa bb", "year": y}]))
    got = bsi.sync(HeadHttp({"p23": ("application/pdf", 1), "p24": ("text/html", 1)}))
    assert got[2023][0]["link"] == "p23"
    assert got[2024][0]["link"] == bsi.LISTING                       # no PDF: BSI's listing page
    assert "link" not in json.loads(bsi.cache_file(2023).read_text())[0]   # the parsed cache stays as it was
