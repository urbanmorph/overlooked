"""Tests for corpus v0 logic. Run with the model-check venv:
data/model_check/.venv/bin/python -m pytest experiments/corpus_v0 -q -p no:cacheprovider
"""

from collections import Counter

import numpy as np
import pandas as pd
import pytest
from logic import (
    combine_probs,
    conformal_threshold,
    done_ids,
    fit_temperature,
    hash_unit,
    in_validation,
    knn_class_scores,
    match_name,
    observer_split,
    open_data_url,
    page_name,
    research_grade_at,
    sample_capped,
    softmax,
    unseen_summary,
    waited_record,
)

# --- photo URLs -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, want",
    [
        (
            "https://inaturalist-open-data.s3.amazonaws.com/photos/12345/original.jpg",
            "https://inaturalist-open-data.s3.amazonaws.com/photos/12345/medium.jpg",
        ),
        (
            "https://static.inaturalist.org/photos/987/original.jpeg?1600000000",
            "https://inaturalist-open-data.s3.amazonaws.com/photos/987/medium.jpeg",
        ),
        ("https://inaturalist-open-data.s3.amazonaws.com/photos/5/large.png", None),
        ("https://example.org/photos/5/original.jpg", None),
        ("", None),
        (None, None),
    ],
)
def test_open_data_url(url, want):
    # large.png is a size we do not rewrite: only "original" URLs as GBIF publishes them are mapped
    assert open_data_url(url) == want


# --- observer split -------------------------------------------------------------------------------------


def test_hash_unit_is_stable_and_in_range():
    assert hash_unit("Some Observer") == hash_unit("Some Observer")
    assert hash_unit("Some Observer") != hash_unit("Other Observer")
    assert 0 <= hash_unit("x") < 1
    assert hash_unit("x", salt="a") != hash_unit("x", salt="b")


def test_observer_split_shares_and_consistency():
    names = [f"observer {i}" for i in range(20000)]
    split = [observer_split(n) for n in names]
    share = Counter(split)["test"] / len(split)
    assert 0.19 < share < 0.21
    assert set(split) == {"train", "test"}
    # every observation of one observer gets the same side
    assert len({observer_split("observer 7") for _ in range(5)}) == 1


def test_observer_split_empty_name_is_test():
    # no observer name: we cannot keep it apart from training, so never train on it
    assert observer_split("") == "test"
    assert observer_split(None) == "test"


# --- capped sampling ------------------------------------------------------------------------------------


def test_sample_capped_spreads_over_observers_then_states():
    rows = []
    # species A: 10 obs by alice in Kerala, 10 by bob (5 Kerala, 5 Goa), 1 by carol in Assam
    rows += [("A", "alice", "Kerala")] * 10
    rows += [("A", "bob", "Kerala")] * 5 + [("A", "bob", "Goa")] * 5
    rows += [("A", "carol", "Assam")]
    # species B: 2 obs only
    rows += [("B", "dan", "Goa")] * 2
    df = pd.DataFrame(rows, columns=["species", "observer", "state"])
    out = sample_capped(df, cap=4, by="species", seed=1)
    a = out[out.species == "A"]
    assert len(a) == 4 and len(out[out.species == "B"]) == 2
    assert set(a.observer) == {"alice", "bob", "carol"}  # one each before anyone gets a second
    # the 4th pick is a second photo of alice or bob; bob's second should come from a new state (Goa/Kerala)
    assert a.observer.value_counts().max() == 2
    bob = a[a.observer == "bob"]
    if len(bob) == 2:
        assert set(bob.state) == {"Kerala", "Goa"}


def test_sample_capped_is_deterministic():
    df = pd.DataFrame({"species": ["A"] * 50, "observer": [f"o{i % 7}" for i in range(50)], "state": "X"})
    a = sample_capped(df, cap=10, by="species", seed=3)
    b = sample_capped(df, cap=10, by="species", seed=3)
    assert a.index.tolist() == b.index.tolist()
    assert a.observer.nunique() == 7


# --- research grade timing ------------------------------------------------------------------------------

SP, GEN, FAM, OTHER_SP = 100, 10, 1, 101  # species 100 and 101 in genus 10, family 1


def ident(user, day, taxon, current=True, disagreement=False):
    # as the iNaturalist API gives it: an identification's ancestor_ids do not include the taxon itself
    anc = {SP: [FAM, GEN], OTHER_SP: [FAM, GEN], GEN: [FAM], FAM: []}[taxon]
    return {
        "user": {"id": user},
        "created_at": f"2024-01-{day:02d}T00:00:00+00:00",
        "taxon": {"id": taxon, "ancestor_ids": anc},
        "current": current,
        "disagreement": disagreement,
    }


def test_rg_needs_two_agreeing():
    ids = [ident(1, 1, SP), ident(2, 20, SP)]
    assert research_grade_at(ids, SP).day == 20


def test_rg_coarser_id_does_not_block_or_count():
    ids = [ident(1, 1, SP), ident(2, 3, GEN), ident(3, 9, SP)]
    assert research_grade_at(ids, SP).day == 9


def test_rg_conflict_needs_more_than_two_thirds():
    # day 5: 2 agree, 1 disagrees -> 2/3 is not more than 2/3; day 12: 3 agree vs 1 -> RG
    ids = [ident(1, 1, SP), ident(2, 2, OTHER_SP), ident(3, 5, SP), ident(4, 12, SP)]
    assert research_grade_at(ids, SP).day == 12


def test_rg_explicit_ancestor_disagreement_counts_against():
    ids = [ident(1, 1, SP), ident(2, 2, GEN, disagreement=True), ident(3, 4, SP), ident(4, 6, SP)]
    assert research_grade_at(ids, SP).day == 6


def test_rg_user_changes_mind_only_latest_counts():
    # user 2 first says OTHER_SP, then on day 15 changes to SP
    ids = [ident(1, 1, SP), ident(2, 2, OTHER_SP, current=False), ident(2, 15, SP)]
    assert research_grade_at(ids, SP).day == 15


def test_rg_never_reached():
    assert research_grade_at([ident(1, 1, SP)], SP) is None


def test_waited_record():
    obs = {
        "id": 9,
        "created_at": "2024-01-01T00:00:00+00:00",
        "user": {"id": 1},
        "quality_grade": "research",
        "taxon": {"id": SP, "rank": "species", "ancestor_ids": [FAM, GEN, SP]},
        "identifications": [ident(1, 1, SP), ident(2, 2, GEN), ident(3, 31, SP)],
    }
    r = waited_record(obs)
    assert r["obs_id"] == 9
    assert r["waited_days"] == pytest.approx(30.0)
    assert r["n_identifiers"] == 2  # users other than the observer
    assert r["final_species_id"] == SP
    assert r["quality_grade"] == "research"


def test_waited_record_subspecies_uses_species_ancestor():
    obs = {
        "id": 9,
        "created_at": "2024-01-01T00:00:00+00:00",
        "user": {"id": 1},
        "quality_grade": "research",
        "taxon": {"id": 1000, "rank": "subspecies", "ancestor_ids": [FAM, GEN, SP, 1000], "min_species_taxon_id": SP},
        "identifications": [ident(1, 1, SP), ident(3, 3, SP)],
    }
    assert waited_record(obs)["final_species_id"] == SP


def test_waited_record_not_species():
    obs = {
        "id": 9,
        "created_at": "2024-01-01T00:00:00+00:00",
        "user": {"id": 1},
        "quality_grade": "needs_id",
        "taxon": {"id": GEN, "rank": "genus", "ancestor_ids": [FAM, GEN]},
        "identifications": [ident(1, 1, GEN)],
    }
    r = waited_record(obs)
    assert r["final_species_id"] is None and r["rg_at"] is None and r["waited_days"] is None


# --- names ----------------------------------------------------------------------------------------------


def test_match_name_exact_then_synonym():
    cand = {"Aquila hastata", "Apis cerana"}
    acc = {"Clanga hastata": "Aquila hastata", "Apis indica": "Apis cerana"}
    assert match_name(["Apis cerana", "Apis cerana"], cand, acc) == ("Apis cerana", "exact")
    assert match_name(["Clanga hastata", "Clanga hastata"], cand, acc) == ("Aquila hastata", "synonym")
    # the GBIF species is not a candidate but the verbatim (iNaturalist) name is
    assert match_name(["Apis indica", "Apis cerana"], cand, acc) == ("Apis cerana", "exact")
    assert match_name(["Foo bar", None], cand, acc) == (None, None)
    assert match_name([None, ""], cand, acc) == (None, None)


# --- classifiers and probabilities ----------------------------------------------------------------------


def test_softmax_rows_sum_to_one():
    p = softmax(np.array([[1.0, 2.0, 3.0], [0.0, 0.0, 0.0]]))
    assert np.allclose(p.sum(axis=1), 1)
    assert np.allclose(p[1], 1 / 3)


def test_knn_class_scores_best_similarity_per_class():
    train = np.array([[1, 0], [0.8, 0.6], [0, 1]], dtype=np.float32)
    ytr = np.array([0, 0, 1])
    q = np.array([[0.6, 0.8]], dtype=np.float32)
    s = knn_class_scores(q, train, ytr, n_classes=3)
    assert s.shape == (1, 3)
    assert s[0, 0] == pytest.approx(0.6 * 0.8 + 0.8 * 0.6)
    assert s[0, 1] == pytest.approx(0.8)
    assert s[0, 2] == -np.inf  # class with no training photo


def test_fit_temperature_recovers_scale():
    rng = np.random.default_rng(0)
    true_logits = rng.normal(size=(4000, 5)) * 3
    y = np.array([rng.choice(5, p=softmax(row[None])[0]) for row in true_logits])
    t = fit_temperature(true_logits * 2, y)  # over-confident by a factor 2
    assert t == pytest.approx(2.0, rel=0.15)


def test_combine_probs_keeps_species_without_training_photos():
    p_zs = np.array([[0.5, 0.3, 0.2]])
    p_cl = np.array([[0.0, 0.9, 0.1]])
    c = combine_probs(p_zs, p_cl, w=0.5)
    assert np.allclose(c, [[0.25, 0.6, 0.15]])
    assert c[0, 0] > 0


def test_unseen_summary():
    df = pd.DataFrame({"group": ["G", "G", "G", "H"], "seen": [True, False, False, True], "rank": [1, 2, np.inf, 1]})
    s = unseen_summary(df)
    g = s[s.group == "G"].iloc[0]
    assert g.n == 3 and g.unseen == 2 and g.unseen_pct == pytest.approx(66.7)
    assert g.unseen_top1 == 0.0 and g.unseen_top5 == 50.0 and g.seen_top1 == 100.0


def test_rg_hidden_identification_does_not_count():
    hidden = ident(2, 2, SP)
    hidden["hidden"] = True
    ids = [ident(1, 1, SP), hidden, ident(3, 8, SP)]
    assert research_grade_at(ids, SP).day == 8


# --- conformal threshold and validation split -----------------------------------------------------------


def test_conformal_threshold_matches_split_conformal_rule():
    # scores 1 - p(true); n = 9, level ceil(10 * 0.9) / 9 = 1.0 -> the largest score
    p_true = np.array([0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1])
    assert conformal_threshold(p_true, 0.9) == pytest.approx(0.1)
    # n = 19 at 0.9: level ceil(20 * 0.9) / 19 = 18/19, numpy quantile "higher" (as model_check scoring.py)
    # -> position ceil(18 * 18/19) = 18 -> the largest score, p = 0.05 (slightly conservative)
    p19 = np.linspace(0.95, 0.05, 19)
    assert conformal_threshold(p19, 0.9) == pytest.approx(0.05)


def test_conformal_threshold_too_few_rows_takes_everything():
    assert conformal_threshold(np.array([0.9, 0.8]), 0.95) == 0.0


def test_in_validation_by_observer():
    obs = [f"o{i}" for i in range(5000)]
    v = np.array([in_validation(o) for o in obs])
    assert 0.13 < v.mean() < 0.17
    assert in_validation("o1") == in_validation("o1")


def test_fixed_k():
    from logic import fixed_k

    ranks = np.array([1, 1, 1, 2, 2, 3, 5, 8, 20, np.inf])
    assert fixed_k(ranks, 0.9) == 20  # 9 of 10 within 20
    assert fixed_k(ranks, 0.5) == 2
    assert fixed_k(ranks, 0.95) is None  # the 10th is never in the list


# --- queue check: gate, per-row conformal coverage, growing the T1 sample --------------------------------


def gate_row(**kw):
    base = {
        "n": 150,
        "sp_cov": 90.0,
        "sp_median": 2,
        "top1": 85.0,
        "g_cov": 93.0,
        "g_median": 1,
        "new_n": 60,
        "new_sp_cov": 89.0,
        "new_g_cov": 92.0,
    }
    return {**base, **kw}


def test_gate_levels():
    from logic import gate

    assert gate(gate_row()) == "Quick to confirm"
    assert gate(gate_row(n=99)) == "not enough data"
    assert gate(gate_row(top1=79.9)) == "Genus first"
    assert gate(gate_row(sp_median=3)) == "Genus first"
    assert gate(gate_row(sp_cov=87.9)) == "Genus first"
    assert gate(gate_row(sp_cov=80, g_cov=87.0)) == "For an expert"
    assert gate(gate_row(sp_cov=80, g_median=3)) == "For an expert"


def test_gate_training_overlap_drops_one_level():
    from logic import gate

    assert gate(gate_row(new_sp_cov=84.9)) == "Genus first"
    assert gate(gate_row(new_sp_cov=84.9, new_n=39)) == "Quick to confirm"  # too few to judge
    assert gate(gate_row(top1=70, new_g_cov=84.0)) == "For an expert"
    assert gate(gate_row(top1=70, new_sp_cov=10.0)) == "Genus first"  # species coverage is not the level checked


def test_conformal_rows_matches_model_check():
    from logic import conformal_rows
    from scoring import _conformal

    rng = np.random.default_rng(1)
    n, c = 120, 30
    P = [softmax(rng.normal(size=(1, c)) * 3)[0] for _ in range(n)]
    T = [[int(rng.integers(c))] if rng.random() > 0.1 else [] for _ in range(n)]
    obs = [f"o{int(rng.integers(40))}" for _ in range(n)]
    cov, sizes = _conformal(P, T, obs, ["G"] * n, 0.9, 20, 0)
    p_true = np.array([p[t].max() if t else 0.0 for p, t in zip(P, T)])
    has = np.array([bool(t) for t in T])
    covered, tested, sz = conformal_rows(p_true, has, P, obs, 0.9, n_splits=20, seed=0)
    assert 100 * covered.sum() / tested.sum() == pytest.approx(cov)
    assert sorted(sz) == sorted(sizes.tolist())
    assert covered.shape == (n,) and (covered <= tested).all()


def test_next_sample_size():
    from logic import next_sample_size

    assert next_sample_size(300, 120, pool=5000) == 300  # enough already
    assert next_sample_size(300, 0, pool=250) == 300  # pool exhausted (capped at what was taken)
    assert next_sample_size(300, 30, pool=10000) == 300 + 840  # rate 0.1: 700 more sampled x 1.2
    assert next_sample_size(3900, 30, pool=10000) == 4000  # cap
    assert next_sample_size(300, 95, pool=10000) == 500  # at least one step of 200
    assert next_sample_size(4000, 30, pool=10000) == 4000


@pytest.mark.parametrize(
    "url, want",
    [
        (
            "https://inaturalist-open-data.s3.amazonaws.com/photos/123/square.jpg",
            "https://inaturalist-open-data.s3.amazonaws.com/photos/123/medium.jpg",
        ),
        (
            "https://static.inaturalist.org/photos/77/square.jpeg?1700000000",
            "https://inaturalist-open-data.s3.amazonaws.com/photos/77/medium.jpeg",
        ),
        ("https://example.org/photos/1/square.jpg", None),
        (None, None),
    ],
)
def test_medium_from_api_url(url, want):
    from logic import medium_from_api_url

    assert medium_from_api_url(url) == want


def test_queue_match_species_or_genus():
    from logic import queue_match

    by_group = {"Birds": {"Apis cerana", "Corvus splendens"}}
    genera = {"Birds": {"Apis", "Corvus"}}
    assert queue_match("Birds", "Corvus splendens", "species", by_group, genera, {}) == ("Corvus splendens", "species")
    assert queue_match("Birds", "Corvus splendens insolens", "subspecies", by_group, genera, {}) == (
        "Corvus splendens",
        "species",
    )
    assert queue_match("Birds", "Corvus", "genus", by_group, genera, {}) == ("Corvus", "genus")
    assert queue_match("Birds", "Pica", "genus", by_group, genera, {}) == (None, None)
    assert queue_match("Birds", "Corvus macro", "species", by_group, genera, {}) == (None, None)
    assert queue_match("Birds", "Corvidae", "family", by_group, genera, {}) == (None, None)


def test_recheck_outcome():
    from logic import recheck_outcome

    frozen = {
        "taxon_id": 10, "shown_species": "A b|A c", "set90": "A b|A c|D e", "top_names": "A c|A b|D e",
        "shown_genera": "A", "band": "Quick to confirm",
    }  # fmt: skip
    r = recheck_outcome(frozen, {"quality_grade": "research", "taxon_id": 11}, "A b")
    assert r == {
        "reached_rg": True, "changed_taxon": True, "final_species": "A b", "in_shown": True, "in_set90": True,
        "first": False, "in_top5": True, "genus_in_shown": True,
    }  # fmt: skip
    r = recheck_outcome(frozen, {"quality_grade": "needs_id", "taxon_id": 10}, None)
    assert r["reached_rg"] is False and r["changed_taxon"] is False and r["in_shown"] is None
    r = recheck_outcome(frozen, {"missing": True}, None)
    assert r["reached_rg"] is False and r["changed_taxon"] is None
    # research grade at a species that is not a candidate: counted, and a miss
    r = recheck_outcome(frozen, {"quality_grade": "research", "taxon_id": 99}, None)
    assert r["reached_rg"] is True and r["in_set90"] is False and r["first"] is False


# --- live shortlist files ---------------------------------------------------------------------------------


def live_obs(**kw):
    o = {
        "id": 5, "observed_on": "2026-09-30", "place_guess": "Kodagu, Karnataka", "obscured": False,
        "created_at": "2026-10-01T00:00:00+00:00", "taxon": {"name": "Halyomorpha", "rank": "genus"},
        "photos": [{"url": "https://inaturalist-open-data.s3.amazonaws.com/photos/1/square.jpg",
                    "attribution": "(c) name, some rights reserved (CC BY)", "license_code": "cc-by"}],
    }  # fmt: skip
    return {**o, **kw}


def test_public_row_quick_caps_and_fields():
    from logic import public_row

    r = public_row(live_obs(), "quick", ["A a", "A b", "A c", "A d"], ["A", "B", "C", "D", "E", "F"], state="29")
    assert list(r) == ["id", "url", "photo", "attribution", "licence", "observed", "place", "state", "now", "band",
                       "names", "genera"]  # fmt: skip
    assert r["url"] == "https://www.inaturalist.org/observations/5"
    assert r["photo"] == "https://inaturalist-open-data.s3.amazonaws.com/photos/1/medium.jpg"
    assert r["names"] == ["A a", "A b", "A c"] and r["genera"] == ["A", "B", "C", "D", "E"]
    assert r["now"] == {"name": "Halyomorpha", "rank": "genus"} and r["state"] == "29"


def test_public_row_genus_has_no_names_and_obscured_has_no_state():
    from logic import public_row

    r = public_row(live_obs(obscured=True), "genus", ["A a"], ["A"], state="29")
    assert r["names"] == [] and r["genera"] == ["A"] and r["state"] is None


def test_live_order_quick_first_then_oldest():
    from logic import live_order

    rows = [
        {"id": 3, "band": "genus", "created_at": "2026-08-01T00:00:00+00:00"},
        {"id": 2, "band": "quick", "created_at": "2026-09-01T00:00:00+00:00"},
        {"id": 1, "band": "quick", "created_at": "2026-07-01T00:00:00+00:00"},
        {"id": 4, "band": "quick", "created_at": "2026-07-01T00:00:00+00:00"},
    ]
    assert [r["id"] for r in live_order(rows)] == [1, 4, 2, 3]


def test_paginate_by_bytes():
    from logic import compact, paginate

    rows = [{"id": i, "pad": "x" * 50} for i in range(100)]
    pages = paginate(rows, lambda rs: compact({"rows": rs}), max_bytes=1000)
    assert sum(len(p) for p in pages) == 100 and [r["id"] for p in pages for r in p] == list(range(100))
    assert all(len(compact({"rows": p}).encode()) <= 1000 for p in pages)
    assert paginate([], lambda rs: compact({"rows": rs}), 1000) == [[]]


def test_compact_is_deterministic_and_unicode():
    from logic import compact

    assert compact({"a": "é", "b": [1, 2]}) == '{"a":"é","b":[1,2]}'


def test_done_ids_are_named_casual_or_gone():
    """A shown observation is done when iNaturalist now has it as research grade or casual, or no longer returns it."""
    answers = [{"id": 1, "quality_grade": "research"}, {"id": 2, "quality_grade": "needs_id"},
               {"id": 3, "quality_grade": "casual"}]
    assert done_ids(answers, shown=[1, 2, 3, 4]) == {1, 3, 4}
    assert done_ids([], shown=[]) == set()


def test_page_name_numbers_every_page_after_the_first():
    assert [page_name("true-bugs", n) for n in (1, 2, 3)] == ["true-bugs.json", "true-bugs.2.json", "true-bugs.3.json"]
