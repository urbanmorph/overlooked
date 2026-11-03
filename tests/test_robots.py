"""robots.txt: the open data under /data/ (named in llms.txt) is not closed to agents and crawlers."""

from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"


def test_data_is_not_disallowed():
    rules = [line.split(":", 1)[1].strip() for line in (SITE / "robots.txt").read_text().splitlines()
             if line.lower().startswith("disallow:")]
    assert not any("/data/".startswith(r) for r in rules if r)
    assert "/data/" in (SITE / "llms.txt").read_text()
