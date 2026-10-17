"""Cache, restart and idempotency of the extractors."""

import time

import pytest
import requests

from pipeline import gbif, inat, layer_newspecies as ns


class FakeResponse:
    def __init__(self, body=b"", data=None, fail_after=None):
        self.body, self.data, self.fail_after = body, data, fail_after
        self.status_code, self.headers = 200, {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def json(self):
        return self.data

    def iter_content(self, size):
        yield self.body[:3]
        if self.fail_after:
            raise requests.ConnectionError("cut")
        yield self.body[3:]


class FakeHttp:
    def __init__(self, response):
        self.response, self.calls = response, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.response


def test_cut_download_is_never_taken_as_finished(tmp_path, monkeypatch):
    monkeypatch.setattr(gbif, "RAW", tmp_path)
    meta = {"key": "k1", "downloadLink": "x", "doi": "d"}
    with pytest.raises(requests.ConnectionError):
        gbif.fetch(FakeHttp(FakeResponse(b"abcdef", fail_after=True)), meta)
    assert not (tmp_path / "k1.zip").exists()
    gbif.fetch(FakeHttp(FakeResponse(b"abcdef")), meta)
    assert (tmp_path / "k1.zip").read_bytes() == b"abcdef"


def test_inat_client_stops_at_time_limit_and_checkpoints(monkeypatch):
    monkeypatch.setattr(inat, "GAP", 0)
    saved = []
    c = inat.Client(budget=100, minutes=1, checkpoint=lambda cl: saved.append(cl.used))
    c.http = FakeHttp(FakeResponse(data={"ok": 1}))
    c.next_checkpoint = 0  # due now
    assert c.get("x") == {"ok": 1}
    assert saved == [0]
    c.deadline = time.monotonic() - 1
    with pytest.raises(inat.Budget, match="time limit"):
        c.get("x")


def test_plazi_skips_years_already_fetched(monkeypatch):
    monkeypatch.setattr(ns.time, "sleep", lambda s: None)
    this_year = ns.datetime.now(ns.timezone.utc).year
    done = {str(y): [] for y in range(ns.FIRST_YEAR, this_year)}
    done[str(ns.FIRST_YEAR)] = [{"name": "Aus bus", "year": ns.FIRST_YEAR}]
    saves = []
    row = {"TaxName": "Cus dus", "TaxStatus": "sp. nov.", "BibYear": str(this_year), "BibSource": "J",
           "MatCitRegion": "Kerala", "DocUuid": "u"}
    http = FakeHttp(FakeResponse(data={"data": [row]}))
    names = ns.plazi_names(http, done, lambda: saves.append(1))
    assert len(http.calls) == 1 and saves == [1]
    assert [n["name"] for n in names] == ["Aus bus", "Cus dus"]


def test_matching_stops_at_time_limit():
    state = {"names": [{"name": "Aus bus", "year": 2020}]}
    out = ns.match_all(None, None, state, {}, set(), {}, {}, time.monotonic() - 1, lambda: None)
    assert out is None


def test_inat_daily_budget_counts_earlier_runs_today(tmp_path, monkeypatch):
    from pipeline import layer_inat
    monkeypatch.setattr(inat, "CACHE", tmp_path)
    assert layer_inat.budget_left(9000, "2026-10-17") == 9000
    layer_inat.record_usage("2026-10-17", 7866)
    assert layer_inat.budget_left(9000, "2026-10-17") == 1134
    assert layer_inat.budget_left(9000, "2026-10-18") == 9000
    layer_inat.record_usage("2026-10-17", 2000)
    assert layer_inat.budget_left(9000, "2026-10-17") == 0
