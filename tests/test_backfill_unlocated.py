"""Backfill of query L (records with no coordinates) for a snapshot published before the query existed."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("backfill_unlocated",
                                              Path(__file__).resolve().parent.parent / "scripts" / "backfill_unlocated.py")
bu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bu)


def test_next_step_restarts_where_it_stopped():
    assert bu.next_step({}, published=True) == "done"                          # already in the snapshot
    assert bu.next_step({}, published=False) == "submit"
    assert bu.next_step({"key": "k", "status": "RUNNING"}, published=False) == "wait"
    assert bu.next_step({"key": "k", "status": "SUCCEEDED"}, published=False) == "build"
    assert bu.next_step({"key": "k", "status": "FAILED"}, published=False) == "submit"   # ask again
