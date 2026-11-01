"""eBird's bird species with records from India: a current list, reviewed by eBird's regional editors, that has the
splits newer than the 2023 checklists (the Eastern cattle egret Ardea coromanda, the Eastern barn owl Tyto javanica).
pipeline/name_review.py uses it so such a species is not shown as a name to check.

Source: GBIF's eBird Observation Dataset (Cornell Lab of Ornithology, doi:10.15468/aomfnb, CC BY 4.0), one occurrence
search with a species facet, keyed by Catalogue of Life ID (GBIF's checklistKey for COL XR), as the master list is.
Only the species keys and record counts are kept, in R2 cache/ (never served); a run that cannot reach GBIF uses that
copy. One request a run, so no progress log.
"""

import json
from pathlib import Path

from pipeline.util import log

URL = "https://api.gbif.org/v1/occurrence/search"
EBIRD = "4fa7b334-ce0d-4e88-aaae-2e0c138d049e"
COL_XR = "7ddf754f-d193-4cc9-b351-99906754a03b"
FACET_LIMIT = 5000
MIN_RECORDS = 10      # fewer: a vagrant, an escape or an error
R2_KEY = "cache/ebird/india_species.json"


def refresh(http, s3, cache: Path):
    """{COL ID: records} for India, fetched from GBIF and kept in R2 (uploaded only when it changed). When GBIF cannot be
    reached, or the answer may be cut at the facet limit: R2's copy. None when there is neither."""
    from pipeline import r2
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / Path(R2_KEY).name
    params = {"checklistKey": COL_XR, "datasetKey": EBIRD, "country": "IN", "limit": 0, "facet": "speciesKey",
              "speciesKey.facetLimit": FACET_LIMIT}
    try:
        r = http.get(URL, params=params, timeout=300)
        r.raise_for_status()
        counts = {c["name"]: c["count"] for f in r.json()["facets"] for c in f["counts"]}
        if not counts or len(counts) >= FACET_LIMIT:
            raise ValueError(f"{len(counts)} species: empty or cut at the facet limit")
        dest.write_text(json.dumps(dict(sorted(counts.items())), separators=(",", ":")))
    except Exception as e:  # noqa: BLE001 - any failure: use the copy in R2
        log(f"eBird India: GBIF not used ({e}); using the copy in R2")
        if not s3 or not r2.exists(s3, R2_KEY):
            return None
        s3.download_file(r2.bucket(), R2_KEY, str(dest))
        return dest
    log(f"eBird India: {len(counts):,} species")
    if s3:
        r2.sync_file(s3, dest, R2_KEY, immutable=False)
    return dest


def keys(path, min_records=MIN_RECORDS):
    """The COL IDs with at least min_records records from India; empty when there is no list."""
    if not path:
        return set()
    return {k for k, n in json.loads(Path(path).read_text()).items() if n >= min_records}
