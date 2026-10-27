"""Records that cannot be placed in a district (query L): no coordinates, flagged or too coarse coordinates.
Placed in states by the state text as published.

A record is placed in an LGD state when its stateprovince text names exactly one state or union
territory (pipeline/ref/state_names.csv: official names, old names, common spellings). Cities
(Bombay, Madras), historic regions that span states (Bengal, United Provinces) and text naming two
states stay unplaced: "no place".

Creates table unlocated: species_key, name, genus, taxonrank, grp, stateprovince, state_lgd,
datasetkey, basis, problem, first_year, last_year, n_records.
"""

import csv
import json
import re
import time
import unicodedata
from pathlib import Path

import requests

from pipeline.groups import GROUP_SQL
from pipeline.unresolved import read_tsv
from pipeline.util import value

ROOT = Path(__file__).resolve().parent.parent
STATE_NAMES = ROOT / "pipeline" / "ref" / "state_names.csv"
# State text that names a place outside India: GBIF has the record as India, but it is not (pipeline/ref).
FOREIGN = ROOT / "pipeline" / "ref" / "foreign_places.csv"
TITLE_CACHE = ROOT / "data" / "cache" / "gbif_datasets.json"
TITLE_KEY = "cache/gbif_datasets.json"

TYPES = {"specieskey": "VARCHAR", "species": "VARCHAR", "genus": "VARCHAR", "taxonrank": "VARCHAR",
         "kingdom": "VARCHAR", "phylum": "VARCHAR", "class": "VARCHAR", "order": "VARCHAR", "family": "VARCHAR",
         "stateprovince": "VARCHAR", "datasetkey": "VARCHAR", "basisofrecord": "VARCHAR", "problem": "VARCHAR",
         "first_year": "INTEGER", "last_year": "INTEGER", "n_records": "BIGINT"}

# Words around a state name that do not change it: "State of Kerala", "Andaman Is.", "Puducherry UT".
PREFIX = re.compile(r"^(?:(?:the|state of|union territory of|ut of|nct of|etat du|etat de|estado de) )+")
SUFFIX = re.compile(r"(?: (?:state of|state|union territory|ut|territory|islands|island|is|ids|isl))+$")


def words(text):
    """Lower case, accents and punctuation removed, '&' read as 'and'."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower().replace("&", " and ")).split())


def key(text):
    """Letters only, so 'Tamil Nadu', 'TamilNadu' and 'Tamil-Nadu' are one name."""
    return words(text).replace(" ", "")


def load_state_names(path=STATE_NAMES):
    return {key(r["name"]): int(r["state_lgd"]) for r in csv.DictReader(path.open(encoding="utf-8"))}


def state_of(text, names):
    """LGD state code for a stateprovince text, or None. Tries each part (split on , ; / and brackets),
    with and without words such as 'State of'. Text that names two different states stays unplaced."""
    if not text:
        return None
    inner = re.findall(r"[(\[](.*?)[)\]]", text)
    outer = re.sub(r"[(\[].*?[)\]]", " ", text)
    found = set()
    for part in (p for chunk in (outer, *inner) for p in re.split(r"[,;/]", chunk)):
        w = words(part)
        for k in (w, SUFFIX.sub("", PREFIX.sub("", w))):
            if k.replace(" ", "") in names:
                found.add(names[k.replace(" ", "")])
    return found.pop() if len(found) == 1 else None


def foreign_places(path=FOREIGN):
    """State texts (lower case, trimmed) that name a place outside India."""
    return {r["place"].strip().lower() for r in csv.DictReader(path.open())}


def build(con, tsv, names_path=STATE_NAMES):
    """Load a query L download and place it in states, without records whose state text names a place outside
    India. Returns the number of records."""
    read_tsv(con, "lcube", tsv, TYPES)
    con.execute("DELETE FROM lcube WHERE list_contains($1, lower(trim(stateprovince)))", [sorted(foreign_places())])
    # Merged duplicate keys (names.merge_duplicates), when that step has run.
    if value(con, "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'key_map'"):
        con.sql("UPDATE lcube SET specieskey = m.canonical FROM key_map m WHERE lcube.specieskey = m.species_key")
    names = load_state_names(names_path)
    texts = [r[0] for r in con.sql("SELECT DISTINCT stateprovince FROM lcube WHERE stateprovince IS NOT NULL").fetchall()]
    con.execute("CREATE OR REPLACE TABLE state_map AS SELECT unnest($1) AS stateprovince, unnest($2)::INTEGER AS state_lgd",
                [texts, [state_of(t, names) for t in texts]])
    con.sql(f"""
        CREATE OR REPLACE TABLE unlocated AS
        SELECT l.specieskey AS species_key, any_value(l.species) AS name, l.genus, lower(l.taxonrank) AS taxonrank,
               {GROUP_SQL} AS grp, l.stateprovince, m.state_lgd, l.datasetkey, l.basisofrecord AS basis,
               coalesce(l.problem, 'none') AS problem,
               min(l.first_year) AS first_year, max(l.last_year) AS last_year, sum(l.n_records) AS n_records
        FROM lcube l LEFT JOIN state_map m USING (stateprovince)
        GROUP BY species_key, l.genus, taxonrank, grp, l.stateprovince, m.state_lgd, l.datasetkey, basis, problem
        ORDER BY state_lgd NULLS LAST, grp, species_key, datasetkey
    """)
    return value(con, "SELECT coalesce(sum(n_records), 0) FROM unlocated")


def dataset_titles(http, keys, cache=TITLE_CACHE, s3=None, gap=1.0):
    """Titles of GBIF datasets, from the GBIF API, one request at a time. Kept in data/cache and in R2
    cache/, so each dataset is asked once. A failed lookup gives None and is tried again next time."""
    from pipeline import r2
    titles = (r2.get_json(s3, TITLE_KEY) or {}) if s3 else {}
    if cache.exists():
        titles.update(json.loads(cache.read_text()))
    missing = [k for k in dict.fromkeys(keys) if k not in titles]
    try:
        for k in missing:
            try:
                r = http.get(f"https://api.gbif.org/v1/dataset/{k}", timeout=30)
                r.raise_for_status()
                titles[k] = r.json().get("title")
            except (requests.RequestException, ValueError):
                pass
            time.sleep(gap)
    finally:
        if missing:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(titles, indent=0, ensure_ascii=False))
            if s3:
                r2.put_json(s3, titles, TITLE_KEY)
    return {k: titles.get(k) for k in keys}
