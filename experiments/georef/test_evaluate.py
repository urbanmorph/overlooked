"""Tests for the sampling and scoring helpers of the georeferencing test."""

from evaluate import caps, kind_of, outcome


def test_caps_fill_to_total_and_keep_small_datasets_whole():
    got = caps({"a": 10, "b": 1000, "c": 5000}, 1010)
    assert got["a"] == 10
    assert sum(got.values()) == 1010
    assert abs(got["b"] - got["c"]) <= 1


def test_caps_take_everything_when_total_is_large():
    assert caps({"a": 3, "b": 4}, 100) == {"a": 3, "b": 4}


def test_outcome():
    assert outcome([5], 5) == "right"
    assert outcome([5], 6) == "wrong"
    assert outcome([], 6) == "none"
    assert outcome([5], None) == "no truth"


def test_outcome_of_a_district_set():
    # Right when the true district is anywhere in the set (parent and the districts carved from it).
    assert outcome([102, 769], 769) == "right"
    assert outcome([102, 769], 110) == "wrong"


def test_kind_of():
    assert kind_of("PRESERVED_SPECIMEN") == "specimen"
    assert kind_of("MATERIAL_SAMPLE") == "specimen"
    assert kind_of("HUMAN_OBSERVATION") == "observation"
    assert kind_of("MATERIAL_CITATION") == "material citation"
    assert kind_of("OCCURRENCE") == "other"
