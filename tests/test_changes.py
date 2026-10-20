"""Species state per snapshot and the species change feed (pipeline/changes.py)."""

import json

import duckdb
import pytest

from pipeline import changes

# Species rows: key, name, kingdom, phylum, class, order, family, genus.
BIRD = ("Animalia", "Chordata", "Aves", "Passeriformes", "Motacillidae", "Anthus")
PLANT = ("Plantae", "Tracheophyta", "Magnoliopsida", "Lamiales", "Lamiaceae", "Ocimum")
SOURCES = {"records": {"ledger_cube": 1000, "species_history": 100}, "queries": {"ledger_cube": "q1"},
           "boundaries": "b1", "gbif_india_records": 5000}


def snapshot(folder, species, ledger, decades):
    """Write the three snapshot files a state is built from.
    species: (key, name, *classification); ledger: (key, district, state, first, last, n); decades: (key, decade, basis, n)."""
    folder.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("CREATE TABLE s (species_key VARCHAR, name VARCHAR, kingdom VARCHAR, phylum VARCHAR, class VARCHAR, "
                "\"order\" VARCHAR, family VARCHAR, genus VARCHAR)")
    con.executemany("INSERT INTO s VALUES (?, ?, ?, ?, ?, ?, ?, ?)", species)
    con.execute("CREATE TABLE l (species_key VARCHAR, district_lgd INTEGER, state_lgd INTEGER, first_year INTEGER, "
                "last_year INTEGER, n_records DOUBLE, n_records_near_shore DOUBLE)")
    con.executemany("INSERT INTO l VALUES (?, ?, ?, ?, ?, ?, 0)", ledger)
    con.execute("CREATE TABLE d (species_key VARCHAR, decade INTEGER, basis VARCHAR, n_records DOUBLE)")
    con.executemany("INSERT INTO d VALUES (?, ?, ?, ?)", decades)
    for t, f in (("s", "species"), ("l", "ledger"), ("d", "species_decade")):
        con.sql(f"COPY {t} TO '{folder / f}.parquet' (FORMAT parquet)")
    return folder


def iucn_file(path, rows):
    """A Red List table as pipeline/iucn.py writes it: (name, category, accepted, kingdom)."""
    con = duckdb.connect()
    con.execute("CREATE TABLE i (name VARCHAR, category VARCHAR, accepted BOOLEAN, iucn_id VARCHAR, kingdom VARCHAR, "
                "phylum VARCHAR, class VARCHAR, \"order\" VARCHAR, family VARCHAR)")
    con.executemany("INSERT INTO i VALUES (?, ?, ?, '1', ?, NULL, NULL, NULL, NULL)", rows)
    con.sql(f"COPY i TO '{path}' (FORMAT parquet)")
    return path


def rows(folder, file="species_state.parquet"):
    con = duckdb.connect()
    cols = [c[0] for c in con.sql(f"DESCRIBE SELECT * FROM '{folder / file}'").fetchall()]
    return [dict(zip(cols, r)) for r in con.sql(f"SELECT * FROM '{folder / file}'").fetchall()]


@pytest.fixture
def first(tmp_path):
    """October 2026: a pipit in two districts, a mint in one, a pipit seen last in 1996, a bird with no place."""
    return snapshot(tmp_path / "2026-10", [
        ("A1", "Anthus nilghiriensis", *BIRD),
        ("P1", "Ocimum americanum", *PLANT),
        ("A2", "Anthus similis", *BIRD),
        ("A3", "Anthus rufulus", *BIRD),
        ("A4", "Anthus roseatus", *BIRD),
        ("A5", "Anthus campestris", *BIRD),
        ("A6", "Anthus trivialis", *BIRD),
        ("A7", "Anthus hodgsoni", *BIRD),
    ], [
        ("A1", 101, 32, 1950, 2024, 40), ("A1", 102, 32, 1990, 2020, 10),
        ("P1", 201, 29, 1900, 1950, 3),
        ("A2", 101, 32, 1980, 1996, 2),
        ("A3", 101, 32, 2000, 2025, 5),
        ("A4", 101, 32, 2000, 2025, 5),
        ("A5", 101, 32, 1950, 1960, 1),
        ("A7", 101, 32, 2010, 2025, 30),
    ], [
        ("A1", 2020, "HUMAN_OBSERVATION", 45), ("A1", 1950, "PRESERVED_SPECIMEN", 5),
        ("P1", 1900, "PRESERVED_SPECIMEN", 3),
        ("A2", 1990, "HUMAN_OBSERVATION", 2),
        ("A3", 2020, "HUMAN_OBSERVATION", 5),
        ("A4", 2020, "HUMAN_OBSERVATION", 5),
        ("A5", 1960, "HUMAN_OBSERVATION", 1),
        ("A6", 2010, "OCCURRENCE", 4),
        ("A7", 2020, "HUMAN_OBSERVATION", 30),
    ])


@pytest.fixture
def second(tmp_path):
    """January 2027: A1 leaves district 102 and enters 103; P1 renamed; A2 now 31 years old; A3 under a new key;
    A4 gone; A5 recorded again (an old specimen newly published); A8 new; A7 jumps from 30 to 300 specimens."""
    return snapshot(tmp_path / "2027-01", [
        ("A1", "Anthus nilghiriensis", *BIRD),
        ("P1", "Ocimum africanum", *PLANT),
        ("A2", "Anthus similis", *BIRD),
        ("A3x", "Anthus rufulus", *BIRD),
        ("A5", "Anthus campestris", *BIRD),
        ("A6", "Anthus trivialis", *BIRD),
        ("A7", "Anthus hodgsoni", *BIRD),
        ("A8", "Anthus richardi", *BIRD),
    ], [
        ("A1", 101, 32, 1950, 2026, 42), ("A1", 103, 33, 2026, 2026, 1),
        ("P1", 201, 29, 1900, 1950, 3),
        ("A2", 101, 32, 1980, 1996, 2),
        ("A3x", 101, 32, 2000, 2025, 5),
        ("A5", 101, 32, 1950, 2001, 2),
        ("A7", 101, 32, 2010, 2025, 300),
        ("A8", 104, 33, 2026, 2026, 1),
    ], [
        ("A1", 2020, "HUMAN_OBSERVATION", 43),
        ("P1", 1900, "PRESERVED_SPECIMEN", 3),
        ("A2", 1990, "HUMAN_OBSERVATION", 2),
        ("A3x", 2020, "HUMAN_OBSERVATION", 5),
        ("A5", 1960, "HUMAN_OBSERVATION", 1), ("A5", 2000, "PRESERVED_SPECIMEN", 1),
        ("A6", 2010, "OCCURRENCE", 4),
        ("A7", 2020, "HUMAN_OBSERVATION", 30), ("A7", 2010, "PRESERVED_SPECIMEN", 270),
        ("A8", 2020, "HUMAN_OBSERVATION", 1),
    ])


# ---------------------------------------------------------------- state

def test_state_one_row_per_species(first, tmp_path):
    iucn = iucn_file(tmp_path / "iucn.parquet", [
        ("Anthus nilghiriensis", "VU", True, "Animalia"),
        ("Anthus nilghiriensis", "LC", False, "Animalia"),   # a synonym row: the assessed name wins
        ("Ocimum americanum", "LC", True, "Animalia"),       # other kingdom: not this plant
    ])
    meta = changes.state(first, "2026-10", SOURCES, iucn, {"etag": "e1"})
    by = {r["species_key"]: r for r in rows(first)}
    assert len(by) == 8 and meta["rows"] == 8
    a1 = by["A1"]
    assert a1["name"] == "Anthus nilghiriensis" and a1["grp"] == "Birds"
    assert a1["records"] == 50 and a1["records_placed"] == 50
    assert a1["records_observation"] == 45 and a1["records_specimen"] == 5 and a1["records_other"] == 0
    assert a1["districts"] == [101, 102] and a1["n_districts"] == 2 and a1["states"] == [32]
    assert (a1["first_year"], a1["last_year"]) == (1950, 2024)
    assert a1["districts_recent"] == 2           # both districts have a record since 1996 (2026 - 30)
    assert a1["iucn"] == "VU"
    assert by["P1"]["iucn"] == "NE" and by["P1"]["grp"].startswith("Plants")   # not assessed
    assert by["A2"]["districts_recent"] == 1     # 1996 counts as recent in 2026
    a6 = by["A6"]                                # records with coordinates, none placed in a district
    assert a6["records"] == 4 and a6["records_placed"] == 0 and a6["districts"] == [] and a6["last_year"] is None
    assert meta["ref_year"] == 2026 and meta["recent_years"] == changes.RECENT_YEARS
    assert meta["sources"] == SOURCES and meta["iucn"] == {"etag": "e1"}
    assert meta["totals"] == {"species": 8, "records": 100, "records_placed": 96, "districts": 3}
    assert json.loads((first / "species_state.json").read_text()) == meta


def test_state_without_iucn_table(first):
    meta = changes.state(first, "2026-10", SOURCES)
    assert meta["iucn"] is None
    assert all(r["iucn"] is None for r in rows(first))


def test_state_is_not_rebuilt_from_the_same_inputs(first):
    meta = changes.state(first, "2026-10", SOURCES)
    stamp = (first / "species_state.parquet").stat().st_mtime_ns
    assert changes.state(first, "2026-10", SOURCES) == meta
    assert (first / "species_state.parquet").stat().st_mtime_ns == stamp
    other = changes.state(first, "2026-10", {**SOURCES, "boundaries": "b2"})
    assert other["inputs"] != meta["inputs"]


# ---------------------------------------------------------------- change feed

def feed(old, new, old_sources=SOURCES, new_sources=SOURCES, iucn_old=None, iucn_new=None):
    changes.state(old, old.name, old_sources, *(iucn_old or (None, None)))
    changes.state(new, new.name, new_sources, *(iucn_new or (None, None)))
    summary = changes.compare(old, new)
    return summary, {(r["change"], r["species_key"]): r for r in rows(new, "species_changes.parquet")}


def test_first_snapshot_is_the_baseline(first):
    changes.state(first, "2026-10", SOURCES)
    summary = changes.compare(None, first)
    assert summary["baseline"] and summary["from"] is None and summary["to"] == "2026-10"
    assert summary["rows"] == 0 and set(summary["counts"]) == set(changes.CHANGE_TYPES)
    assert rows(first, "species_changes.parquet") == []


def test_same_snapshot_gives_no_changes(first, tmp_path):
    import shutil
    again = tmp_path / "2026-10-again"
    shutil.copytree(first, again)
    summary, got = feed(first, again)
    assert got == {} and summary["rows"] == 0 and not summary["baseline"]


def test_change_types(first, second):
    summary, got = feed(first, second)
    assert set(got) == {
        ("districts_added", "A1"), ("districts_removed", "A1"),
        ("renamed", "P1"),
        ("no_recent_record", "A2"),
        ("key_changed", "A3x"),
        ("not_in_snapshot", "A4"),
        ("recent_record_again", "A5"), ("newly_recorded", "A8"),
    }
    assert got[("districts_added", "A1")]["districts_added"] == [103]
    assert got[("districts_removed", "A1")]["districts_removed"] == [102]
    assert got[("renamed", "P1")]["name_before"] == "Ocimum americanum"
    assert got[("key_changed", "A3x")]["species_key_before"] == "A3"
    a2 = got[("no_recent_record", "A2")]
    assert (a2["last_year_before"], a2["last_year_after"]) == (1996, 1996)
    assert got[("recent_record_again", "A5")]["reason"] == "older record, newly published"
    assert got[("newly_recorded", "A8")]["reason"] == "new record"
    assert got[("newly_recorded", "A8")]["districts_added"] == [104]   # a new species carries its districts
    assert summary["counts"]["districts_added"] == 1 and summary["from"] == "2026-10" and summary["to"] == "2027-01"


def test_artefact_flags(first, second):
    _, got = feed(first, second)
    # A7: 30 observations, then 270 specimens more at once: a dataset added, not a change in the field.
    # It has no change of its own, so the jump shows in the summary list of large record changes.
    assert ("districts_added", "A7") not in got
    summary = json.loads((second / "species_changes.json").read_text())
    jump = {r[0]: r for r in summary["record_jumps"]}
    assert jump["A7"][2:4] == [30, 300] and "kind_shift" in jump["A7"][4]
    assert "latest_record_removed" not in got[("no_recent_record", "A2")]["flags"]
    assert got[("districts_removed", "A1")]["flags"] == []


def test_source_changes_flag_every_row(first, second):
    bigger = {**SOURCES, "records": {"ledger_cube": 1200, "species_history": 100}, "boundaries": "b2"}
    summary, got = feed(first, second, new_sources=bigger)
    assert set(summary["sources"]["shifts"]) == {"boundaries", "records:ledger_cube"}
    assert "large_source_change" in got[("newly_recorded", "A8")]["flags"]
    assert "boundaries_changed" in got[("districts_added", "A1")]["flags"]
    assert "boundaries_changed" not in got[("renamed", "P1")]["flags"]


def test_unknown_sources_are_not_shifts(first, second):
    summary, _ = feed(first, second, old_sources={})
    assert summary["sources"]["shifts"] == [] and summary["sources"]["unknown"]


def test_iucn_changes_only_when_both_months_have_the_table(first, second, tmp_path):
    old = iucn_file(tmp_path / "i1.parquet", [("Anthus similis", "LC", True, "Animalia"),
                                              ("Ocimum americanum", "LC", True, "Plantae")])
    new = iucn_file(tmp_path / "i2.parquet", [("Anthus similis", "NT", True, "Animalia"),
                                              ("Anthus nilghiriensis", "VU", True, "Animalia"),
                                              ("Ocimum americanum", "LC", True, "Plantae")])
    _, got = feed(first, second, iucn_old=(old, {"etag": "1"}), iucn_new=(new, {"etag": "2"}))
    assert (got[("iucn_changed", "A2")]["iucn_before"], got[("iucn_changed", "A2")]["iucn_after"]) == ("LC", "NT")
    assert (got[("iucn_changed", "A1")]["iucn_before"], got[("iucn_changed", "A1")]["iucn_after"]) == ("NE", "VU")
    # P1 was renamed, so its new name has no Red List match: a change of name, not of category.
    assert got[("iucn_changed", "P1")]["iucn_after"] == "NE" and "name_changed" in got[("iucn_changed", "P1")]["flags"]
    assert "name_changed" not in got[("iucn_changed", "A2")]["flags"]
    _, got = feed(first, second, iucn_new=(new, {"etag": "2"}))
    assert not [k for k in got if k[0] == "iucn_changed"]


def test_latest_record_removed_is_flagged(first, tmp_path):
    later = snapshot(tmp_path / "2026-11", [("A1", "Anthus nilghiriensis", *BIRD)],
                     [("A1", 101, 32, 1950, 1990, 40)], [("A1", 1990, "HUMAN_OBSERVATION", 40)])
    _, got = feed(first, later)
    row = got[("no_recent_record", "A1")]
    assert (row["last_year_before"], row["last_year_after"]) == (2024, 1990)
    assert "latest_record_removed" in row["flags"]


def test_compare_is_skipped_for_the_same_inputs(first, second):
    feed(first, second)
    stamp = (second / "species_changes.parquet").stat().st_mtime_ns
    before = (second / "species_changes.json").read_text()
    changes.compare(first, second)
    assert (second / "species_changes.parquet").stat().st_mtime_ns == stamp
    assert (second / "species_changes.json").read_text() == before


def test_sources_from_a_manifest():
    manifest = {"downloads": [{"query": "ledger_cube", "records": 10}], "boundaries": {"sha256": "c205da56ce05" + "0" * 52},
                "health": {"sources": {"gbif_api": {"fingerprint": {"india_records": 7}}}}}
    assert changes.sources(manifest) == {"records": {"ledger_cube": 10}, "queries": None, "boundaries": "c205da56ce05",
                                         "gbif_india_records": 7}
    assert changes.sources({**manifest, "queries": {"ledger_cube": "q"}})["queries"] == {"ledger_cube": "q"}


def test_previous_state_built_from_snapshot_files(first, tmp_path):
    """A published snapshot made before species_state existed: its state is built from its own files."""
    (first / "manifest.json").write_text(json.dumps({"downloads": [], "boundaries": {"sha256": "b" * 64}}))
    assert changes.previous_state(first, "snapshots/2026-10", None) == first
    assert json.loads((first / "species_state.json").read_text())["sources"]["boundaries"] == "b" * 12
    assert changes.previous_state(tmp_path / "2025-01", "snapshots/2025-01", None) is None


# ---------------------------------------------------------------- monthly run

def test_monthly_run_compares_with_the_previous_published_snapshot(first, second, tmp_path, monkeypatch):
    from pipeline import run
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "2026-10.json").write_text(json.dumps({"run_id": "2026-10", "status": "published", "requested": "2026-10-01"}))
    (runs / "2027-01.json").write_text(json.dumps({"run_id": "2027-01", "status": "requested", "requested": "2027-01-01"}))
    monkeypatch.setattr(run, "RUNS", runs)
    monkeypatch.setattr(run, "SNAPSHOTS", tmp_path)
    monkeypatch.setattr(changes, "iucn_input", lambda s3=None: (None, None))
    feed = run.species_feed(second, "2027-01", None, SOURCES, None)
    assert feed["from"] == "2026-10" and feed["counts"]["newly_recorded"] == 1
    assert (first / changes.STATE).exists()          # the previous state was built from its snapshot files
    # A test run (one state) is never compared with the all-India snapshot.
    assert run.species_feed(second, "2027-01", "Kerala", SOURCES, None)["baseline"]


def test_a_failed_species_feed_does_not_stop_the_monthly_run(second, monkeypatch, capsys):
    from pipeline import run

    def broken(*a, **k):
        raise RuntimeError("bad state")
    monkeypatch.setattr(changes, "iucn_input", lambda s3=None: (None, None))
    monkeypatch.setattr(changes, "state", broken)
    assert run.species_feed(second, "2027-01", None, SOURCES, None) is None
    assert "species changes not built: bad state" in capsys.readouterr().out
