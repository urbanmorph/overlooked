"""BSI's regional and family books (pipeline/bsi_monographs.py): names from the lines that start a species account,
kept only when GBIF knows them as a species of the book's kingdom."""

from pipeline import bsi_monographs as bm


def test_candidates_from_lines_that_start_a_species_account():
    lines = ["Parmotrema nilgherrense (Nyi.) Hale, Phytologia 28: 338. 1974. -Parmelia",
             "ZONARIA LATISSIMA Kitz.",
             "3. Inonotus rickii (Pat.) Reid",
             "Russula rosea var. minor Pers.",
             "It sparsely grows on boulders in open places.",           # running text
             "Distribution: India (Kerala, Nagaland, Sikkim)",
             "From J. dryophilus which also has a well developed",
             "MACROLICHENS OF SIKKIM"]
    assert bm.candidates(lines) == ["Parmotrema nilgherrense", "Zonaria latissima", "Inonotus rickii",
                                    "Russula rosea var. minor"]


class Http:
    def __init__(self, answers):
        self.answers, self.asked, self.headers = answers, [], {}

    def get(self, url, params=None, **kw):
        self.asked.append(params["name"])
        body = self.answers.get(params["name"], {"matchType": "NONE"})
        return type("R", (), {"json": lambda self: body, "raise_for_status": lambda self: None})()


def test_only_names_gbif_knows_as_a_species_of_the_books_kingdom(tmp_path):
    http = Http({
        "Parmotrema nilgherrense": {"matchType": "EXACT", "rank": "SPECIES", "kingdom": "Fungi", "confidence": 99,
                                    "canonicalName": "Parmotrema nilgherrense"},
        "Parmotrema nilgherense": {"matchType": "FUZZY", "rank": "SPECIES", "kingdom": "Fungi", "confidence": 95,
                                   "canonicalName": "Parmotrema nilgherrense"},           # an OCR misreading
        "Hale Phytologia": {"matchType": "FUZZY", "rank": "GENUS", "kingdom": "Plantae", "confidence": 70},
        "Ulva lactuca": {"matchType": "EXACT", "rank": "SPECIES", "kingdom": "Plantae", "confidence": 99,
                         "canonicalName": "Ulva lactuca"},                                 # a plant in a fungus book
    })
    cache = {}
    got = bm.verify(["Parmotrema nilgherrense", "Parmotrema nilgherense", "Hale Phytologia", "Ulva lactuca"],
                    "lichens", http, cache, pause=0)
    assert [(c, n) for c, n, _ in got] == [("Parmotrema nilgherrense", "Parmotrema nilgherrense"),
                                          ("Parmotrema nilgherense", "Parmotrema nilgherrense"),
                                          ("Hale Phytologia", None), ("Ulva lactuca", None)]
    assert bm.verify(["Ulva lactuca"], "algae", Http({}), cache, pause=0)[0][1] == "Ulva lactuca"   # cached: no request


def test_book_rows_once_each_at_the_first_page():
    spec = {"title": "Macrolichens of Sikkim", "group": "lichens", "states": "Sikkim", "url": "u"}
    pages = {"10": {"lines": [[0, 0, 0, "Parmotrema nilgherense (Nyl.) Hale"]]},
             "9": {"lines": [[0, 0, 0, "Parmotrema nilgherrense (Nyl.) Hale"], [0, 0, 0, "It grows on bark."]]}}
    rows = bm.book_rows(spec, pages, {"Parmotrema nilgherrense": "Parmotrema nilgherrense",
                                      "Parmotrema nilgherense": "Parmotrema nilgherrense"})
    assert [(r["name"], r["page"], r["states"], r["source"]) for r in rows] == [
        ("Parmotrema nilgherrense", 9, "Sikkim", "BSI")]


def test_a_slow_answer_is_asked_again():
    import requests

    class Slow(Http):
        def get(self, url, params=None, **kw):
            if not self.asked:
                self.asked.append("timeout")
                raise requests.exceptions.ReadTimeout("slow")
            return super().get(url, params, **kw)

    http = Slow({"Ulva lactuca": {"matchType": "EXACT", "rank": "SPECIES", "kingdom": "Plantae", "confidence": 99,
                                  "canonicalName": "Ulva lactuca"}})
    assert bm.verify(["Ulva lactuca"], "algae", http, {}, pause=0)[0][1] == "Ulva lactuca"
    assert http.asked == ["timeout", "Ulva lactuca"]
