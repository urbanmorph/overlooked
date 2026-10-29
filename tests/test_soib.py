"""State of India's Birds (pipeline/soib.py): which bird species have a known population trend (the Prestonian gap),
and the copy kept in R2's cache."""

import duckdb

from pipeline import soib

HEADER = ["eBird.Scientific.Name.2022", "India.Checklist.Scientific.Name", "Selected.SOIB", "SOIB.Long.Term.Status",
          "SOIBv2.Long.Term.Status", "SOIBv2.Current.Status"]


def csv(path, rows):
    path.write_text("\n".join(",".join(r) for r in [HEADER, *rows]) + "\n")
    return path


def test_a_trend_is_known_when_either_trend_has_a_direction_or_is_stable(tmp_path):
    path = csv(tmp_path / "s.csv", [
        ["Aus bus", "Aus bus", "X", "Stable", "Rapid Decline", "Trend Inconclusive"],   # long-term known
        ["Cus dus", "Cus duus", "X", "Uncertain", "Insufficient Data", "Stable"],        # current known
        ["Eus fus", "Eus fus", "X", "Data Deficient", "Trend Inconclusive", "Insufficient Data"],
        ["Gus hus", "Gus hus", "", "NA", "NA", "NA"],                                    # not selected
    ])
    rows = {n: (a, k) for n, a, k in duckdb.sql(soib.trends_sql(path)).fetchall()}
    assert rows["Aus bus"] == (True, True)
    assert rows["Cus duus"] == (True, True) and rows["Cus dus"] == (True, True)      # both names of a species
    assert rows["Eus fus"] == (True, False)                                          # assessed, no known trend
    assert rows["Gus hus"] == (False, False)


class Http:
    def __init__(self, body=b"", fail=False):
        self.body, self.fail, self.calls = body, fail, 0

    def get(self, url, **kw):
        self.calls += 1
        if self.fail:
            raise ConnectionError("down")
        return type("R", (), {"content": self.body, "raise_for_status": lambda self: None})()


def test_refresh_keeps_a_copy_in_r2_and_falls_back_to_it(tmp_path, monkeypatch):
    from tests.r2_fake import FakeS3
    monkeypatch.setenv("R2_BUCKET", "b")
    s3, body = FakeS3(), b"a,b\n1,2\n"
    path = soib.refresh(Http(body), s3, tmp_path / "one")
    assert path.read_bytes() == body and list(s3.store) == [soib.R2_KEY]
    assert soib.refresh(Http(body), s3, tmp_path / "two").read_bytes() == body and s3.writes.count(soib.R2_KEY) <= 1
    assert soib.refresh(Http(fail=True), s3, tmp_path / "three").read_bytes() == body     # GitHub down: R2's copy
    assert soib.refresh(Http(fail=True), None, tmp_path / "four") is None                  # nothing to fall back to
