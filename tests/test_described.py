"""Description years: from Catalogue of Life authorship, Kew WCVP (the basionym's year) and checklist authorities."""

import io
import json
import zipfile

import duckdb

from pipeline import described


def test_year_of_takes_the_first_year_in_the_authorship():
    assert described.year_of("Swinhoe, 1890") == 1890
    assert described.year_of("(Fabricius, 1775)") == 1775          # original description, in a new genus
    assert described.year_of("(Reitter, 1889) Smith, 1950") == 1889
    assert described.year_of("Walker, [1866]") == 1866
    assert described.year_of("L.") is None                          # botanical authorships rarely give a year
    assert described.year_of("Kirby 1700") is None                  # before Linnaeus: not a description year
    assert described.year_of(None) is None
    assert described.year_of("Breme 2099") is None                  # a typo: a year still to come


def coldp(tmp_path):
    rows = ["col:ID\tcol:parentID\tcol:status\tcol:rank\tcol:scientificName\tcol:authorship",
            "A1\tP\taccepted\tspecies\tAus bus\tSwinhoe, 1890",
            "A2\tP\taccepted\tspecies\tCus dus\t(L.) DC.",
            "A3\tP\taccepted\tgenus\tAus\tMoore, 1880",
            "A4\tA1\tsynonym\tspecies\tAus cus\tHampson, 1891",
            "A5\tP\tprovisionally accepted\tspecies\tEus fus\t(Walker, [1866])"]
    z = tmp_path / "coldp.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("NameUsage.tsv", "\n".join(rows) + "\n")
    return z


def test_col_years_keeps_accepted_species_with_their_year_and_authorship(tmp_path):
    out = tmp_path / "col.parquet"
    described.col_years(coldp(tmp_path), out)
    got = duckdb.sql(f"SELECT id, year, authority FROM '{out}' ORDER BY id").fetchall()
    assert got == [("A1", 1890, "Swinhoe, 1890"), ("A2", None, "(L.) DC."), ("A5", 1866, "(Walker, [1866])")]


def wcvp_zip(tmp_path):
    head = ("plant_name_id|taxon_rank|taxon_status|first_published|taxon_name|taxon_authors|accepted_plant_name_id|"
            "basionym_plant_name_id")
    rows = [head,
            "1|Species|Synonym|(1753)|Arundo bambos|L.|2|",
            "2|Species|Accepted|(1895)|Bambusa bambos|(L.) Voss|2|1",       # the basionym's year counts
            "3|Species|Accepted|(1753)|Mangifera indica|L.|3|",
            "4|Species|Synonym|(1830)|Mangifera indica|Wall.|3|",           # a homonym: the accepted name wins
            "5|Variety|Accepted|(1900)|Mangifera indica var. x|Foo|5|",
            "6|Species|Accepted||Ficus nova|Bar|6|"]
    z = tmp_path / "wcvp.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("wcvp_names.csv", "\n".join(rows) + "\n")
    return z


def test_wcvp_years_use_the_basionym_and_prefer_accepted_names(tmp_path):
    out = tmp_path / "wcvp.parquet"
    described.wcvp_years(wcvp_zip(tmp_path), out)
    got = dict((n, (y, a)) for n, y, a in duckdb.sql(f"SELECT name, year, authority FROM '{out}'").fetchall())
    assert got["Bambusa bambos"] == (1753, "(L.) Voss")
    assert got["Mangifera indica"] == (1753, "L.")
    assert got["Arundo bambos"] == (1753, "L.")
    assert got["Ficus nova"] == (None, "Bar")
    assert "Mangifera indica var. x" not in got


class Resp(io.BytesIO):
    def __init__(self, body=b"", headers=None):
        super().__init__(body)
        self.headers, self.status_code = headers or {}, 200

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        while chunk := self.read(n):
            yield chunk

    def json(self):
        return json.loads(self.getvalue())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class Http:
    """Answers the COL dataset, the two version checks and the two downloads; counts the downloads."""

    def __init__(self, col_zip, wcvp_zip, col_key=316441, etag='"e1"'):
        self.col_zip, self.wcvp_zip, self.col_key, self.etag, self.downloads = col_zip, wcvp_zip, col_key, etag, 0

    def get(self, url, **kw):
        if url == described.COL_DATASET:
            return Resp(json.dumps({"key": self.col_key, "alias": "COL26.9 XR"}).encode())
        self.downloads += 1
        return Resp((self.col_zip if url == described.COL_EXPORT else self.wcvp_zip).read_bytes())

    def head(self, url, **kw):
        return Resp(headers={"ETag": self.etag})


def test_sync_downloads_once_and_again_only_for_a_new_release(tmp_path, monkeypatch):
    monkeypatch.setattr(described, "CACHE", tmp_path / "cache")
    http = Http(coldp(tmp_path), wcvp_zip(tmp_path))
    paths = described.sync(http, None)
    assert http.downloads == 2 and paths["col"].exists() and paths["wcvp"].exists()
    assert described.sync(http, None) == paths and http.downloads == 2      # same releases: nothing fetched
    http.col_key = 316999
    described.sync(http, None)
    assert http.downloads == 3                                              # only the new COL release
    meta = json.loads((tmp_path / "cache" / "described.json").read_text())
    assert meta["col"]["key"] == 316999 and meta["wcvp"]["etag"] == '"e1"'
