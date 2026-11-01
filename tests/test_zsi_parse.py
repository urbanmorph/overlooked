"""The ZSI Fauna of India checklists (pipeline/zsi_parse.py, pipeline/zsi_match.py): names lost to the parser come
back. Two causes found on 1 Nov 2026: years in square brackets ("(Cramer, [1780])", the Lepidoptera checklist), and
letters the OCR of scanned pages confuses ("Ardeola grayll" for grayii, "Lxobrychus" for Ixobrychus)."""

import duckdb
import pytest

from pipeline import zsi_match, zsi_parse

COL = {"names": {"Ardeola grayii", "Ardeola bacchus", "Ixobrychus sinensis", "Aus grayi", "Aus ilia", "Aus lila"},
       "genera": {"Ardeola", "Ixobrychus", "Aus"}}


def names(text):
    return [m.group("name") for m in zsi_parse.ENTRY.finditer(text)]


def test_a_year_in_square_brackets_is_an_authority():
    text = "Euploea core (Cramer, [1780]) Euploea klugii Moore, [1858] Euploea crameri Lucas, 1853"
    assert names(text) == ["Euploea core", "Euploea klugii", "Euploea crameri"]


def test_a_year_in_round_brackets_after_the_author():
    text = "Hypena laceratalis Walker, (1859) Creatonotos nigergangis N. Singh & Kirti (2016) Aus bus (Smith, 1900)"
    assert names(text) == ["Hypena laceratalis", "Creatonotos nigergangis", "Aus bus"]


def test_an_authority_may_start_with_a_lowercase_particle():
    text = "Tarucus ananda (de Nicéville, [1884]) Celatoxia marginata (de Nicéville, [1884]) Aus bus van der Poll, 1890"
    assert names(text) == ["Tarucus ananda", "Celatoxia marginata", "Aus bus"]


def test_ocr_misreads_of_a_real_name_are_read_as_that_name():
    text = zsi_parse.flat("399 Indian Pond Heron Ardeola (Sykes, 1832)\ngrayll\n\n"
                          "384 Yellow Bittern Lxobrychus (Gmelin, JF,\nsinensis 1789)\n400 Chinese Pond Heron Ardeola bacchus")
    assert [n for n, _ in zsi_parse.dictionary_names(text, COL)] == ["Ardeola grayii", "Ixobrychus sinensis", "Ardeola bacchus"]


def test_a_garbled_epithet_one_letter_from_one_name_of_its_genus_is_that_name():
    col = {"names": {"Ciconia episcopus", "Ciconia ciconia", "Ciconia nigra", "Curruca curruca", "Curruca nana",
                     "Bus abcdef", "Bus abcdeg"}, "genera": {"Ciconia", "Curruca", "Bus"}}
    text = zsi_parse.flat("364 Woolly-necked Stork Ciconia_ |(Boddaert, 1783)\neplsCcOpus\n"
                          "897 Lesser Whitethroat Curruca  |(Linnaeus, 1758)\nCUurruca\n")
    assert [n for n, _ in zsi_parse.dictionary_names(text, col)] == ["Ciconia episcopus", "Curruca curruca"]
    assert zsi_parse.dictionary_names("Bus (Smith, 1900) abcdex", col) == []    # one letter from two names
    assert zsi_parse.dictionary_names("Bus (Smith, 1900) abcd", col) == []      # too short to guess


def test_a_misread_that_fits_two_names_is_left_out():
    assert zsi_parse.dictionary_names("Aus (Smith, 1900) liia", COL) == []       # ilia or lila: not guessed
    assert [n for n, _ in zsi_parse.dictionary_names("Aus grayi", COL)] == ["Aus grayi"]   # an exact name stays


def test_the_match_reads_past_ocr_letters_when_one_name_fits(tmp_path, monkeypatch):
    bb = tmp_path / "animals.parquet"
    duckdb.sql(f"""COPY (SELECT * FROM (VALUES
        ('1', 'accepted', 'species', 'Animalia', 'Ardeidae', '', 'Botaurus sinensis', 'Botaurus', 'sinensis', '', '1'),
        ('2', 'synonym', 'species', 'Animalia', 'Ardeidae', '', 'Ixobrychus sinensis', 'Ixobrychus', 'sinensis', '', '1'))
        t(id, status, rank, kingdom, family, authorship, canonical_name, genus, epithet, infra, accepted_id))
        TO '{bb}' (FORMAT parquet)""")
    src = tmp_path / "in.csv"
    src.write_text("checklist,family,name,rank,authority,mark,page\n120_Aves.pdf,Ardeidae,Lxobrychus sinensis,species,,,19\n")
    out, qc = tmp_path / "out.csv", tmp_path / "qc.csv"
    zsi_match.match(src, out, qc, bb)
    (row,) = duckdb.sql(f"SELECT match_type, col_accepted_name FROM read_csv('{out}', all_varchar=true)").fetchall()
    assert row == ("ocr_letters", "Botaurus sinensis")


@pytest.mark.parametrize("a,b", [("grayll", "grayii"), ("Lxobrychus", "Ixobrychus"), ("rnalabarica", "malabarica")])
def test_fold_makes_ocr_look_alikes_equal(a, b):
    assert zsi_parse.fold(a) == zsi_parse.fold(b)
