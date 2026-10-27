"""Shared helpers of the pipeline: streamed downloads, restore from R2, JSON output."""

import json
from pathlib import Path

import duckdb
import pytest
import requests

from pipeline import r2, util


class Response:
    def __init__(self, body, kind="application/pdf", cut=False):
        self.body, self.cut, self.headers = body, cut, {"Content-Type": kind}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield self.body[:2]
        if self.cut:
            raise requests.ConnectionError("cut")
        yield self.body[2:]


class Http:
    def __init__(self, response):
        self.response = response

    def get(self, url, **kw):
        return self.response


def test_stream_writes_the_file_only_when_complete(tmp_path):
    dest = tmp_path / "a" / "f.pdf"
    with pytest.raises(requests.ConnectionError):
        util.stream(Http(Response(b"abcdef", cut=True)), "u", dest)
    assert not dest.exists()
    assert util.stream(Http(Response(b"abcdef")), "u", dest) is True
    assert dest.read_bytes() == b"abcdef"


def test_stream_refuses_a_page_in_place_of_a_pdf(tmp_path):
    dest = tmp_path / "f.pdf"
    assert util.stream(Http(Response(b"<html>", kind="text/html")), "u", dest, kind="pdf") is False
    assert not dest.exists() and not list(tmp_path.iterdir())


def test_restore_takes_the_r2_copy_only_when_the_local_file_is_absent(tmp_path, monkeypatch):
    got = []

    class S3:
        def download_file(self, bucket, key, path):
            got.append(key)
            open(path, "w").write("from r2")

    monkeypatch.setattr(r2, "bucket", lambda: "b")
    monkeypatch.setattr(r2, "exists", lambda s3, key: key == "k")
    f = tmp_path / "x" / "f.json"
    assert r2.restore(None, "k", f) is False                      # no R2 client: nothing to do
    assert r2.restore(S3(), "other", f) is False                  # not in R2
    assert r2.restore(S3(), "k", f) is True and f.read_text() == "from r2"
    assert r2.restore(S3(), "k", f) is False and got == ["k"]     # already here: no second download


def test_dump_is_compact_and_keeps_unicode(tmp_path):
    util.dump({"a": "é"}, tmp_path / "d" / "x.json")
    assert (tmp_path / "d" / "x.json").read_text() == '{"a":"é"}'
    assert json.loads((tmp_path / "d" / "x.json").read_text()) == {"a": "é"}


def test_stream_refuses_an_answer_shorter_than_its_content_length(tmp_path):
    dest = tmp_path / "f.zip"
    short = Response(b"abcdef", kind="application/zip")
    short.headers["Content-Length"] = "10"
    with pytest.raises(IOError):
        util.stream(Http(short), "u", dest)
    assert not dest.exists()
    full = Response(b"abcdef", kind="application/zip")
    full.headers["Content-Length"] = "6"
    assert util.stream(Http(full), "u", dest) is True and dest.read_bytes() == b"abcdef"


def test_stream_does_not_compare_length_of_a_compressed_answer(tmp_path):
    gz = Response(b"abcdef", kind="application/json")
    gz.headers.update({"Content-Length": "4", "Content-Encoding": "gzip"})  # requests unpacks it: 6 bytes arrive
    assert util.stream(Http(gz), "u", tmp_path / "f.json") is True


def test_first_and_value_read_one_row_and_leave_the_connection_free():
    con = duckdb.connect()
    con.sql("CREATE TABLE t AS SELECT range AS a FROM range(5)")
    assert util.first(con, "SELECT count(*), max(a) FROM t") == (5, 4)
    assert util.first(con, "SELECT a FROM t WHERE a > ? ORDER BY a LIMIT 1", [2]) == (3,)
    assert util.first(con, "SELECT a FROM t WHERE a > 9") is None
    assert util.value(con, "SELECT sum(a) FROM t") == 10
    assert util.value(con, "SELECT a FROM t WHERE a > ?", [9]) is None
    assert util.value(duckdb, "SELECT 7") == 7          # the module's default connection, as described.py uses
    assert con.sql("SELECT 1").fetchall() == [(1,)]     # duckdb 2.0 refuses a new query while a result is unread


def test_no_code_calls_fetchone():
    """duckdb 2.0 has no fetchone() on relations, and after execute() it leaves the result unread. Use util.first."""
    root = Path(__file__).resolve().parent.parent
    bad = [f"{p.relative_to(root)}:{i}" for d in ("pipeline", "scripts", "tests") for p in (root / d).rglob("*.py")
           for i, line in enumerate(p.read_text().splitlines(), 1) if ".fetchone(" in line and p.name != "test_util.py"]
    assert bad == []


def test_period_is_the_monday_of_the_week_in_utc():
    from datetime import datetime, timezone
    assert util.period(datetime(2026, 10, 26, 0, 5, tzinfo=timezone.utc)) == "2026-10-26"   # a Monday
    assert util.period(datetime(2026, 11, 1, 23, 59, tzinfo=timezone.utc)) == "2026-10-26"  # the Sunday after
    assert util.period(datetime(2027, 1, 1, tzinfo=timezone.utc)) == "2026-12-28"           # a week across the year
    assert len(util.period()) == 10


def test_runs_and_layers_are_named_by_week(monkeypatch):
    """The monthly run became weekly (27 October 2026): a run id is the week's Monday, a test run adds the state."""
    from pipeline import run
    monkeypatch.setattr(run, "period", lambda: "2026-10-26")
    assert run.default_run_id() == "2026-10-26"
    assert run.default_run_id("Tamil Nadu") == "2026-10-26-tamil-nadu"


def test_a_built_run_records_its_summary_without_the_dropped_quiet_count(tmp_path, monkeypatch):
    """finish() keeps the run's main counts in runs/<id>.json; the summary no longer has quiet_species (the
    'no record since 1980' count was dropped), and a run must not fail on it after its files are built."""
    from pipeline import run
    monkeypatch.setattr(run, "RUNS", tmp_path)
    state = {"run_id": "2026-10-26", "status": "requested"}
    summary = {"species": 9, "records": 20, "districts": 3, "ledger_rows": 12, "built": "x"}
    manifest = {"downloads": [{"key": "k", "doi": "10.1/x"}]}
    run.finish(None, state, tmp_path, manifest, summary, "b", tmp_path / "b", publish=False)
    saved = json.loads((tmp_path / "2026-10-26.json").read_text())
    assert saved["status"] == "built" and saved["summary"] == {"species": 9, "records": 20, "districts": 3, "ledger_rows": 12}
