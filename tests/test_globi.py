"""GloBI (Global Biotic Interactions): the snapshot download (resumable, skipped when unchanged) and the species
table for the Eltonian gap. Small fixtures stand in for the 2.66 GB snapshot and the LGD districts."""

import gzip
import json

import duckdb
import pytest

from pipeline import globi

HEADER = ["sourceTaxonSpeciesName", "interactionTypeName", "targetTaxonSpeciesName", "decimalLatitude",
          "decimalLongitude", "localityName", "sourceNamespace", "otherColumn", "sourceTaxonKingdomName",
          "sourceTaxonClassName", "targetTaxonKingdomName", "targetTaxonClassName"]


def snapshot(path, rows):
    with gzip.open(path, "wt") as f:
        f.write("\t".join(HEADER) + "\n")
        for r in rows:
            f.write("\t".join(r + [""] * (len(HEADER) - len(r)) if len(r) > 1 else r) + "\n")
    return path


@pytest.fixture
def districts(tmp_path):
    """Two square districts in one state, around (lat 10..11, lon 76..77) and (lat 20..21, lon 80..81)."""
    con = duckdb.connect()
    con.sql("INSTALL spatial; LOAD spatial")
    path = tmp_path / "districts.parquet"
    con.sql(f"""COPY (SELECT * FROM (VALUES
        (101, 32, 'A', 'S', ST_GeomFromText('POLYGON((76 10, 77 10, 77 11, 76 11, 76 10))')),
        (102, 32, 'B', 'S', ST_GeomFromText('POLYGON((80 20, 81 20, 81 21, 80 21, 80 20))')))
        t(dist_lgd, state_lgd, dtname, stname, geometry)) TO '{path}' (FORMAT parquet)""")
    return path


def test_one_row_per_species_from_both_sides_of_each_interaction(tmp_path, districts):
    tsv = snapshot(tmp_path / "i.tsv.gz", [
        ["Aus bus", "eats", "Cus dus", "10.5", "76.5", "", "ds/one", "x"],          # in India (district 101)
        ["Aus bus", "pollinates", "Eus fus", "", "", "Kerala, India", "ds/two", "x"],   # no point: the locality says India
        ["Aus bus", "eats", "Cus dus", "40.0", "-3.0", "Spain", "ds/one", "x"],          # abroad
        ["Gus hus", "parasiteOf", "", "20.5", "80.5", "", "ds/one", "x"],               # partner not named to species
        ["Hus ius", "eats", "Ius jus", "", "", "USA: Indiana", "ds/one", "x"],           # not India: a whole word only
        ["Hus ius", "eats", "Ius jus", "", "", "Indian subregion", "ds/one", "x"],
        ["broken row with no tabs"],
    ])
    out = tmp_path / "species.parquet"
    globi.species_table(duckdb.connect(), tsv, districts, out, tmp_path / "edges.parquet")
    rows = {r[0]: r[1:] for r in duckdb.sql(
        f"SELECT name, records, partners, types, records_india, datasets FROM '{out}' ORDER BY name").fetchall()}
    assert rows["Aus bus"] == (3, 2, ["eats", "pollinates"], 2, 2)
    assert rows["Cus dus"] == (2, 1, ["eats"], 1, 1)                   # a target counts as well as a source
    assert rows["Eus fus"][3] == 1                                     # India from the locality name
    assert rows["Gus hus"] == (1, 0, ["parasiteOf"], 1, 1)
    assert rows["Hus ius"][3] == 0                                     # "Indiana", "Indian subregion": not India


def test_partners_one_row_per_species_partner_and_kind_of_link_from_both_sides(tmp_path, districts):
    """edges.parquet: what each species does to each partner (outgoing) or has done to it (incoming), with the
    partner's kingdom and class, records and records in India."""
    tsv = snapshot(tmp_path / "i.tsv.gz", [
        ["Aus bus", "eats", "Cus dus", "10.5", "76.5", "", "ds/one", "x", "Animalia", "Mammalia", "Plantae", "Magnoliopsida"],
        ["Aus bus", "eats", "Cus dus", "40.0", "-3.0", "Spain", "ds/two", "x", "Animalia", "Mammalia", "Plantae", "Magnoliopsida"],
        ["Vus wus", "pathogenOf", "Aus bus", "", "", "India", "ds/one", "x", "Orthornavirae", "", "Animalia", "Mammalia"],
        ["Aus bus", "eats", "", "", "", "", "ds/one", "x"],                                   # no partner species
    ])
    edges = tmp_path / "edges.parquet"
    globi.species_table(duckdb.connect(), tsv, districts, tmp_path / "s.parquet", edges)
    rows = sorted(duckdb.sql(f"SELECT name, partner, type, outgoing, pkingdom, pclass, records, records_india FROM '{edges}'").fetchall())
    assert rows == [("Aus bus", "Cus dus", "eats", True, "Plantae", "Magnoliopsida", 2, 1),
                    ("Aus bus", "Vus wus", "pathogenOf", False, "Orthornavirae", None, 1, 1),
                    ("Cus dus", "Aus bus", "eats", False, "Animalia", "Mammalia", 2, 1),
                    ("Vus wus", "Aus bus", "pathogenOf", True, "Animalia", "Mammalia", 1, 1)]


class Resp:
    def __init__(self, status, body=b"", headers=None):
        self.status_code, self.body, self.headers = status, body, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Http:
    """A file served with an ETag and Range; stop_after: bytes to send before the connection drops."""

    def __init__(self, body, etag='"e1"', stop_after=None):
        self.body, self.etag, self.stop_after, self.ranges = body, etag, stop_after, []

    def head(self, url, **kw):
        return Resp(200, headers={"ETag": self.etag, "Content-Length": str(len(self.body))})

    def get(self, url, headers=None, **kw):
        start = int((headers or {}).get("Range", "bytes=0-")[6:].rstrip("-") or 0)
        self.ranges.append(start)
        part = self.body[start:]
        if self.stop_after is not None:
            part, self.stop_after = part[:self.stop_after], None
            r = Resp(206 if start else 200, part)

            def broken(n, part=part):
                yield from Resp(0, part).iter_content(n)
                raise ConnectionError("dropped")
            r.iter_content = broken
            return r
        return Resp(206 if start else 200, part)


def test_the_download_resumes_and_a_second_run_downloads_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(globi, "CHUNK", 4)
    body = b"0123456789" * 5
    dest = tmp_path / "i.tsv.gz"
    http = Http(body, stop_after=17)
    with pytest.raises(ConnectionError):
        globi.download(http, dest)
    assert (tmp_path / "i.tsv.gz.part").stat().st_size == 17 and not dest.exists()   # every byte received is kept
    assert globi.download(http, dest) is True and dest.read_bytes() == body
    assert http.ranges == [0, 17]                                                       # continued, not restarted
    again = Http(body)
    assert globi.download(again, dest) is False and again.ranges == []                  # same ETag: nothing to do
    meta = json.loads((tmp_path / "i.tsv.gz.json").read_text())
    assert meta["etag"] == '"e1"' and meta["length"] == len(body)


def test_a_new_snapshot_is_downloaded_from_the_start(tmp_path, monkeypatch):
    monkeypatch.setattr(globi, "CHUNK", 4)
    dest = tmp_path / "i.tsv.gz"
    globi.download(Http(b"old snapshot"), dest)
    new = Http(b"a newer snapshot", etag='"e2"')
    assert globi.download(new, dest) is True and dest.read_bytes() == b"a newer snapshot" and new.ranges == [0]


def test_refresh_publishes_the_table_and_a_run_with_the_same_snapshot_does_nothing(tmp_path, monkeypatch, districts):
    """On GitHub Actions each run starts with an empty disk: the snapshot's ETag is kept in R2 next to the table, so a
    week with no new snapshot downloads nothing. Only the species table goes to R2 (cache/, never served)."""
    from tests.r2_fake import FakeS3
    monkeypatch.setenv("R2_BUCKET", "b")
    monkeypatch.setattr(globi, "CHUNK", 1 << 16)
    body = gzip.compress(("\t".join(HEADER) + "\nAus bus\teats\tCus dus\t10.5\t76.5\t\td\tx\t\t\t\t\n").encode())
    s3, http = FakeS3(), Http(body)
    assert globi.refresh(http, s3, tmp_path / "one", districts) == "published"
    assert sorted(s3.store) == ["cache/globi/edges.parquet", "cache/globi/meta.json", "cache/globi/species.parquet"]
    again = Http(body)
    assert globi.refresh(again, s3, tmp_path / "two", districts) == "unchanged" and again.ranges == []
    assert globi.refresh(Http(body, etag='"e2"'), s3, tmp_path / "three", districts) == "published"
