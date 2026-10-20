"""Tests for the model-check scoring. Run: data/model_check/.venv/bin/python -m pytest experiments/model_check -q"""

import numpy as np
import pandas as pd
from scoring import accepted_from_match, score_probs, summarise


def test_score_probs_top1_genus_top5():
    cand = [
        "Apis cerana",
        "Apis dorsata",
        "Bombus haemorrhoidalis",
        "Xylocopa violacea",
        "Xylocopa latipes",
        "Vespa tropica",
    ]
    # Row 0: right species. Row 1: wrong species, right genus by summed genus probability.
    # Row 2: true species in the top five but not first.
    p = np.array(
        [
            [0.70, 0.10, 0.05, 0.05, 0.05, 0.05],
            [0.30, 0.00, 0.00, 0.35, 0.35, 0.00],
            [0.40, 0.20, 0.15, 0.10, 0.10, 0.05],
        ]
    )
    true_sp = ["Apis cerana", "Xylocopa latipes", "Xylocopa violacea"]
    out = score_probs(p, cand, true_sp, accepted=[None, None, None])
    assert list(out.pred_species) == ["Apis cerana", "Xylocopa violacea", "Apis cerana"]
    assert list(out.species_correct) == [True, False, False]
    assert list(out.genus_correct) == [True, True, False]
    assert list(out.species_in_top5) == [True, True, True]
    assert out.pred_prob.iloc[0] == 0.7


def test_synonym_match_uses_accepted_name():
    cand = ["Parmotrema tinctorum", "Usnea florida"]
    p = np.array([[0.9, 0.1]])
    out = score_probs(p, cand, ["Parmotrema tinctorium"], accepted=["Parmotrema tinctorum"])
    assert not out.species_correct.iloc[0]
    assert out.species_correct_syn.iloc[0]
    assert out.species_in_top5_syn.iloc[0]
    assert out.genus_correct_syn.iloc[0]


def test_accepted_from_match():
    syn = {"matchType": "EXACT", "rank": "SPECIES", "status": "SYNONYM", "species": "Dicranopteris linearis"}
    assert accepted_from_match(syn) == "Dicranopteris linearis"
    sub = {"matchType": "EXACT", "rank": "SUBSPECIES", "status": "ACCEPTED", "species": "Panthera tigris"}
    assert accepted_from_match(sub) == "Panthera tigris"
    assert accepted_from_match({"matchType": "HIGHERRANK", "rank": "GENUS", "genus": "Apis"}) is None
    assert accepted_from_match({"matchType": "NONE"}) is None


def test_summarise_per_group_and_overall():
    df = pd.DataFrame(
        {
            "group": ["A", "A", "B"],
            "true_in_candidates": [True, False, True],
            "true_in_candidates_syn": [True, True, True],
            "species_correct": [True, False, False],
            "species_correct_syn": [True, True, False],
            "genus_correct": [True, False, True],
            "genus_correct_syn": [True, True, True],
            "species_in_top5": [True, False, True],
            "species_in_top5_syn": [True, True, True],
        }
    )
    s = summarise(df).set_index("group")
    assert s.loc["A", "n"] == 2 and s.loc["A", "top1"] == 50.0 and s.loc["A", "top1_syn"] == 100.0
    assert s.loc["All", "n"] == 3 and s.loc["All", "top1"] == 33.3 and s.loc["All", "genus_syn"] == 100.0
    # top-1 among photos whose true species is a candidate: A has one such photo, right
    assert s.loc["A", "top1_in_cand"] == 100.0 and s.loc["All", "top1_in_cand"] == 50.0


def test_probe_folds_keep_observations_together_and_min_photos():
    from probe import folds

    df = pd.DataFrame(
        {"id": [1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], "true_species": ["A a"] * 6 + ["B b"] * 4 + ["C c"] * 2}
    )
    sub, splits = folds(df, min_photos=3, k=2)
    assert set(sub.true_species) == {"A a", "B b"}
    for tr, te in splits:
        assert not set(sub.id.iloc[tr]) & set(sub.id.iloc[te])
    assert sorted(np.concatenate([te for _, te in splits]).tolist()) == list(range(len(sub)))


def test_true_rank_and_recall_at_k():
    from scoring import shortlist_table, true_rank

    assert true_rank(np.array([0.5, 0.3, 0.2]), [1]) == 2
    assert true_rank(np.array([0.5, 0.3, 0.2]), [2, 0]) == 1  # best of several accepted names
    assert true_rank(np.array([0.5, 0.5]), []) == np.inf
    P = [np.array([0.6, 0.3, 0.1])] * 4
    T = [[0], [1], [2], []]
    t = shortlist_table(P, T, obs=[1, 2, 3, 4], groups=["A"] * 4, n_splits=2).set_index("group")
    assert t.loc["A", "r@1"] == 25.0 and t.loc["A", "r@3"] == 75.0 and t.loc["A", "r@20"] == 75.0
    # 90% can never be reached: one photo's species is not a candidate at all
    assert t.loc["A", "k90"] == "not reached" and t.loc["A", "conf90_cov"] == "not reached"


def test_fixed_k_and_conformal_reach_target():
    from scoring import shortlist_table

    rng = np.random.default_rng(0)
    P, T = [], []
    for i in range(400):
        p = rng.dirichlet(np.ones(30))
        true = int(np.argsort(-p)[i % 3])  # true species is always in the top 3
        P.append(p)
        T.append([true])
    t = shortlist_table(P, T, obs=list(range(400)), groups=["A"] * 400, n_splits=10).set_index("group")
    assert t.loc["A", "k90"] == 3 and t.loc["A", "k95"] == 3
    assert t.loc["A", "conf95_cov"] >= 93.0  # marginal coverage near the target on held-out halves
    assert t.loc["A", "conf95_median"] <= 30


def test_shortlist_inputs_genus_level():
    from scoring import shortlist_inputs

    cand = ["Apis cerana", "Apis dorsata", "Vespa tropica"]
    _p, T, Pg, Tg, gnames = shortlist_inputs(np.array([[0.2, 0.3, 0.5]]), cand, ["Apis florea"], [None])
    assert T == [[]] and list(gnames) == ["Apis", "Vespa"]
    assert np.allclose(Pg[0], [0.5, 0.5]) and Tg == [[0]]
