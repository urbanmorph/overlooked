"""pipeline/store.py: an extractor's state, kept locally and in R2, saved every SAVE_EVERY seconds and on exit."""

import json

import pytest

from pipeline import store
from tests.r2_fake import FakeS3


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "b")
    return FakeS3()


def test_r2s_copy_wins_over_an_old_local_one(tmp_path, s3):
    """A snapshot (a week's counts, a sync cursor): R2's whole copy, never a mix of two weeks."""
    p = tmp_path / "counts.json"
    p.write_text('{"period": "old", "a": 1}')
    s3.store["cache/x/counts.json"] = b'{"period": "new", "b": 2}'
    assert store.Store(p, s3, "cache/x/counts.json").data == {"period": "new", "b": 2}
    assert store.Store(p).data == {"period": "old", "a": 1}                     # no R2: the local copy
    assert store.Store(tmp_path / "none.json", s3, "cache/x/none.json").data == {}


def test_answers_from_both_copies_are_kept_r2_winning_a_conflict(tmp_path, s3):
    """Answers that only grow (OCR pages, Wikidata answers): a laptop's and the CI's are merged, a section deep."""
    p = tmp_path / "s.json"
    p.write_text('{"pages": {"1": "local", "2": "local only"}, "v": 1}')
    s3.store["cache/s.json"] = b'{"pages": {"1": "r2", "3": "r2 only"}, "v": 2}'
    st = store.Store(p, s3, "cache/s.json", merge=True)
    assert st.data == {"pages": {"1": "r2", "2": "local only", "3": "r2 only"}, "v": 2}


def test_saved_through_a_part_file_to_both_places_when_due_and_on_exit(tmp_path, s3, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(store.time, "monotonic", lambda: clock[0])
    p = tmp_path / "s.json"
    with pytest.raises(RuntimeError), store.Store(p, s3, "cache/s.json") as st:
        st.data["a"] = 1
        st.maybe_save()                                   # not due: nothing written
        assert not p.exists() and not s3.uploads
        clock[0] += store.SAVE_EVERY + 1
        st.data["b"] = 2
        st.maybe_save()                                   # due: written and uploaded
        assert json.loads(p.read_text()) == {"a": 1, "b": 2} and s3.uploads == ["cache/s.json"]
        st.data["c"] = 3
        raise RuntimeError("the run fails")
    assert json.loads(p.read_text())["c"] == 3 and json.loads(s3.store["cache/s.json"])["c"] == 3   # saved on exit
    assert not list(tmp_path.glob("*.part"))


def test_an_unchanged_store_is_not_uploaded_again(tmp_path, s3):
    p = tmp_path / "s.json"
    with store.Store(p, s3, "cache/s.json") as st:
        st.data["a"] = 1
    with store.Store(p, s3, "cache/s.json"):
        pass
    assert s3.uploads == ["cache/s.json"]
