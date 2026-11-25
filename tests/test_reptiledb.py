"""The Reptile Database (pipeline/reptiledb.py): English names for reptiles that iNaturalist has none for, read from
the database's own CC BY 4.0 copy on ChecklistBank, downloaded only when a new version is published."""

import io
import zipfile

import duckdb

from pipeline import reptiledb

USAGE = ("col:ID\tcol:status\tcol:scientificName\tcol:rank\n"
         "T1\taccepted\tOphiophagus kaalinga\tspecies\n"
         "T2\taccepted\tCylindrophis ruffus\tspecies\n"
         "T3\taccepted\tHelicops scalaris\tspecies\n"
         "T4\tsynonym\tNaja oldname\tspecies\n"
         "T5\taccepted\tAus bus cus\tsubspecies\n"
         "T6\taccepted\tGopherus agassizii\tspecies\n"
         "T7\taccepted\tUromastyx aegyptia\tspecies\n"
         "T8\taccepted\tHemiphyllodactylus typus\tspecies\n"
         "T9\taccepted\tCyrtodactylus x\tspecies\n")
VERN = ("col:taxonID\tcol:name\tcol:language\n"
        "T1\tWestern Ghats king cobra\teng\n"
        "T1\tKönigskobra\tdeu\n"
        "T2\tMirza’s Pipe-Snake [mirzae]\teng\n"          # a subspecies' name on the species: never the species'
        "T3\tLadder Keelback (Hoge's Keelback)\teng\n"     # a second name in brackets: dropped
        "T4\tOld Cobra\teng\n"                             # a synonym: not a species of its own
        "T5\tCus Snake\teng\n"                             # a subspecies
        "T6\t(Californian) Desert Tortoise\teng\n"
        "T7\tLeptien’s Mastigure (leptieni)\teng\n"        # a subspecies epithet in brackets: not the species'
        "T8\t(Indopacific) Tree Gecko\teng\n"
        "T8\tCommon Dwarf Gecko\teng\n"                    # a name with no brackets wins
        "T8\tIndopacific Slender Gecko\teng\n"
        "T9\tBattambang Leaf-toed Gecko (\teng\n"        # cut short in the source: no name
        "T9\tNanling Leopard Gecko]\teng\n")


def export(usage=USAGE, vern=VERN):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("NameUsage.tsv", usage)
        z.writestr("VernacularName.tsv", vern)
    return b.getvalue()


class Resp:
    def __init__(self, body=None, content=b"", status=200):
        self.body, self.content, self.status_code = body, content, status

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeClb:
    def __init__(self, version="2026-06", fail=False):
        self.version, self.fail, self.asked = version, fail, []

    def get(self, url, params=None, **kw):
        self.asked.append(url)
        if self.fail:
            raise ConnectionError("down")
        if url == reptiledb.DATASET_API:
            return Resp({"version": self.version, "attempt": 34})
        assert url == reptiledb.EXPORT and params == {"format": "ColDP", "extended": "true"}
        return Resp(content=export())


def rows(path):
    return dict(duckdb.sql(f"SELECT name, english FROM '{path}'").fetchall())


def test_one_english_name_per_accepted_species(tmp_path):
    out = reptiledb.refresh(FakeClb(), None, tmp_path)
    assert rows(out) == {"Ophiophagus kaalinga": "Western Ghats king cobra", "Gopherus agassizii": "Desert Tortoise",
                         "Hemiphyllodactylus typus": "Common Dwarf Gecko", "Helicops scalaris": "Ladder Keelback"}
    assert duckdb.sql(f"SELECT DISTINCT version FROM '{out}'").fetchall() == [("2026-06",)]


def test_the_export_is_read_again_only_for_a_new_version(tmp_path):
    reptiledb.refresh(FakeClb(), None, tmp_path)
    same = FakeClb()
    reptiledb.refresh(same, None, tmp_path)
    assert same.asked == [reptiledb.DATASET_API]
    new = FakeClb(version="2026-11")
    out = reptiledb.refresh(new, None, tmp_path)
    assert new.asked == [reptiledb.DATASET_API, reptiledb.EXPORT]
    assert duckdb.sql(f"SELECT DISTINCT version FROM '{out}'").fetchall() == [("2026-11",)]


def test_the_last_copy_when_checklistbank_does_not_answer(tmp_path):
    first = reptiledb.refresh(FakeClb(), None, tmp_path)
    assert reptiledb.refresh(FakeClb(fail=True), None, tmp_path) == first
    assert reptiledb.refresh(FakeClb(fail=True), None, tmp_path / "empty") is None
