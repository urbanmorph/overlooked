"""Checklist papers read from one PDF into one table: the steps pipeline/lichens.py and pipeline/bryophytes.py share.

A checklist module gives URL, PDF, TABLE, R2_DIR (cache/<name>/, never served) and FIELDS, and parse(pdf),
check(rows) (a list of problems) and summary(rows) (a log line). The PDF comes from the local cache, else R2, else
the source; the table is written whole through a .part file. A second run with the same PDF downloads nothing and
uploads nothing.
"""

import argparse
import csv
from pathlib import Path

from pipeline import util
from pipeline.util import log

ROOT = Path(__file__).resolve().parent.parent


def write(rows, path, fields):
    """rows as CSV with these fields in this order (other keys left out), written whole or not at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows({k: r.get(k) for k in fields} for r in rows)
    tmp.replace(path)
    return path


def run(m, http, s3=None, cache=None):
    """Fetch (once), parse, check and keep the table of checklist module m; with s3, both files in R2."""
    from pipeline import r2
    name, cache = Path(m.__file__).stem, cache or m.CACHE
    pdf = r2.cached_file(s3, m.R2_DIR + m.PDF, cache / m.PDF, lambda d: util.stream(http, m.URL, d, kind="pdf"),
                         immutable=False)
    if pdf is None:
        raise SystemExit(f"{name}: {m.URL} did not answer with a PDF (a challenge page?); "
                         f"download it by hand to {cache / m.PDF}")
    rows = m.parse(pdf)
    problems = m.check(rows)
    if problems:
        raise SystemExit(f"{name}: the table did not read cleanly:\n  " + "\n  ".join(problems[:30]))
    table = write(rows, cache / m.TABLE, m.FIELDS)
    log(f"{name}: {m.summary(rows)}")
    if s3:
        r2.sync_file(s3, table, m.R2_DIR + m.TABLE, immutable=False)
    return table


def main(m):
    """The command line of checklist module m: [--publish] keeps the PDF and the table in R2."""
    from pipeline import health
    a = argparse.ArgumentParser()
    a.add_argument("--publish", action="store_true", help=f"keep the PDF and the table in R2 ({m.R2_DIR})")
    args = a.parse_args()
    s3 = None
    if args.publish:
        from dotenv import load_dotenv

        from pipeline import r2
        load_dotenv(ROOT / ".env", override=True)
        s3 = r2.client()
    run(m, health.session(), s3)
