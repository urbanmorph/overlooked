"""Shared helpers of the pipeline: streamed downloads, restore from R2, JSON output."""

import json

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
