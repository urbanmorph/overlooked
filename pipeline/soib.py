"""State of India's Birds (SoIB 2023): which bird species of India have a known population trend. The Prestonian gap
(how many there are, and whether that changes) of Hortal et al. 2015, for birds.

Source: SoIB's main table (SoIB_main_2023.csv, about 1 MB) in the SoIB Partnership's repository on GitHub, MIT licence,
"Copyright (c) 2023 The SoIB Partnership". Cite: SoIB (2023). State of India's Birds, 2023: Range, trends, and
conservation status. The SoIB Partnership. doi:10.5281/zenodo.11124589. The 2025 and 2026 updates keep the 2023
trend categories.

A trend is known when the long-term or the current annual trend (SOIBv2 columns, the 2023 categories) is Rapid
Decline, Decline, Stable, Increase or Rapid Increase. "Trend Inconclusive" and "Insufficient Data" are assessed but not
known; a species not selected for SoIB is not assessed. Both names of a species count: the India Checklist name and
eBird's.

Kept in R2 cache/soib/ (never served); a run that cannot reach GitHub uses that copy.
"""

from pathlib import Path

from pipeline.util import log

URL = ("https://raw.githubusercontent.com/stateofindiasbirds/soib_2023/master/"
       "01_analyses_full/results/past/SoIB_main_2023.csv")
R2_KEY = "cache/soib/SoIB_main_2023.csv"
KNOWN = ("Rapid Decline", "Decline", "Stable", "Increase", "Rapid Increase")


def trends_sql(path):
    """SELECT name, assessed, known: one row per name of each species in the table."""
    return f"""
        WITH s AS (SELECT "eBird.Scientific.Name.2022" AS ebird, "India.Checklist.Scientific.Name" AS checklist,
                          coalesce("Selected.SOIB", '') = 'X' AS assessed,
                          "SOIBv2.Long.Term.Status" IN {KNOWN} OR "SOIBv2.Current.Status" IN {KNOWN} AS known
                   FROM read_csv('{path}', header = true, all_varchar = true))
        SELECT name, bool_or(assessed) AS assessed, bool_or(known) AS known FROM (
            SELECT checklist AS name, assessed, known FROM s UNION ALL SELECT ebird, assessed, known FROM s)
        WHERE coalesce(name, '') <> '' GROUP BY name"""


def refresh(http, s3, cache: Path):
    """The table, fetched from GitHub and kept in R2 (uploaded only when it changed). When GitHub cannot be reached:
    R2's copy. None when there is neither."""
    from pipeline import r2
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / Path(R2_KEY).name
    try:
        r = http.get(URL, timeout=120)
        r.raise_for_status()
        dest.write_bytes(r.content)
    except Exception as e:  # noqa: BLE001 - any failure: use the copy in R2
        log(f"SoIB: {URL} not reached ({e}); using the copy in R2")
        if not s3 or not r2.exists(s3, R2_KEY):
            return None
        s3.download_file(r2.bucket(), R2_KEY, str(dest))
        return dest
    if s3:
        r2.sync_file(s3, dest, R2_KEY, immutable=False)
    return dest
