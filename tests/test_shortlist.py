"""Species shortlists for taxonomists: sets, bands, calibration file, site rows, and the score run."""

import json
import subprocess
import sys

import numpy as np
import pytest

from pipeline import shortlist as sl

NAMES = ["Papilio polytes", "Papilio demoleus", "Danaus chrysippus", "Danaus genutia", "Junonia almana"]


def entry(**kw):
    """A passed conformal group entry, as calibrate() writes it."""
    e = {
        "identifiable": True, "method": "conformal", "target": 0.9, "threshold": 0.2, "k": 2,
        "genus_threshold": 0.3, "coverage": 0.91, "median_size": 1, "p90_size": 3, "n": 200,
        "measured_on": "test", "max_size": 3, "max_genera": 5, "input": "probs", "temperature": 1.0,
        "model_id": "bioclip-2.5", "corpus_version": "v0", "date": "2026-10-20", "passed": True, "reason": None,
    }
    e.update(kw)
    return e


def heldout(n=200, c=5, hit=0.95, seed=0):
    """Held-out probabilities where the true class gets most of the mass in a share `hit` of rows."""
    rng = np.random.default_rng(seed)
    true_idx = rng.integers(0, c, n)
    p = rng.random((n, c)) * 0.1
    for i, t in enumerate(true_idx):
        p[i, t if rng.random() < hit else (t + 1) % c] += 1.0
    p /= p.sum(axis=1, keepdims=True)
    return p, [NAMES[t] for t in true_idx]


# --- probabilities ---

def test_softmax_rows_sum_to_one_and_temperature_flattens():
    s = np.array([[2.0, 1.0, 0.0]])
    p1, p5 = sl.softmax(s), sl.softmax(s, temperature=5.0)
    assert np.allclose(p1.sum(axis=1), 1) and np.allclose(p5.sum(axis=1), 1)
    assert p5[0, 0] < p1[0, 0]
    assert np.allclose(sl.softmax(np.array([1000.0, 0.0])), [1.0, 0.0])  # no overflow


def test_to_probs_uses_entry_input_kind():
    s = np.array([2.0, 1.0, 0.0])
    assert np.allclose(sl.to_probs(s, {"input": "logits", "temperature": 1.0}), sl.softmax(s))
    p = np.array([0.6, 0.3, 0.1])
    assert np.allclose(sl.to_probs(p, {"input": "probs", "temperature": 1.0}), p)


def test_genus_probs_sum_by_genus_in_first_seen_order():
    genera, gp = sl.genus_probs(np.array([0.1, 0.2, 0.3, 0.3, 0.1]), NAMES)
    assert genera == ["Papilio", "Danaus", "Junonia"]
    assert np.allclose(gp, [0.3, 0.6, 0.1])


# --- sets ---

def test_conformal_threshold_is_the_kth_largest_true_probability():
    p_true = np.linspace(0.01, 1.0, 100)  # n = 100, target 0.9: k = ceil(101 * 0.9) = 91
    thr = sl.conformal_threshold(p_true, 0.9)
    assert thr == pytest.approx(np.sort(p_true)[::-1][90])
    assert (p_true >= thr).mean() >= 0.9


def test_conformal_threshold_unreachable_target_takes_every_candidate():
    assert sl.conformal_threshold(np.array([0.5, 0.4, 0.3]), 0.9) == 0.0  # ceil(4 * 0.9) = 4 > 3


def test_fixed_k_is_the_rank_that_covers_the_target():
    ranks = np.array([1] * 80 + [2] * 15 + [np.inf] * 5)
    assert sl.fixed_k(ranks, 0.9) == 2
    assert sl.fixed_k(ranks, 0.99) is None  # the right name is not a candidate for 5%


def test_prediction_set_is_ordered_and_keeps_ties():
    p = np.array([0.1, 0.4, 0.2, 0.2, 0.1])
    assert sl.prediction_set(p, threshold=0.2) == [1, 2, 3]
    assert sl.prediction_set(p, k=2) == [1, 2]


# --- bands ---

def test_quick_to_confirm_when_group_passed_and_set_is_short():
    out = sl.shortlist(np.array([0.7, 0.2, 0.05, 0.03, 0.02]), NAMES, entry())
    assert out["band"] == sl.QUICK
    assert out["species"] == ["Papilio polytes", "Papilio demoleus"]
    assert out["genera"] == ["Papilio"]


def test_long_set_goes_to_an_expert_with_genera_only():
    out = sl.shortlist(np.array([0.21, 0.2, 0.2, 0.2, 0.19]), NAMES, entry(threshold=0.15, genus_threshold=0.35))
    assert out["band"] == sl.EXPERT
    assert out["species"] == []
    assert out["genera"] == ["Papilio", "Danaus"]


def test_empty_set_goes_to_an_expert():
    out = sl.shortlist(np.array([0.2] * 5), NAMES, entry(threshold=0.5))
    assert out["band"] == sl.EXPERT and out["species"] == []


def test_group_that_failed_goes_to_an_expert():
    out = sl.shortlist(np.array([0.9, 0.05, 0.03, 0.01, 0.01]), NAMES, entry(passed=False))
    assert out["band"] == sl.EXPERT and out["species"] == [] and out["genera"] == ["Papilio"]


def test_no_calibration_goes_to_an_expert_with_no_names():
    out = sl.shortlist(np.array([0.9, 0.05, 0.03, 0.01, 0.01]), NAMES, None)
    assert out == {"band": sl.EXPERT, "species": [], "genera": []}


def test_not_identifiable_from_a_photo_needs_a_specimen():
    out = sl.shortlist(np.array([0.9, 0.05, 0.03, 0.01, 0.01]), NAMES, sl.specimen_entry("genitalia needed"))
    assert out == {"band": sl.SPECIMEN, "species": [], "genera": []}


def test_too_many_genera_shows_group_only():
    out = sl.shortlist(np.array([0.2] * 5), NAMES, entry(threshold=0.5, genus_threshold=0.1, max_genera=2))
    assert out["genera"] == []


def test_fixed_k_method_uses_k():
    out = sl.shortlist(np.array([0.3, 0.25, 0.2, 0.15, 0.1]), NAMES, entry(method="fixed_k", threshold=None, k=3))
    assert out["band"] == sl.QUICK and len(out["species"]) == 3


def test_logits_input_is_turned_into_probabilities():
    out = sl.shortlist(np.array([5.0, 0.0, 0.0, 0.0, 0.0]), NAMES, entry(input="logits", threshold=0.5))
    assert out["species"] == ["Papilio polytes"]


def test_scores_must_match_names():
    with pytest.raises(ValueError):
        sl.shortlist(np.array([0.5, 0.5]), NAMES, entry())


# --- calibration ---

def test_calibrate_passes_a_strong_group():
    p, true = heldout(hit=0.97)
    e = sl.calibrate(p, NAMES, true, model_id="m", corpus_version="v0", date="2026-10-20")
    assert e["passed"] and e["method"] == "conformal" and e["n"] == 200
    assert e["coverage"] >= 0.9 and e["median_size"] <= 3
    assert 0 < e["threshold"] <= 1 and e["genus_threshold"] is not None
    assert e["measured_on"] == "calibration"


def test_calibrate_fails_a_weak_group_with_a_reason():
    p, true = heldout(hit=0.3, c=5)
    e = sl.calibrate(p, NAMES, true, max_size=1, model_id="m", corpus_version="v0", date="2026-10-20")
    assert not e["passed"] and "median" in e["reason"]


def test_calibrate_counts_names_outside_the_candidates_as_misses():
    p, true = heldout(hit=1.0)
    true = ["Not a candidate"] * 30 + true[30:]  # 15% unreachable: 90% cannot be met with a short set
    e = sl.calibrate(p, NAMES, true, model_id="m", corpus_version="v0", date="2026-10-20")
    assert e["threshold"] == 0.0 and not e["passed"]


def test_calibrate_measures_on_a_test_split_when_given():
    p, true = heldout(n=300)
    e = sl.calibrate(p[:200], NAMES, true[:200], test=(p[200:], true[200:]),
                     model_id="m", corpus_version="v0", date="2026-10-20")
    assert e["measured_on"] == "test" and e["n"] == 200 and e["n_test"] == 100


def test_calibrate_fixed_k():
    p, true = heldout(hit=0.97)
    e = sl.calibrate(p, NAMES, true, method="fixed_k", model_id="m", corpus_version="v0", date="2026-10-20")
    assert e["method"] == "fixed_k" and e["threshold"] is None and e["k"] >= 1 and e["passed"]


def test_calibrate_refuses_a_small_set():
    p, true = heldout(n=99)
    with pytest.raises(sl.CalibrationTooSmall, match="99"):
        sl.calibrate(p, NAMES, true, model_id="m", corpus_version="v0", date="2026-10-20")


def test_calibrate_groups_reports_refused_groups():
    big, small = heldout(n=200), heldout(n=50)
    groups, refused = sl.calibrate_groups(
        {"Butterflies": (big[0], NAMES, big[1]), "Moths": (small[0], NAMES, small[1])},
        model_id="m", corpus_version="v0", date="2026-10-20")
    assert list(groups) == ["Butterflies"]
    assert "Moths" in refused and "50" in refused["Moths"]


def test_calibration_file_round_trip_and_version_is_stable(tmp_path):
    p, true = heldout()
    groups = {"Butterflies": sl.calibrate(p, NAMES, true, model_id="m", corpus_version="v0", date="2026-10-20"),
              "Insects: true bugs": sl.specimen_entry("needs a specimen")}
    doc = sl.make_calibration(groups, created="2026-10-20T00:00:00Z")
    assert doc["format"] == sl.FORMAT and doc["version"] == sl.FORMAT_VERSION
    assert doc["calibration_version"] == sl.make_calibration(groups, created="2027-01-01T00:00:00Z")["calibration_version"]
    path = tmp_path / "cal.json"
    sl.save_calibration(doc, path)
    assert sl.load_calibration(path) == doc


@pytest.mark.parametrize("change", [
    lambda d: d.update(version=99),
    lambda d: d.update(format="other"),
    lambda d: d["groups"]["G"].update(method="magic"),
    lambda d: d["groups"]["G"].update(target=1.5),
    lambda d: d["groups"]["G"].update(threshold=None),
    lambda d: d["groups"]["G"].update(n=10),
    lambda d: d["groups"]["G"].update(passed="yes"),
    lambda d: d["groups"]["G"].update(median_size=9),  # passed with a long median set
    lambda d: d["groups"]["G"].pop("model_id"),
    lambda d: d["groups"]["G"].update(input="raw"),
    lambda d: d["groups"]["G"].update(temperature=0),
])
def test_validate_rejects_bad_files(change):
    doc = sl.make_calibration({"G": entry()})
    change(doc)
    with pytest.raises(sl.CalibrationError):
        sl.validate(doc)


# --- site rows and value ---

def test_row_has_bands_and_names_only():
    out = sl.shortlist(np.array([0.7, 0.2, 0.05, 0.03, 0.02]), NAMES, entry())
    r = sl.row(123, "Butterflies", "Kerala", out, entry(), "abc123", flags={"endemic": True})
    assert r == {
        "obs": 123, "group": "Butterflies", "state": "Kerala", "band": sl.QUICK,
        "shortlist": [{"rank": 1, "name": "Papilio polytes"}, {"rank": 2, "name": "Papilio demoleus"}],
        "genera": [{"rank": 1, "name": "Papilio"}],
        "model": "bioclip-2.5", "calibration": "abc123", "value": sl.value({"endemic": True}),
    }
    assert "0.7" not in json.dumps(r)


def test_value_orders_by_flags():
    assert sl.value({}) == 1
    first, threatened, endemic, listed = (sl.value({f: True}) for f in sl.VALUE_FLAGS)
    assert first > threatened > endemic > listed > 1
    assert sl.value({"threatened": True, "endemic": True}) > threatened
    with pytest.raises(ValueError):
        sl.value({"famous": True})


def test_priority_is_value_times_ease():
    assert sl.priority(5, sl.QUICK) > sl.priority(5, sl.EXPERT) > sl.priority(5, sl.SPECIMEN)
    assert sl.priority(9, sl.EXPERT) == 9 * sl.EASE[sl.EXPERT]


# --- score run: cache, restart, idempotency ---

def write_shard(path, group, scores, model="bioclip-2.5", **extra):
    n = len(scores)
    np.savez(path, group=np.array(group), model=np.array(model), names=np.array(NAMES),
             obs_id=np.arange(n) + 1000, state=np.array(["Kerala"] * n), scores=scores, **extra)


@pytest.fixture
def run_dir(tmp_path):
    feats, out = tmp_path / "feats", tmp_path / "out"
    feats.mkdir()
    rng = np.random.default_rng(1)
    s = rng.random((4, 5))
    s[:, 0] += 3
    write_shard(feats / "a.npz", "Butterflies", s / s.sum(axis=1, keepdims=True),
                endemic=np.array([True, False, False, False]))
    write_shard(feats / "b.npz", "Moths", rng.random((3, 5)))
    cal = tmp_path / "cal.json"
    sl.save_calibration(sl.make_calibration({"Butterflies": entry()}), cal)
    return feats, cal, out


def test_score_writes_rows_per_shard(run_dir):
    feats, cal, out = run_dir
    stats = sl.score(feats, cal, out)
    assert stats == {"done": 2, "skipped": 0, "rows": 7}
    a = json.loads((out / "a.json").read_text())
    assert len(a) == 4 and all(r["band"] == sl.QUICK for r in a)
    assert a[0]["value"] > a[1]["value"]  # endemic flag
    b = json.loads((out / "b.json").read_text())
    assert all(r["band"] == sl.EXPERT and r["shortlist"] == [] for r in b)  # Moths: no calibration
    manifest = json.loads((out / "manifest.json").read_text())
    assert set(manifest["shards"]) == {"a.npz", "b.npz"}


def test_score_second_run_does_no_work(run_dir):
    feats, cal, out = run_dir
    sl.score(feats, cal, out)
    before = {p.name: p.stat().st_mtime_ns for p in out.iterdir()}
    assert sl.score(feats, cal, out) == {"done": 0, "skipped": 2, "rows": 0}
    assert {p.name: p.stat().st_mtime_ns for p in out.iterdir()} == before


def test_score_redoes_a_changed_shard_or_calibration(run_dir):
    feats, cal, out = run_dir
    sl.score(feats, cal, out)
    write_shard(feats / "b.npz", "Moths", np.random.default_rng(2).random((2, 5)))
    assert sl.score(feats, cal, out)["done"] == 1
    sl.save_calibration(sl.make_calibration({"Butterflies": entry(), "Moths": entry()}), cal)
    assert sl.score(feats, cal, out)["done"] == 2


def test_score_redoes_a_shard_whose_output_was_lost(run_dir):
    feats, cal, out = run_dir
    sl.score(feats, cal, out)
    (out / "a.json").write_text("[]")
    assert sl.score(feats, cal, out)["done"] == 1


def test_score_stops_at_the_time_limit_and_continues(run_dir, monkeypatch):
    feats, cal, out = run_dir
    calls = []  # the run reads the clock at its start and before each shard: the second shard is past the limit
    monkeypatch.setattr(sl.time, "monotonic", lambda: calls.append(1) or (0.0 if len(calls) <= 2 else 10_000.0))
    assert sl.score(feats, cal, out, minutes=1)["done"] == 1
    monkeypatch.undo()
    assert sl.score(feats, cal, out) == {"done": 1, "skipped": 1, "rows": 3}


def test_score_refuses_scores_from_another_model(run_dir):
    feats, cal, out = run_dir
    write_shard(feats / "a.npz", "Butterflies", np.full((2, 5), 0.2), model="other-model")
    with pytest.raises(ValueError, match="other-model"):
        sl.score(feats, cal, out)


def test_score_from_features_and_a_linear_head(tmp_path):
    feats, heads, out = tmp_path / "feats", tmp_path / "heads", tmp_path / "out"
    feats.mkdir(), heads.mkdir()
    x = np.eye(5)[[0, 0, 1]]
    np.savez(feats / "a.npz", group=np.array("Butterflies"), model=np.array("bioclip-2.5"), names=np.array(NAMES),
             obs_id=np.array([1, 2, 3]), state=np.array(["Goa"] * 3), feats=x)
    np.savez(heads / f"{sl.slug('Butterflies')}.npz", names=np.array(NAMES), weights=np.eye(5), scale=np.array(20.0))
    cal = tmp_path / "cal.json"
    sl.save_calibration(sl.make_calibration({"Butterflies": entry(input="logits", threshold=0.5)}), cal)
    sl.score(feats, cal, out, heads=heads)
    rows = json.loads((out / "a.json").read_text())
    assert [r["shortlist"][0]["name"] for r in rows] == ["Papilio polytes", "Papilio polytes", "Papilio demoleus"]


def test_import_needs_no_ml_libraries():
    code = "import sys, pipeline.shortlist; bad = {'torch', 'open_clip', 'pandas', 'sklearn'} & set(sys.modules); print(bad)"
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip() == "set()"


def test_calibrate_command_writes_a_valid_file(tmp_path):
    held = tmp_path / "held"
    held.mkdir()
    p, true = heldout()
    np.savez(held / "b.npz", group=np.array("Butterflies"), names=np.array(NAMES), scores=p, true=np.array(true))
    out = tmp_path / "cal.json"
    sl.main(["calibrate", "--heldout", str(held), "--model", "m", "--corpus", "v0", "--out", str(out),
             "--not-identifiable", "Insects: true bugs"])
    doc = sl.load_calibration(out)
    assert doc["groups"]["Butterflies"]["passed"]
    assert doc["groups"]["Insects: true bugs"]["identifiable"] is False
