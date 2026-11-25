"""English names of reptiles from The Reptile Database (Uetz, P. & Hošek, J. (2026), The Reptile Database,
doi:10.48580/d37s), the copy its editors publish on ChecklistBank (dataset 1008) under CC BY 4.0.

The master list takes a reptile's English name from iNaturalist first (the pictures table); this fills only the
species iNaturalist has none for (254 of 361 such reptiles of India on 25 Nov 2026, Ophiophagus kaalinga among them).

One English name per accepted species, under its own name: the first listed with no brackets, else the first whose
brackets hold a second name ("Ladder Keelback (Hoge's Keelback)" is Ladder Keelback). A name with a subspecies in
square brackets ("Mirza's Pipe-Snake [mirzae]") or a lowercase epithet in brackets ("(leptieni)") is a subspecies'
name and never the species'.

Each run asks ChecklistBank for the dataset's version (one small request) and downloads the export (about 25 MB)
only when the version is new: two or three times a year. Kept in R2 cache/master/reptiledb_english.parquet; a run
that cannot reach ChecklistBank uses that copy, else the last local one.
"""

import csv
import io
import re
import zipfile
from pathlib import Path

import duckdb

from pipeline.util import log

DATASET_API = "https://api.checklistbank.org/dataset/1008"
EXPORT = DATASET_API + "/export.zip"
R2_KEY = "cache/master/reptiledb_english.parquet"

SUBSPECIES = re.compile(r"\[|\(\s*(?:[a-z]+|[A-Z]\.[^)]*)\s*\)|also general")   # [mirzae], (leptieni), (C. c. x)
BRACKETS = re.compile(r"\s*\([^)]*\)\s*")
QUOTES = "\"“”‘’'"
BROKEN = re.compile(r"[()\[\]“”\";]")   # left after cleaning: a name cut short or run into a note


def clean(name):
    """The species' name from one listed English name, or None when it is a subspecies' or a note."""
    if SUBSPECIES.search(name):
        return None
    name = " ".join(BRACKETS.sub(" ", name).split()).strip(QUOTES + " ")
    return name if name and not BROKEN.search(name) else None


def english(zip_bytes):
    """{accepted species name: English name} from a ColDP export."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        read = lambda f: csv.DictReader(io.TextIOWrapper(z.open(f), "utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)
        species = {r["col:ID"]: r["col:scientificName"] for r in read("NameUsage.tsv")
                   if r["col:status"] == "accepted" and r["col:rank"] == "species"}
        listed = {}
        for r in read("VernacularName.tsv"):
            if r["col:language"] == "eng" and r["col:taxonID"] in species:
                listed.setdefault(species[r["col:taxonID"]], []).append(r["col:name"])
    out = {}
    for name, names in listed.items():
        plain = [n.strip(QUOTES + " ") for n in names if not re.search(r"[(\[]", n)]
        plain = [n for n in plain if n and not BROKEN.search(n)]
        best = plain[0] if plain else next(filter(None, map(clean, names)), None)
        if best:
            out[name] = best
    return out


def version_of(path):
    try:
        got = duckdb.sql(f"SELECT any_value(version) FROM '{path}'").fetchall()
        return got[0][0] if got else None
    except duckdb.Error:
        return None


def refresh(http, s3, cache: Path):
    """The names table (name, english, version). When ChecklistBank cannot be reached: R2's copy, else the last local
    one. None when there is neither."""
    from pipeline import r2
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / Path(R2_KEY).name
    try:
        r = http.get(DATASET_API, timeout=60)
        r.raise_for_status()
        version = r.json()["version"]
        if s3 and not dest.exists():
            r2.fetch(s3, R2_KEY, dest)
        if dest.exists() and version_of(dest) == version:
            return dest
        r = http.get(EXPORT, params={"format": "ColDP", "extended": "true"}, timeout=600)
        r.raise_for_status()
        got = english(r.content)
    except Exception as e:  # noqa: BLE001 - any failure: use the copy kept before
        log(f"Reptile Database: ChecklistBank not reached ({e}); using the copy kept before")
        return r2.fetch(s3, R2_KEY, dest) if s3 else (dest if dest.exists() else None)
    part = dest.with_suffix(".part")
    duckdb.execute(f"""COPY (SELECT unnest(?::VARCHAR[]) AS name, unnest(?::VARCHAR[]) AS english, ?::VARCHAR AS version
                            ORDER BY 1) TO '{part}' (FORMAT parquet)""", [list(got), list(got.values()), version])
    part.replace(dest)
    log(f"Reptile Database {version}: {len(got):,} species with an English name")
    if s3:
        r2.sync_file(s3, dest, R2_KEY, immutable=False)
    return dest
