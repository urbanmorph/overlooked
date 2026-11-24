"""Checklist papers read from one PDF into one table (pipeline/checklist.py): the steps lichens and bryophytes share."""

import ast
from pathlib import Path

import pytest

from pipeline import bryophytes, checklist, lichens
from tests.r2_fake import FakeS3
from tests.test_util import Response

ROOT = Path(__file__).resolve().parent.parent


def test_write_keeps_the_fields_in_order_and_only_them(tmp_path):
    t = checklist.write([{"b": 2, "a": 1, "extra": "x"}], tmp_path / "d" / "t.csv", ["a", "b"])
    assert t.read_text().splitlines() == ["a,b", "1,2"]
    assert not list((tmp_path / "d").glob("*.part"))


class Mod:
    """A checklist module: the names checklist.run reads."""
    __file__ = "pipeline/ferns.py"
    URL, PDF, TABLE, R2_DIR, FIELDS = "u", "ferns.pdf", "ferns.csv", "cache/ferns/", ["no", "name"]
    parse = staticmethod(lambda pdf: [{"no": 1, "name": "Aus bus"}])
    check = staticmethod(lambda rows: [])
    summary = staticmethod(lambda rows: f"{len(rows)} taxa")


class Http:
    def __init__(self, body=b"%PDF x", kind="application/pdf"):
        self.calls, self.body, self.kind = 0, body, kind

    def get(self, url, **kw):
        self.calls += 1
        return Response(self.body, self.kind)


def test_run_takes_the_pdf_from_r2_before_the_source_and_keeps_both_files(tmp_path, monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "b")
    s3, http = FakeS3(), Http()
    table = checklist.run(Mod, http, s3, tmp_path / "a")
    assert table.read_text().splitlines() == ["no,name", "1,Aus bus"] and http.calls == 1
    assert {"cache/ferns/ferns.pdf", "cache/ferns/ferns.csv"} <= set(s3.store)
    checklist.run(Mod, http, s3, tmp_path / "b")      # a new machine: the PDF comes from R2
    assert http.calls == 1


def test_run_stops_on_a_page_that_is_not_a_pdf_or_a_table_that_does_not_read(tmp_path):
    with pytest.raises(SystemExit, match="did not answer with a PDF"):
        checklist.run(Mod, Http(b"<html>", "text/html"), None, tmp_path)
    (tmp_path / "ferns.pdf").write_bytes(b"%PDF x")
    bad = type("Bad", (Mod,), {"check": staticmethod(lambda rows: ["row 2: no name"])})
    with pytest.raises(SystemExit, match="row 2: no name"):
        checklist.run(bad, Http(), None, tmp_path)


def test_lichens_and_bryophytes_keep_only_their_own_parsing():
    for m in (lichens, bryophytes):
        defs = {n.name for n in ast.parse(Path(m.__file__).read_text()).body if isinstance(n, ast.FunctionDef)}
        assert not defs & {"write", "main"}, m.__name__
        assert callable(m.summary)
