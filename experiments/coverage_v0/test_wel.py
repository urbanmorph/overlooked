"""Tests for the coverage study. Run: .venv/bin/python -m pytest experiments/coverage_v0 -q -p no:cacheprovider"""

import duckdb
import pytest
from wel import COLUMNS, by_group, flags


def write(con, sql, path):
    con.sql(f"COPY ({sql}) TO '{path}' (FORMAT parquet)")
    return str(path)


@pytest.fixture
def lists(tmp_path):
    """Five species of one group, each stopping at a different stage of the funnel."""
    con = duckdb.connect()
    master = write(con, """SELECT * FROM (VALUES
        ('K1', 'Aus bus', 'Birds', ['ZSI', 'GBIF'], true, ['ho'], [32]),       -- recent district record
        ('K2', 'Cus dus', 'Birds', ['GBIF'], true, ['sp'], [29]),              -- old district record
        ('K3', 'Eus fus', 'Birds', ['GBIF'], true, ['sp', 'lm'], []::INTEGER[]),  -- no place
        ('K4', 'Gus hus', 'Birds', ['ZSI'], false, ['chk'], []::INTEGER[]),    -- checklist only
        (NULL, 'Xus yus', 'Birds', ['BSI'], false, ['chk', 'nm'], []::INTEGER[]))  -- name not matched
        t(key, name, "group", sources, observed, labels, states_observed)""", tmp_path / "master.parquet")
    ledger = write(con, """SELECT * FROM (VALUES ('K1', 101, 32, 1990, 2024), ('K2', 201, 29, 1890, 1950))
        t(species_key, district_lgd, state_lgd, first_year, last_year)""", tmp_path / "ledger.parquet")
    unl = write(con, """SELECT * FROM (VALUES ('K3', NULL::INTEGER, 2020)) t(species_key, state_lgd, last_year)""",
                tmp_path / "unlocated.parquet")
    return {"master": master, "ledger": ledger, "unlocated": unl}


def test_each_species_gets_a_flag_per_column(lists):
    con = duckdb.connect()
    f = {r[0]: r for r in flags(con, **lists, recent_from=2016).fetchall()}
    cols = ["name"] + list(COLUMNS)
    row = lambda n: dict(zip(cols, f[n]))
    assert list(COLUMNS) == ["accepted_name", "checklist", "open_record", "in_state", "in_district", "recent"]
    assert row("Aus bus") == {"name": "Aus bus", "accepted_name": True, "checklist": True, "open_record": True,
                                    "in_state": True, "in_district": True, "recent": True}
    assert row("Cus dus")["recent"] is False and row("Cus dus")["in_district"] is True
    # A recent record with no place is not "recent" in the funnel: each stage nests in the one before.
    assert row("Eus fus")["open_record"] and not row("Eus fus")["in_state"] and not row("Eus fus")["recent"]
    assert row("Gus hus")["checklist"] and not row("Gus hus")["open_record"]
    assert not row("Xus yus")["accepted_name"]


def test_counts_by_group_nest_like_a_funnel(lists):
    con = duckdb.connect()
    g = by_group(con, flags(con, **lists, recent_from=2016))
    assert g["Birds"] == {"species": 5, "accepted_name": 4, "checklist": 3, "open_record": 3, "in_state": 2,
                          "in_district": 2, "recent": 1}
    funnel = ["species", "open_record", "in_state", "recent"]
    for counts in g.values():
        assert all(counts[a] >= counts[b] for a, b in zip(funnel, funnel[1:]))
