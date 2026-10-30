"""Master list: every species documented from India, with the sources that list it.

Per species (and per state where the place is known) we track two things: an open record, and the IUCN category.
  documented  on the list of any source: ZSI checklists, BSI checklists, Kew WCVP (plants native to India),
              new species since 2007 (Plazi, BSI Plant Discoveries, ZSI Animal Discoveries), or an open record
  observed    an open record: a record anyone can check online. A GBIF record of any kind (photo, sighting,
              specimen, sound, DNA sample, record cited from a paper), or an iNaturalist research-grade
              observation. This is the standard of GBIF, which takes only research grade from iNaturalist.
An iNaturalist "needs ID" observation is not an open record of its species: the name waits for a second person.
A species named only in such observations is not on the list (status 2); its observations still count as waiting.
A checklist entry is not an observation: a species only on checklists is "documented, no open record yet".

Names: every name is matched to the Catalogue of Life (eXtended Release, the taxonomy of GBIF's SQL
downloads): GBIF species keys as they are, ZSI's own Catalogue of Life match, then exact names, then
GBIF's name match against the Catalogue of Life (one request per name, cached in R2 cache/master/).
A name that does not match stays on the list with the label "name not matched".

Inputs (all optional except the snapshot):
  snapshot      snapshots/<run>/{species,ledger,species_decade}.parquet (+ unlocated when built)
  ZSI           data/fnf/zsi/zsi_checklist_matched.csv, else R2 cache/master/zsi_checklist.csv
  WCVP          data/fnf/wcvp/wcvp_india.parquet, else R2 cache/master/wcvp_india.parquet
  BSI checklist data/bsi/bsi_checklist.csv, else R2 cache/bsi/bsi_checklist.csv
  iNaturalist   layers/inat/<period>/species_counts.json (species per state, research grade and needs ID),
                genus_counts.json (genera of observations named only to genus), coarse_counts.json (named only above genus)
  new species   layers/newspecies/<period>/new_species.json
  IUCN          the Red List checklist on GBIF (pipeline/iucn.py)
  described     Catalogue of Life authorship and Kew WCVP years (pipeline/described.py), R2 cache/described/

Output: data/layers/master/<period>/. With --publish, R2 layers/master/<period>/<build>/ (one folder per build, never
changed after), then layers/master/<period>/current.json and layers/master/latest.json name it.
  master.parquet        one row per species on the list: key, name, group, sources[], observed (an open record), iucn,
                        labels[], states_observed[] (states with an open record), year (described), authority
  master_state.parquet  one row per species x state with an observation
  summary.json          totals by group and by state x group
  g/<gi>.json           all species of a group
  search/<p>.json       search index, one file per two-letter name prefix; search/places.json

Usage:
  python -m pipeline.master seed                                 # local machine: ZSI and WCVP files to R2 cache/master/
  python -m pipeline.master [--snapshot 2026-10] [--minutes 60] [--publish]
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests

from pipeline import described, gbif, health, iucn, unlocated
from pipeline.gbif import NEW_SPECIES_FROM
from pipeline.boundaries import title
from pipeline.groups import GROUP_SQL, GROUPS
from pipeline.layer_newspecies import expand, gbif_match
from pipeline.site_data import RIGHTS, shard_of
from pipeline.r2 import sha256
from pipeline.util import dump, first, now, period, value

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "master"
LAYERS = ROOT / "data" / "layers"
SNAPSHOTS = ROOT / "data" / "snapshots"
ZSI_LOCAL = ROOT / "data" / "fnf" / "zsi" / "zsi_checklist_matched.csv"
WCVP_LOCAL = ROOT / "data" / "fnf" / "wcvp" / "wcvp_india.parquet"
BSI_LOCAL = ROOT / "data" / "bsi" / "bsi_checklist.csv"
MATCH_KEY = "cache/master/gbif_match.json"
SEED_MATCH_KEYS = ["cache/newspecies/gbif_match.json"]   # earlier matches, read only
CHECKPOINT = 600  # seconds between saves of the match cache
RETRIES, BACKOFF = 5, 30  # GBIF match: tries per name, and names failing in a row before stopping; seconds
WORKERS = 4  # GBIF match requests at once

SOURCES = ["ZSI", "BSI", "WCVP", "GBIF", "iNaturalist", "Plazi", "IUCN", "Lichens", "Bryophytes"]
LABELS = [
    ("rg", "Research grade (iNaturalist)", "id"),
    ("nid", "Needs ID (iNaturalist)", "id"),
    ("ho", "Human observation", "id"),
    ("sp", "Specimen", "id"),
    ("pap", "From a paper", "id"),
    ("dna", "DNA sequence or sample", "id"),
    ("mo", "Machine observation", "id"),
    ("oc", "Other record (kind not given)", "id"),
    ("chk", "Checklist only", "id"),
    ("lm", "No exact location", "other"),
    ("do", "DNA only", "other"),
    ("end", "Endemic to India", "other"),
    ("nra", "No record since it was described", "other"),
    ("nm", "Name not matched", "other"),
    ("vn", "Recorded under the name as published", "other"),
    ("lnc", "Records with no coordinates", "other"),
    ("lco", "Records with coordinates uncertain by more than 25 km", "other"),
    ("lfl", "Records with coordinates that GBIF marks as possibly wrong", "other"),
    ("lgo", "Only GBIF records with no exact location", "other"),
]
# Query L: why a record cannot go in a district.
PROBLEM_LABEL = {"none": "lnc", "coarse": "lco", "issue": "lfl"}
CODES = [c for c, _, _ in LABELS]
# NE = not assessed. EW and EX come last so the first seven indices stay fixed.
IUCN_CATS = ["CR", "EN", "VU", "NT", "LC", "DD", "NE", "EW", "EX"]
THREATENED = ("CR", "EN", "VU")
BASIS_LABEL = {"HUMAN_OBSERVATION": "ho", "OBSERVATION": "ho", "PRESERVED_SPECIMEN": "sp", "MATERIAL_CITATION": "pap",
               "MATERIAL_SAMPLE": "dna", "MACHINE_OBSERVATION": "mo", "OCCURRENCE": "oc"}

# Classification hints from a ZSI checklist file name: (pattern, kingdom, phylum, class, order).
# Used only when the name has no better classification (GBIF, GBIF match, IUCN, genus or family lookup).
ZSI_HINTS = [
    (r"AVES", "Animalia", "Chordata", "Aves", None),
    (r"MAMMALIA", "Animalia", "Chordata", "Mammalia", None),
    (r"REPTILIA", "Animalia", "Chordata", "Reptilia", None),
    (r"AMPHIBIA", "Animalia", "Chordata", "Amphibia", None),
    (r"PISCES", "Animalia", "Chordata", "Actinopterygii", None),
    (r"ODONATA", "Animalia", "Arthropoda", "Insecta", "Odonata"),
    (r"COLEOPTERA", "Animalia", "Arthropoda", "Insecta", "Coleoptera"),
    (r"LEPIDOPTERA", "Animalia", "Arthropoda", "Insecta", "Lepidoptera"),
    (r"DIPTERA", "Animalia", "Arthropoda", "Insecta", "Diptera"),
    (r"HYMENOPTERA", "Animalia", "Arthropoda", "Insecta", "Hymenoptera"),
    (r"HEMIPTERA", "Animalia", "Arthropoda", "Insecta", "Hemiptera"),
    (r"BLATTODEA|MANTODEA|ORTHOPTERA|PHASMIDA|DERMAPTERA|THYSANOPTERA|PSOCOPTERA|TRICHOPTERA|EPHEMEROPTERA|"
     r"PLECOPTERA|NEUROPTERA|MEGALOPTERA|RAPHIDIOPTERA|STREPSIPTERA|MECOPTERA|SIPHONAPTERA|MALLOPHAGA|"
     r"PHTHIRAPTERA|EMBIOPTERA|ARCHAEOGNATHA|ZYGENTOMA", "Animalia", "Arthropoda", "Insecta", None),
    (r"ARACHNIDA|SCORPIONES", "Animalia", "Arthropoda", "Arachnida", None),
    (r"MOLLUSCA", "Animalia", "Mollusca", None, None),
    (r"BRACHYUR|ANOMURA|DECAPODA|AMPHIPODA|ISOPODA|STOMATOPODA|MYSIDA|TANAIDACEA|CUMACEA|EUPHASIACEA|BATHYNELLACEA",
     "Animalia", "Arthropoda", "Malacostraca", None),
    (r"PROTISTA|PROTISTTA|CILIOPHORA|FORAMINIFERA", "Protozoa", None, None, None),
]
# iNaturalist iconic group -> (kingdom, phylum, class).
INAT_HINTS = {"Plantae": ("Plantae", None, None), "Insecta": ("Animalia", "Arthropoda", "Insecta"),
              "Aves": ("Animalia", "Chordata", "Aves"), "Mammalia": ("Animalia", "Chordata", "Mammalia"),
              "Reptilia": ("Animalia", "Chordata", "Reptilia"), "Amphibia": ("Animalia", "Chordata", "Amphibia"),
              "Actinopterygii": ("Animalia", "Chordata", "Actinopterygii"),
              "Arachnida": ("Animalia", "Arthropoda", "Arachnida"), "Mollusca": ("Animalia", "Mollusca", None),
              "Fungi": ("Fungi", None, None), "Animalia": ("Animalia", None, None),
              "Chromista": ("Chromista", None, None), "Protozoa": ("Protozoa", None, None)}
# Group for a genus that has no species on the list, from its iNaturalist iconic group.
ICONIC_GROUP = {"Aves": "Birds", "Reptilia": "Reptiles", "Amphibia": "Amphibians", "Actinopterygii": "Fish",
                "Insecta": "Insects: other", "Arachnida": "Spiders & other arachnids", "Mollusca": "Molluscs",
                "Mammalia": "Mammals: other (whales, dolphins...)", "Plantae": "Plants: other flowering plants & conifers",
                "Fungi": "Fungi"}
# BSI checklist group text -> (kingdom, phylum, class).
BSI_HINTS = [(r"lichen", "Fungi", "Ascomycota", "Lecanoromycetes"), (r"fung", "Fungi", None, None),
             (r"bryo|moss|liverwort|hornwort", "Plantae", "Bryophyta", None),
             (r"alga|diatom", "Plantae", "Chlorophyta", None),
             (r"pterido|fern|lycophyt", "Plantae", "Tracheophyta", "Polypodiopsida"),
             (r"", "Plantae", "Tracheophyta", None)]


def prefix(name):
    """Search file for a name: its first two letters, lower case ASCII; anything else is '_'."""
    p = "".join(c if "a" <= c <= "z" else "_" for c in (name or "").lower()[:2])
    return p.ljust(2, "_")


def hint_row(hints, text):
    """First matching hint for a text, or Nones."""
    for pattern, *cls in hints:
        if re.search(pattern, text or "", re.I):
            return cls
    return [None] * len(hints[0][1:])


# ---------------------------------------------------------------- inputs

def r2_file(s3, key, dest: Path):
    """Download an R2 object to dest if it is missing or differs. Returns dest, or None if R2 has no such object."""
    from pipeline import r2
    if not s3 or not r2.exists(s3, key):
        return dest if dest.exists() else None
    remote = r2.remote_sha256(s3, key)
    if not dest.exists() or (remote and remote != sha256(dest)):
        dest.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(r2.bucket(), key, str(dest))
    return dest


def zsi_derived(src: Path, dest: Path):
    """The columns of the ZSI checklist the master list needs, from fnf's matched file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    duckdb.sql(f"""
        COPY (SELECT checklist, family, name, rank, authority, mark, col_accepted_id, col_accepted_name, col_family, match_type,
                     coalesce(needs_review, 'false') AS needs_review
              FROM read_csv('{src}', header = true, all_varchar = true) ORDER BY checklist, name)
        TO '{dest}' (HEADER)
    """)
    return dest


def zsi_input(s3):
    dest = CACHE / "zsi_checklist.csv"
    if ZSI_LOCAL.exists():
        return zsi_derived(ZSI_LOCAL, dest)
    return r2_file(s3, "cache/master/zsi_checklist.csv", dest)


def wcvp_input(s3):
    return WCVP_LOCAL if WCVP_LOCAL.exists() else r2_file(s3, "cache/master/wcvp_india.parquet", CACHE / "wcvp_india.parquet")


def globi_input(s3):
    """GloBI's species table (pipeline/globi.py). With R2, always R2's copy (a local one can be out of date)."""
    from pipeline import globi
    return r2_file(s3, globi.R2_PREFIX + "species.parquet", CACHE / "globi_species.parquet") if s3 else (
        globi.CACHE / "species.parquet" if (globi.CACHE / "species.parquet").exists() else None)


def globi_edges_input(s3):
    """GloBI's partner table (pipeline/globi.py edges.parquet). With R2, always R2's copy."""
    from pipeline import globi
    local = globi.CACHE / "edges.parquet"
    return r2_file(s3, globi.R2_PREFIX + "edges.parquet", CACHE / "globi_edges.parquet") if s3 else (
        local if local.exists() else None)


def lichens_input(s3):
    """The lichen checklist table (pipeline/lichens.py): R2's copy, else the local one."""
    from pipeline import lichens
    local = lichens.CACHE / lichens.TABLE
    return r2_file(s3, lichens.R2_DIR + lichens.TABLE, CACHE / lichens.TABLE) if s3 else (local if local.exists() else None)


ZOTERO_MINUTES = 20   # the bird bibliography's pass at most this long per run; the next run continues


def zotero_input_refreshed(http, s3):
    """The bird bibliography brought up to date (pipeline/zotero.py), else the last table in R2."""
    from pipeline import zotero
    try:
        return zotero.refresh(http, s3, deadline=time.monotonic() + ZOTERO_MINUTES * 60)
    except Exception as e:  # noqa: BLE001 - any failure: last week's table
        print(f"zotero: not refreshed ({e}); using the copy in R2", flush=True)
        return zotero_input(s3)


def zotero_input(s3):
    """The bird bibliography's table (pipeline/zotero.py): R2's copy, else the local one."""
    from pipeline import zotero
    local = zotero.CACHE / zotero.TABLE
    return r2_file(s3, zotero.R2_DIR + zotero.TABLE, CACHE / zotero.TABLE) if s3 else (local if local.exists() else None)


def bryophytes_input(s3):
    """The bryophyte checklist table (pipeline/bryophytes.py): R2's copy, else the local one."""
    from pipeline import bryophytes
    local = bryophytes.CACHE / bryophytes.TABLE
    return (r2_file(s3, bryophytes.R2_DIR + bryophytes.TABLE, CACHE / bryophytes.TABLE) if s3
            else (local if local.exists() else None))


def bsi_monographs_input(s3):
    """BSI's regional and family books (pipeline/bsi_monographs.py): the local table, else R2's."""
    local = BSI_LOCAL.with_name("bsi_monographs.csv")
    return local if local.exists() else r2_file(s3, "cache/bsi/bsi_monographs.csv", CACHE / "bsi_monographs.csv")


EVIDENCE_MINUTES = 40   # Wikidata requests at most this long per run; the next run continues


def evidence_input(http, s3, paths, prev):
    """pipeline/evidence.py's tables (species.parquet, bold_india.csv) for the species of the snapshot and of the
    previous list: refreshed, else R2's last copies (None, None when there are none)."""
    from pipeline import evidence
    keys = {k for (k,) in duckdb.sql(f"SELECT DISTINCT species_key FROM '{paths['species']}'").fetchall()}
    if prev:
        keys |= {k for (k,) in duckdb.sql(f"SELECT key FROM '{prev['parquet']}' WHERE key IS NOT NULL").fetchall()}
    try:
        return evidence.refresh(http, s3, sorted(k for k in keys if k),
                                deadline=time.monotonic() + EVIDENCE_MINUTES * 60)
    except Exception as e:  # noqa: BLE001 - any failure: last week's tables
        print(f"evidence: not refreshed ({e}); using the copies in R2", flush=True)
        return (r2_file(s3, evidence.R2_DIR + "species.parquet", CACHE / "evidence.parquet"),
                r2_file(s3, evidence.R2_DIR + "bold_india.csv", CACHE / "bold_india.csv"))


def bsi_input(s3):
    return BSI_LOCAL if BSI_LOCAL.exists() else r2_file(s3, "cache/bsi/bsi_checklist.csv", CACHE / "bsi_checklist.csv")


def seed(s3):
    """Local machine only: copy the ZSI and WCVP inputs (not in git, not on Actions) to R2 cache/master/."""
    from pipeline import r2
    sent = r2.sync_file(s3, zsi_derived(ZSI_LOCAL, CACHE / "zsi_checklist.csv"), "cache/master/zsi_checklist.csv",
                        immutable=False)
    sent += r2.sync_file(s3, WCVP_LOCAL, "cache/master/wcvp_india.parquet", immutable=False)
    print(f"seeded R2 cache/master/: {sent} of 2 files uploaded (the rest were already there)")


def snapshot_input(s3, run_id):
    """Paths of the snapshot files; missing ones are fetched from R2 snapshots/<run>/."""
    folder = SNAPSHOTS / run_id
    paths = {}
    for name in ("species", "ledger", "species_decade", "unlocated", "species_places"):
        p = folder / f"{name}.parquet"
        if not p.exists() and s3:
            r2_file(s3, f"snapshots/{run_id}/{name}.parquet", p)
        paths[name] = p if p.exists() else None
    missing = [n for n in ("species", "ledger", "species_decade") if not paths[n]]
    if missing:
        raise SystemExit(f"snapshot {run_id}: {missing} not found locally or in R2")
    if not paths["unlocated"]:
        print(f"warning: snapshot {run_id} has no unlocated.parquet; GBIF records that cannot go in a district count nowhere",
              flush=True)
    return paths


def layer_input(s3, layer, field, filename):
    """The newest local layers/<layer>/<period>/<filename>, else the one R2 layers/<layer>/latest.json names."""
    from pipeline import r2
    local = sorted((LAYERS / layer).glob(f"*/{filename}"))
    if local:
        return json.loads(local[-1].read_text()), local[-1].parent.name
    latest = r2.get_json(s3, f"layers/{layer}/latest.json") if s3 else None
    if latest and latest.get(field):
        return r2.get_json(s3, latest[field]), latest.get("period") or latest.get("month")
    return None, None


# ---------------------------------------------------------------- loading

NAMES_COLS = ("source VARCHAR, name VARCHAR, key VARCHAR, kingdom VARCHAR, phylum VARCHAR, class VARCHAR, "
              "\"order\" VARCHAR, family VARCHAR, genus VARCHAR, grp VARCHAR, endemic BOOLEAN, new BOOLEAN, tier INTEGER")
EVIDENCE_COLS = ("source VARCHAR, name VARCHAR, key VARCHAR, state_lgd INTEGER, label VARCHAR, "
                 "observed BOOLEAN, located BOOLEAN, year INTEGER")
# Canonical "Genus epithet": subgenus in brackets dropped, infraspecific part dropped.
BINOMIAL = """CREATE OR REPLACE MACRO binomial(s) AS coalesce(nullif(regexp_extract(
                  regexp_replace(trim(s), '\\s*\\([A-Z][a-z]+\\)', ''), '^([A-Z][a-z-]+ (× ?)?[a-z][a-z-]+)', 1), ''),
              nullif(trim(s), ''))"""


def start(con):
    """Empty tables every loader appends to.
    names_in: one row per source x name (documentation), with what is known of the classification.
      tier: how good the classification is (0 = GBIF's own; 5 = a hint from the source).
    evidence: observations. observed: an open record (false for iNaturalist needs ID). state_lgd NULL = India,
      place not known. year: the latest year of the records behind the row, when known."""
    con.sql(BINOMIAL)
    con.sql(f"CREATE OR REPLACE TABLE names_in ({NAMES_COLS})")
    con.sql(f"CREATE OR REPLACE TABLE evidence ({EVIDENCE_COLS})")
    con.sql("CREATE OR REPLACE TABLE alias (name VARCHAR, key VARCHAR, display VARCHAR, prio INTEGER)")
    con.sql("CREATE OR REPLACE TABLE inat_wait (name VARCHAR, raw VARCHAR, state_lgd INTEGER, taxon BIGINT, n BIGINT)")
    con.sql("CREATE OR REPLACE TABLE inat_genus (genus VARCHAR, state_lgd INTEGER, taxon BIGINT, n BIGINT, iconic VARCHAR)")
    con.sql("CREATE OR REPLACE TABLE ns_info (name VARCHAR, year INTEGER, paper VARCHAR)")
    for t in ("col_year (id VARCHAR", "zsi_year (name VARCHAR", "wcvp_year (name VARCHAR"):
        con.sql(f"CREATE OR REPLACE TABLE {t}, year INTEGER, authority VARCHAR)")


def insert(con, table, select, cols, rows):
    """Insert Python rows through an Arrow table (DuckDB's executemany goes row by row, and is slow)."""
    import pyarrow as pa
    con.register("py_rows", pa.table({c: [r[i] for r in rows] for i, c in enumerate(cols)}))
    con.sql(f"INSERT INTO {table} {select} FROM py_rows")
    con.unregister("py_rows")


def load_gbif(con, paths):
    """GBIF species (records with coordinates), their kinds of record, states, and records that cannot go in a district."""
    basis = " ".join(f"WHEN '{b}' THEN '{c}'" for b, c in BASIS_LABEL.items())
    con.sql(f"""INSERT INTO names_in SELECT 'GBIF', name, species_key, kingdom, phylum, class, "order", family, genus,
                NULL, false, false, 0 FROM '{paths["species"]}'""")
    con.sql(f"""INSERT INTO evidence SELECT DISTINCT 'GBIF', NULL, species_key, NULL, CASE basis {basis} ELSE 'oc' END,
                true, true, NULL FROM '{paths["species_decade"]}'""")
    con.sql(f"""INSERT INTO evidence SELECT DISTINCT 'GBIF', NULL, species_key, state_lgd, NULL, true, true, last_year
                FROM '{paths["ledger"]}' WHERE state_lgd IS NOT NULL""")
    con.sql(f"""INSERT INTO alias SELECT name, species_key, name, 0 FROM '{paths["species"]}'""")
    # DNA only, where the ledger knows which records are DNA sequences (snapshots built after that column was added).
    cols = [c[0] for c in con.sql(f"DESCRIBE SELECT * FROM '{paths['ledger']}'").fetchall()]
    dna_sql = (f"""SELECT species_key AS key FROM '{paths["ledger"]}' GROUP BY 1
                   HAVING max(last_year_not_dna) IS NULL AND max(last_year) IS NOT NULL"""
               if "last_year_not_dna" in cols else "SELECT NULL::VARCHAR AS key WHERE false")
    con.sql(f"CREATE OR REPLACE TABLE ledger_dna_only AS {dna_sql}")
    # The Raunkiæran gap: a record placed in India with a trait (ledgers built after n_trait was added; else empty).
    trait_sql = (f"SELECT species_key AS key FROM '{paths['ledger']}' GROUP BY 1 HAVING sum(n_trait) > 0"
                 if "n_trait" in cols else "SELECT NULL::VARCHAR AS key WHERE false")
    con.sql(f"CREATE OR REPLACE TABLE ledger_trait AS {trait_sql}")
    # Places with a record to 1 km or better, and 2 km cells (snapshots built after species_places was added).
    con.sql(f"CREATE OR REPLACE TABLE gbif_places AS SELECT species_key AS key, places_precise, cells_2km FROM '{paths['species_places']}'"
            if paths.get("species_places") else
            "CREATE OR REPLACE TABLE gbif_places (key VARCHAR, places_precise BIGINT, cells_2km BIGINT)")
    if paths.get("unlocated"):
        # Excluded datasets and places outside India apply also to snapshots built before they were listed.
        con.execute(f"""CREATE OR REPLACE TABLE unl AS SELECT * FROM '{paths["unlocated"]}' WHERE species_key IS NOT NULL
                        AND NOT list_contains($1, coalesce(datasetkey, ''))
                        AND NOT list_contains($2, coalesce(lower(trim(stateprovince)), ''))""",
                    [gbif.dataset_keys(), sorted(unlocated.foreign_places())])
        con.sql("""INSERT INTO names_in SELECT 'GBIF', name, species_key, NULL, NULL, NULL, NULL, NULL, genus, grp,
                   false, false, 1 FROM unl""")
        con.sql(f"""INSERT INTO evidence SELECT DISTINCT 'GBIF', NULL, species_key, state_lgd,
                    CASE basis {basis} ELSE 'oc' END, true, false, last_year FROM unl""")
        problem = " ".join(f"WHEN '{p}' THEN '{c}'" for p, c in PROBLEM_LABEL.items())
        con.sql(f"""INSERT INTO evidence SELECT DISTINCT 'GBIF', NULL, species_key, NULL, CASE problem {problem} END,
                    true, false, NULL FROM unl""")
    return "last_year_not_dna" in cols


def load_zsi(con, path):
    """ZSI checklists. Matched names keep ZSI's Catalogue of Life key; subspecies count as their species;
    names held for review or not matched are looked up by name later. '*' marks a species endemic to India."""
    hints = [(c, *hint_row(ZSI_HINTS, c)) for (c,) in
             con.sql(f"SELECT DISTINCT checklist FROM read_csv('{path}', header = true, all_varchar = true)").fetchall()]
    con.execute("CREATE OR REPLACE TABLE zsi_hint (checklist VARCHAR, kingdom VARCHAR, phylum VARCHAR, class VARCHAR, "
                "\"order\" VARCHAR)")
    con.executemany("INSERT INTO zsi_hint VALUES (?, ?, ?, ?, ?)", hints)
    con.sql(f"""
        CREATE OR REPLACE TABLE zsi AS
        SELECT z.*, h.kingdom, h.phylum, h.class, h."order",
               match_type <> 'none' AND NOT needs_review::BOOLEAN AND col_accepted_id IS NOT NULL AS matched
        FROM read_csv('{path}', header = true, all_varchar = true) z JOIN zsi_hint h USING (checklist)
    """)
    con.sql("""
        INSERT INTO names_in
        SELECT 'ZSI', CASE WHEN matched THEN binomial(coalesce(col_accepted_name, name)) ELSE binomial(name) END,
               CASE WHEN matched AND rank = 'species' THEN col_accepted_id END,
               kingdom, phylum, class, "order", coalesce(col_family, family), NULL, NULL,
               coalesce(mark, '') LIKE '%*%', false, 5
        FROM zsi
    """)
    con.sql("""INSERT INTO alias SELECT DISTINCT binomial(coalesce(col_accepted_name, name)), col_accepted_id, binomial(coalesce(col_accepted_name, name)), 1
               FROM zsi WHERE matched AND rank = 'species'""")
    # Authority with its year ("Kruse, 1890"): one source of the year described. Older copies have no authority.
    if "authority" in [c for c, *_ in con.sql("DESCRIBE zsi").fetchall()]:
        con.sql(f"""INSERT INTO zsi_year
                    SELECT DISTINCT CASE WHEN matched THEN binomial(coalesce(col_accepted_name, name)) ELSE binomial(name) END,
                           {described.year_sql("authority")}, nullif(trim(authority), '')
                    FROM zsi WHERE rank = 'species' AND authority IS NOT NULL""")
    con.sql("""INSERT INTO alias SELECT DISTINCT binomial(name), col_accepted_id, binomial(coalesce(col_accepted_name, name)), 2
               FROM zsi WHERE matched AND rank = 'species'""")


def load_lichens(con, path):
    """The lichen checklist of India (pipeline/lichens.py; Sinha, Nayaka & Mishra 2024, CC BY-NC 4.0): accepted
    names, with the paper's endemic mark. Its synonyms are other names of the same species, so they are not listed."""
    con.sql(f"""INSERT INTO names_in SELECT DISTINCT 'Lichens', binomial(name), NULL, 'Fungi', 'Ascomycota',
                'Lecanoromycetes', NULL, NULL, NULL, NULL, endemic::BOOLEAN, false, 5
                FROM read_csv('{path}', header = true, all_varchar = true) WHERE coalesce(name, '') <> ''""")


def load_bryophytes(con, path):
    """The bryophyte checklist of India (pipeline/bryophytes.py; Dandotiya et al. 2011): mosses, liverworts and
    hornworts by name, with the phylum of the list each is in. Rows with no species name ("Bryum sp.") are left out."""
    con.sql(f"""INSERT INTO names_in SELECT DISTINCT 'Bryophytes', binomial(name), NULL, 'Plantae', phylum, NULL, NULL,
                NULL, genus, NULL, false, false, 5
                FROM read_csv('{path}', header = true, all_varchar = true) WHERE coalesce(name, '') <> ''""")


def load_wcvp(con, path):
    """Kew WCVP: vascular plants native to India; endemic_india from Kew's distribution data."""
    con.sql(f"""INSERT INTO names_in SELECT 'WCVP', binomial(species), NULL, 'Plantae', 'Tracheophyta', NULL, NULL,
                family, genus, NULL, coalesce(endemic_india, false), false, 5 FROM '{path}'""")


def load_bsi(con, path):
    """BSI checklists (pipeline/bsi_checklist.py). Accepted names only: a synonym is another name of a species
    the checklist lists under its accepted name. Varieties and subspecies count as their species.
    status containing 'endemic' marks an endemic species."""
    rows = con.sql(f"""SELECT DISTINCT binomial(name), family, "group", coalesce(status, '') ILIKE '%endemic%'
                       FROM read_csv('{path}', header = true, all_varchar = true)
                       WHERE name IS NOT NULL AND coalesce(status, 'accepted') NOT ILIKE '%synonym%'""").fetchall()
    insert(con, "names_in", """SELECT 'BSI', n, NULL, k::VARCHAR, p::VARCHAR, c::VARCHAR, NULL, fam, NULL, NULL,
                                      e::BOOLEAN, false, 5""",
           ["n", "k", "p", "c", "fam", "e"], [[n, *hint_row(BSI_HINTS, g), fam, end] for n, fam, g, end in rows])


def load_inat(con, doc):
    """iNaturalist species lists per state: research grade = an open record; needs ID = waits for a name (evidence that
    links the waiting observations to the species, not an open record)."""
    rows, names, wait = [], {}, []
    for code, lists in doc["lists"].items():
        state = None if code == "india" else int(code)
        for quality, label, record in (("research", "rg", True), ("needs_id", "nid", False)):
            for taxon, name, iconic, n in lists.get(quality, []):
                rows.append([name, state, label, record])
                names.setdefault(name, iconic)
                if quality == "needs_id":
                    wait.append([name, state, taxon, n])
    insert(con, "inat_wait", "SELECT binomial(n), n, s::INTEGER, t::BIGINT, c::BIGINT", ["n", "s", "t", "c"], wait)
    insert(con, "evidence", "SELECT 'iNaturalist', binomial(n), NULL, s::INTEGER, l, r, true, NULL",
           ["n", "s", "l", "r"], rows)
    insert(con, "names_in", """SELECT 'iNaturalist', binomial(n), NULL, k::VARCHAR, p::VARCHAR, c::VARCHAR, NULL, NULL,
                                      NULL, NULL, false, false, 5""",
           ["n", "k", "p", "c"], [[n, *INAT_HINTS.get(i or "", (None, None, None))] for n, i in names.items()])


def load_inat_genus(con, doc):
    """iNaturalist genera of needs-ID observations named only to genus, per state (india = all of India)."""
    rows = [[g, None if code == "india" else int(code), t, n, i]
            for code, lst in doc["lists"].items() for t, g, i, n in lst]
    insert(con, "inat_genus", "SELECT g, s::INTEGER, t::BIGINT, n::BIGINT, i", ["g", "s", "t", "n", "i"], rows)


def load_newspecies(con, doc):
    """Species described from India since the new-species layer's first year (Plazi; BSI and ZSI Discoveries).
    Table ns_info keeps each paper: year, sources, journal, link, and records after the description."""
    rows, info, seen = [], [], []
    for r in expand(doc):
        grp = r["group"] if r["group"] in GROUPS else None
        for src, tag in (("Plazi", "Plazi"), ("BSI", "BSI Plant Discoveries"), ("ZSI", "ZSI Animal Discoveries")):
            if tag in r["sources"]:
                rows.append([src, r["name"], r["key"], grp, (r["year"] or 0) >= NEW_SPECIES_FROM])
        # GBIF has no key for the name yet, but records under the name as published after the description.
        if r["status"] == "recorded" and r["matched_by"] == "name as published in GBIF":
            seen.append([r["name"]])
        info.append([r["name"], r["year"], json.dumps([r["sources"], r["journal"] or None, r["link"], r["status"],
                                                      r["latest_after"], r["year"]], ensure_ascii=False)])
    insert(con, "names_in", """SELECT src, binomial(n), k::VARCHAR, NULL, NULL, NULL, NULL, NULL, NULL, g::VARCHAR,
                                      false, new, 5""", ["src", "n", "k", "g", "new"], rows)
    insert(con, "ns_info", "SELECT binomial(n), y::INTEGER, d", ["n", "y", "d"], info)
    # Observed in India, in no state; located stays unknown, as the layer does not keep the coordinates.
    insert(con, "evidence", "SELECT 'GBIF', binomial(n), NULL, NULL, 'vn', true, NULL, NULL", ["n"], seen)


def load_described(con, paths):
    """Years described: Catalogue of Life by key, WCVP by name (pipeline/described.py)."""
    if paths.get("col"):
        con.sql(f"INSERT INTO col_year SELECT id, year, authority FROM '{paths['col']}'")
    if paths.get("wcvp"):
        con.sql(f"INSERT INTO wcvp_year SELECT name, year, authority FROM '{paths['wcvp']}'")


def described_years(con):
    """Table id_year (id, year, authority, paper): the year from the paper of a new species, else Catalogue of Life
    (by key), else the ZSI authority, else WCVP (plants, by name). The authority comes from the same order.
    A checklist year (Catalogue of Life or ZSI) more than a year before the paper wins over it: the paper lists
    an older species as new (a new record for India or a new combination, or a name matched to an older species)."""
    con.sql("""
        CREATE OR REPLACE TABLE id_year AS
        WITH ns AS (SELECT DISTINCT r.id, n.year, n.paper FROM ns_info n JOIN names_in_r r ON r.new AND r.name = n.name),
        c AS (SELECT id, year, NULL AS authority, 0 AS p FROM ns
              UNION ALL SELECT i.id, y.year, y.authority, 1 FROM ids i JOIN col_year y ON y.id = i.id
              UNION ALL SELECT DISTINCT r.id, z.year, z.authority, 2 FROM zsi_year z
                        JOIN names_in_r r ON r.source = 'ZSI' AND r.name = z.name
              UNION ALL SELECT i.id, w.year, w.authority, 3 FROM ids i JOIN wcvp_year w ON w.name = i.name
                        WHERE i.kingdom = 'Plantae' OR i.kingdom IS NULL),
        y AS (SELECT id, arg_min(year, p) FILTER (WHERE year IS NOT NULL) AS first,
                     min(year) FILTER (WHERE p = 0) AS paper_year, arg_min(year, p) FILTER (WHERE p IN (1, 2) AND year IS NOT NULL) AS checklist_year,
                     arg_min(authority, p) FILTER (WHERE authority IS NOT NULL) AS authority
              FROM c GROUP BY id)
        SELECT y.id, CASE WHEN checklist_year < paper_year - 1 THEN checklist_year ELSE first END AS year,
               y.authority, ns.paper
        FROM y LEFT JOIN (SELECT id, arg_min(paper, year) AS paper FROM ns GROUP BY id) ns USING (id)
    """)


# ---------------------------------------------------------------- names

def match_cache(s3):
    """GBIF name matches: earlier matches (new species layer), then ours on top."""
    from pipeline import r2
    cache = {}
    for key in (SEED_MATCH_KEYS + [MATCH_KEY]) if s3 else []:
        cache.update(r2.get_json(s3, key) or {})
    local = CACHE / "gbif_match.json"
    if local.exists():
        cache.update(json.loads(local.read_text()))
    return cache


def save_match_cache(cache, s3):
    local = CACHE / "gbif_match.json"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps(cache, ensure_ascii=False))
    if s3:
        from pipeline import r2
        r2.sync_file(s3, local, MATCH_KEY, immutable=False)


def to_match(con, cache):
    """Names no key or alias gives, not yet asked of GBIF: iNaturalist research grade first, then needs ID,
    WCVP, BSI and the lichen and bryophyte checklists, then GloBI (a record in India) and BOLD (from India). ZSI names were matched against the same Catalogue of Life release in fnf, so not asked again."""
    rows = con.sql("""
        WITH want AS (
            SELECT name, CASE WHEN label = 'rg' THEN 0 ELSE 1 END AS prio FROM evidence
            WHERE key IS NULL AND source = 'iNaturalist'
            UNION ALL SELECT name, CASE source WHEN 'WCVP' THEN 2 ELSE 3 END FROM names_in
            WHERE key IS NULL AND source IN ('WCVP', 'BSI', 'Lichens', 'Bryophytes')
            -- Names that count for a species but list nothing: GloBI's with a record in India, BOLD's from India.
            UNION ALL SELECT name, 4 FROM globi WHERE india UNION ALL SELECT name, 4 FROM bold
            -- The bird bibliography's tags mix places and topics with names: only a tag with a bird genus.
            UNION ALL SELECT name, 5 FROM lit WHERE split_part(name, ' ', 1) IN
                (SELECT DISTINCT split_part(name, ' ', 1) FROM names_in WHERE class = 'Aves'))
        SELECT name FROM want WHERE name IS NOT NULL AND NOT EXISTS (SELECT 1 FROM alias a WHERE a.name = want.name)
        GROUP BY name ORDER BY min(prio), name
    """).fetchall()
    return [n for (n,) in rows if n not in cache]


def match_names(names, cache, s3, deadline=None, http=None):
    """Ask GBIF for each name not in the cache, WORKERS at a time (each worker about 1 request a second),
    saving the cache every 10 minutes and at the end. A failed request is tried again after a pause; the run
    stops at the deadline, or after RETRIES names in a row fail. The next run continues. Returns how many
    names were answered."""
    http = http or requests.Session()
    http.headers.setdefault("User-Agent", health.ua())
    todo = iter([n for n in dict.fromkeys(names) if n not in cache])

    def ask(name):
        """(name, answer) from a private dict, so only this thread touches the shared cache."""
        for attempt in range(1, RETRIES + 1):
            got = {}
            try:
                gbif_match(http, name, got, need_classification=True)
                return name, got  # empty: GBIF answered with an error; asked again next run
            except requests.RequestException:
                if attempt == RETRIES:
                    raise
                time.sleep(BACKOFF * attempt)

    asked, failures, next_save, stop = 0, 0, time.monotonic() + CHECKPOINT, None
    with ThreadPoolExecutor(WORKERS) as pool:
        running = set()
        try:
            while True:
                while not stop and len(running) < WORKERS * 2:
                    if deadline is not None and time.monotonic() > deadline:
                        stop = "time limit"
                        break
                    name = next(todo, None)
                    if name is None:
                        break
                    running.add(pool.submit(ask, name))
                if not running:
                    break
                done, running = wait(running, return_when=FIRST_COMPLETED)
                for f in done:
                    try:
                        name, got = f.result()
                        cache.update(got)
                        asked, failures = asked + 1, 0
                        if asked % 500 == 0:
                            print(f"{datetime.now(timezone.utc):%H:%M:%S} {asked} names matched", flush=True)
                    except requests.RequestException as e:
                        failures += 1
                        if failures >= RETRIES and not stop:
                            stop = f"{failures} names in a row failed ({type(e).__name__})"
                if time.monotonic() > next_save:
                    next_save = time.monotonic() + CHECKPOINT
                    print(f"{asked} names matched; saving the cache", flush=True)
                    save_match_cache(cache, s3)
        finally:
            for f in running:
                f.cancel()
            if asked:
                save_match_cache(cache, s3)
    if stop:
        print(f"GBIF match stopped: {stop}; {asked} names matched this run; the next run continues", flush=True)
    return asked


def add_matches(con, cache):
    """Matches from the cache become aliases, with their classification (tier 1 for the group)."""
    rows = [[n, m["key"], m.get("accepted_name") or n, *(m.get("classification") or {}).values()]
            for n, m in cache.items() if m and m.get("key")]
    con.sql("CREATE OR REPLACE TABLE matched (name VARCHAR, key VARCHAR, display VARCHAR, kingdom VARCHAR, "
            "phylum VARCHAR, class VARCHAR, \"order\" VARCHAR, family VARCHAR)")
    cols = ["name", "key", "display", "kingdom", "phylum", "class", "order", "family"]
    insert(con, "matched", "SELECT " + ", ".join(f'"{c}"::VARCHAR' for c in cols), cols,
           [r + [None] * (8 - len(r)) for r in rows])
    con.sql("DELETE FROM alias WHERE prio = 3")
    con.sql("INSERT INTO alias SELECT name, key, display, 3 FROM matched")


def resolve(con):
    """Give every row an id: its key, else the key its name has (alias), else 'n:<name>' (name not matched).
    Then fold ids that share a name and kingdom into one (GBIF's key first), as names.merge_duplicates does
    for GBIF keys. Creates tables ids (id, name, grp, kingdom), idmap (id -> canonical)."""
    con.sql("""CREATE OR REPLACE TABLE alias1 AS
               SELECT name, arg_min(key, prio) AS key FROM alias
               WHERE name IS NOT NULL AND key IS NOT NULL GROUP BY name""")
    for t in ("names_in", "evidence"):
        con.sql(f"""CREATE OR REPLACE TABLE {t}_r AS
                    SELECT t.*, coalesce(t.key, a.key, 'n:' || t.name) AS id
                    FROM {t} t LEFT JOIN alias1 a ON t.key IS NULL AND a.name = t.name
                    WHERE coalesce(t.key, t.name) IS NOT NULL""")
    # Evidence for a key with no documentation row (it cannot happen for GBIF, but keeps ids complete).
    con.sql("""CREATE OR REPLACE TABLE all_ids AS
               SELECT id FROM names_in_r UNION SELECT id FROM evidence_r""")
    # Display name: GBIF's name, else ZSI's accepted name, else the matched accepted name, else a source's name.
    con.sql("""
        CREATE OR REPLACE TABLE display AS
        WITH c AS (
            SELECT id, name, 0 AS p FROM names_in_r WHERE source = 'GBIF' AND key = id
            UNION ALL SELECT key, display, prio FROM alias WHERE key IS NOT NULL AND display IS NOT NULL
            UNION ALL SELECT id, name, 9 FROM names_in_r
            UNION ALL SELECT id, name, 9 FROM evidence_r WHERE name IS NOT NULL)
        SELECT id, arg_min(name, p * 1000 + length(name)) AS name FROM c JOIN all_ids USING (id) GROUP BY id
    """)
    # Classification: GBIF's (0), GBIF match (1), IUCN (2), genus lookup (3), family lookup (4), source hint (5).
    con.sql("""
        CREATE OR REPLACE TABLE ref_taxa AS
        SELECT genus, family, kingdom, phylum, class, "order", 0 AS p FROM names_in WHERE tier = 0
        UNION ALL SELECT split_part(name, ' ', 1), family, kingdom, phylum, class, "order", 1 FROM iucn WHERE accepted
    """)
    con.sql("""CREATE OR REPLACE TABLE genus_ref AS
               SELECT genus, kingdom, arg_min(family, p) AS family, arg_min(phylum, p) AS phylum,
                      arg_min(class, p) AS class, arg_min("order", p) AS "order"
               FROM ref_taxa WHERE genus IS NOT NULL GROUP BY genus, kingdom""")
    con.sql("""CREATE OR REPLACE TABLE family_ref AS
               SELECT family, kingdom, arg_min(phylum, p) AS phylum, arg_min(class, p) AS class,
                      arg_min("order", p) AS "order"
               FROM ref_taxa WHERE family IS NOT NULL GROUP BY family, kingdom""")
    con.sql(f"""
        CREATE OR REPLACE TABLE cls AS
        WITH n AS (SELECT DISTINCT id, d.name, n.kingdom AS hk, n.phylum AS hp, n.class AS hc, n."order" AS ho,
                          n.family AS hf, n.grp AS hg, n.tier
                   FROM names_in_r n JOIN display d USING (id)),
        c AS (
            SELECT id, 0 AS t, NULL AS grp, hk AS kingdom, hp AS phylum, hc AS class, ho AS "order", hf AS family
            FROM n WHERE tier = 0
            UNION ALL SELECT id, 1, hg, NULL, NULL, NULL, NULL, NULL FROM n WHERE hg IS NOT NULL
            UNION ALL SELECT key, 1, NULL, kingdom, phylum, class, "order", family FROM matched WHERE kingdom IS NOT NULL
            UNION ALL SELECT n.id, 2, NULL, i.kingdom, i.phylum, i.class, i."order", i.family
                      FROM n JOIN iucn i ON i.name = n.name AND i.accepted AND (n.hk IS NULL OR n.hk = i.kingdom)
            UNION ALL SELECT n.id, 3, NULL, g.kingdom, g.phylum, g.class, g."order", g.family
                      FROM n JOIN genus_ref g ON g.genus = split_part(n.name, ' ', 1) AND (n.hk IS NULL OR n.hk = g.kingdom)
            UNION ALL SELECT n.id, 4, NULL, f.kingdom, f.phylum, f.class, f."order", n.hf
                      FROM n JOIN family_ref f ON f.family = n.hf AND (n.hk IS NULL OR n.hk = f.kingdom)
            UNION ALL SELECT id, 5, NULL, hk, hp, hc, ho, hf FROM n)
        SELECT id, arg_min(coalesce(grp, {GROUP_SQL}), t) AS grp,
               arg_min(kingdom, t) FILTER (WHERE kingdom IS NOT NULL) AS kingdom
        FROM c GROUP BY id
    """)
    con.sql("""
        CREATE OR REPLACE TABLE ids0 AS
        SELECT a.id, d.name, coalesce(c.grp, 'Other') AS grp, c.kingdom,
               a.id IN (SELECT id FROM names_in_r WHERE source = 'GBIF') AS in_gbif
        FROM all_ids a JOIN display d USING (id) LEFT JOIN cls c USING (id)
    """)
    con.sql("""
        CREATE OR REPLACE TABLE idmap AS
        SELECT id, CASE WHEN in_gbif THEN id  -- GBIF keys stay apart: names.merge_duplicates already merged them
                        ELSE first_value(id) OVER (PARTITION BY name, coalesce(kingdom, '')
                                                   ORDER BY in_gbif DESC, starts_with(id, 'n:'), id) END AS canonical
        FROM ids0
    """)
    con.sql("""CREATE OR REPLACE TABLE ids AS
               SELECT i.* EXCLUDE (in_gbif) FROM ids0 i JOIN idmap m USING (id) WHERE m.id = m.canonical""")
    for t in ("names_in_r", "evidence_r"):
        con.sql(f"UPDATE {t} SET id = m.canonical FROM idmap m WHERE {t}.id = m.id AND m.id <> m.canonical")
    return value(con, "SELECT count(*) FROM idmap WHERE id <> canonical")


# ---------------------------------------------------------------- flags and labels

def flags(con):
    """Creates tables master (one row per species) and master_state (one row per species x state)."""
    src_idx = " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(SOURCES))
    lab_idx = " ".join(f"WHEN '{c}' THEN {i}" for i, c in enumerate(CODES))
    cat_idx = " ".join(f"WHEN '{c}' THEN {i}" for i, c in enumerate(IUCN_CATS))
    con.sql("""
        CREATE OR REPLACE TABLE id_names AS   -- every name of a species: its display name first (p 0)
        SELECT id, name, 0 AS p FROM ids
        UNION SELECT id, name, 1 FROM names_in_r UNION SELECT id, name, 1 FROM evidence_r WHERE name IS NOT NULL
        -- Other names GBIF matched to the species (an older name in GloBI or BOLD, for example).
        UNION SELECT coalesce(m.canonical, a.key), a.name, 2 FROM alias1 a LEFT JOIN idmap m ON m.id = a.key
              WHERE coalesce(m.canonical, a.key) IN (SELECT id FROM ids)
    """)
    # IUCN: the assessed name equal to the display name first, then any accepted name, then a synonym.
    con.sql("""
        CREATE OR REPLACE TABLE id_iucn AS
        SELECT id, a.c AS iucn, a.y AS iucn_year, a.d AS iucn_doi FROM (
            SELECT n.id, arg_min({'c': i.category, 'y': i.year, 'd': i.doi},
                                 n.p * 10 + CASE WHEN i.accepted THEN 0 ELSE 5 END) AS a
            FROM id_names n JOIN iucn i ON i.name = n.name JOIN ids d ON d.id = n.id
            WHERE i.kingdom IS NULL OR d.kingdom IS NULL OR i.kingdom = d.kingdom
            GROUP BY n.id)
    """)
    con.sql("""
        CREATE OR REPLACE TABLE id_globi AS
        SELECT n.id, max(g.partners) AS partners, bool_or(g.india) AS interactions_india
        FROM id_names n JOIN globi g USING (name) GROUP BY n.id
    """)
    con.sql("""
        CREATE OR REPLACE TABLE id_lit AS
        SELECT n.id, sum(l.papers) AS papers, max(l.latest) AS papers_latest
        FROM (SELECT DISTINCT id, name FROM id_names) n JOIN lit l USING (name)
        GROUP BY n.id
    """)
    con.sql("""
        CREATE OR REPLACE TABLE id_bold AS SELECT DISTINCT n.id FROM id_names n JOIN bold b USING (name)
    """)
    con.sql("""
        CREATE OR REPLACE TABLE id_soib AS
        SELECT n.id, bool_or(s.known) AS trend_known FROM id_names n JOIN soib s USING (name) GROUP BY n.id
    """)
    con.sql("""
        CREATE OR REPLACE TABLE id_flags AS
        SELECT i.id, coalesce(bool_or(e.observed), false) AS observed,
               coalesce(bool_or(e.located) FILTER (WHERE e.observed), false) AS located,
               coalesce(bool_or(NOT e.located) FILTER (WHERE e.observed), false) AS unplaced,  -- known to have no exact location
               -- On the list: an open record, or a source other than iNaturalist (whose names are its observations).
               coalesce(bool_or(e.observed), false)
                   OR i.id IN (SELECT id FROM names_in_r WHERE source <> 'iNaturalist') AS listed,
               list(DISTINCT e.label) FILTER (WHERE e.label IS NOT NULL) AS ev_labels
        FROM ids i LEFT JOIN evidence_r e USING (id) GROUP BY i.id
    """)
    con.sql(f"""
        CREATE OR REPLACE TABLE id_sources AS
        WITH s AS (SELECT id, source FROM names_in_r UNION SELECT id, source FROM evidence_r
                   UNION SELECT id, 'IUCN' FROM id_iucn)
        SELECT id, list(source ORDER BY CASE source {src_idx} END) AS sources, sum(1::BIGINT << (CASE source {src_idx} END)) AS sources_mask
        FROM s GROUP BY id
    """)
    con.sql(f"""
        CREATE OR REPLACE TABLE id_labels AS
        WITH l AS (
            SELECT id, unnest(ev_labels) AS code FROM id_flags
            UNION SELECT id, 'chk' FROM id_flags WHERE NOT observed AND listed
            UNION SELECT id, 'lm' FROM id_flags WHERE observed AND NOT located AND unplaced
            UNION SELECT id, 'lgo' FROM id_flags JOIN id_sources USING (id)
                  WHERE observed AND NOT located AND unplaced AND sources = ['GBIF']
            UNION SELECT id, 'end' FROM names_in_r WHERE endemic
            -- Checked only where the paper is the description: same year as the year described.
            UNION SELECT id, 'nra' FROM id_year WHERE json_extract_string(paper, '$[3]') = 'none'
                                                AND json_extract(paper, '$[5]')::INTEGER = year
            UNION SELECT id, 'nm' FROM ids WHERE starts_with(id, 'n:')
            UNION SELECT id, 'do' FROM id_flags
                  WHERE observed AND NOT list_has_any(ev_labels, ['rg', 'nid'])
                    AND (ev_labels = ['dna'] OR (id IN (SELECT key FROM ledger_dna_only)
                                                AND NOT list_has_any(ev_labels, ['ho', 'pap', 'mo']))))
        SELECT id, list(code ORDER BY CASE code {lab_idx} END) AS labels, sum(1::BIGINT << (CASE code {lab_idx} END)) AS labels_mask
        FROM l GROUP BY id
    """)
    con.sql("""
        CREATE OR REPLACE TABLE master_state AS
        SELECT e.id, CASE WHEN NOT starts_with(e.id, 'n:') THEN e.id END AS key, any_value(i.name) AS name, e.state_lgd,
               bool_or(e.source = 'GBIF' AND e.located) AS gbif_located,
               bool_or(e.source = 'GBIF' AND NOT e.located) AS gbif_no_coordinates,
               bool_or(e.label = 'rg') AS inat_research, bool_or(e.label = 'nid') AS inat_needs_id,
               bool_or(e.observed) AS observed, max(e.year) FILTER (WHERE e.observed) AS last_year
        FROM evidence_r e JOIN ids i USING (id) WHERE e.state_lgd IS NOT NULL
        GROUP BY e.id, e.state_lgd ORDER BY state_lgd, name
    """)
    con.sql("""
        CREATE OR REPLACE TABLE id_states AS
        SELECT id, coalesce(list(state_lgd ORDER BY state_lgd) FILTER (WHERE observed), []) AS states_observed,
               max(last_year) AS last_year
        FROM master_state GROUP BY id
    """)
    con.sql(f"""
        CREATE OR REPLACE TABLE master AS
        SELECT i.id, CASE WHEN NOT starts_with(i.id, 'n:') THEN i.id END AS key, i.name, i.grp AS "group",
               list_position({GROUPS!r}, i.grp) - 1 AS gi,
               s.sources, s.sources_mask, f.observed,
               -- 0: on the list, no open record yet; 1: an open record; 2: not on the list, a name that waits.
               CASE WHEN NOT f.listed THEN 2 WHEN f.observed THEN 1 ELSE 0 END AS status,
               coalesce(c.iucn, 'NE') AS iucn, CASE coalesce(c.iucn, 'NE') {cat_idx} END AS iucn_i, c.iucn_year, c.iucn_doi,
               gl.partners, coalesce(gl.interactions_india, false) AS interactions_india,
               i.id IN (SELECT key FROM ledger_trait) AS traits, so.trend_known, gp.places_precise, gp.cells_2km,
               ev.types, ev.photos,
               -- 2: a barcode from India (BOLD); 1: a barcode anywhere (iBOL on GBIF); 0: none.
               CASE WHEN i.id IN (SELECT id FROM id_bold) THEN 2 WHEN ev.barcodes > 0 THEN 1 ELSE 0 END AS barcode,
               ev.names AS local_names, li.papers, li.papers_latest,
               l.labels, l.labels_mask,
               coalesce(t.states_observed, []) AS states_observed, t.last_year,
               y.year, y.authority, y.paper
        FROM ids i JOIN id_flags f USING (id) JOIN id_sources s USING (id) JOIN id_labels l USING (id)
        LEFT JOIN id_iucn c USING (id) LEFT JOIN id_states t USING (id) LEFT JOIN id_year y USING (id)
        LEFT JOIN id_globi gl USING (id) LEFT JOIN id_soib so USING (id) LEFT JOIN gbif_places gp ON gp.key = i.id
        LEFT JOIN evid ev ON ev.key = i.id LEFT JOIN id_lit li ON li.id = i.id
        ORDER BY gi, i.name
    """)
    con.sql("CREATE OR REPLACE VIEW listed AS SELECT * FROM master WHERE status < 2")


# ---------------------------------------------------------------- site files

def states_list(districts_path):
    rows = duckdb.sql(f"SELECT DISTINCT state_lgd, stname FROM '{districts_path}' WHERE state_lgd > 0 ORDER BY 1").fetchall()
    return [{"code": str(c), "name": title(n)} for c, n in rows]


# One species in g/<gi>.json (and at the start of w/<gi>.json rows); the last field is the year described.
ROW_SQL = ("coalesce(s.key, ''), s.name, s.sources_mask, s.status, s.iucn_i, s.labels_mask, s.states_obs_mask, "
           "s.year, s.last_year")


def per_area(rows, n, width):
    """rows (state or None for India, group index, *values) -> (India per group, {state: per group})."""
    india, by_state = [[0] * width for _ in range(n)], {}
    for st, gi, *vals in rows:
        (india if st is None else by_state.setdefault(str(st), [[0] * width for _ in range(n)]))[gi] = [int(v) for v in vals]
    return india, by_state


def group_files(out: Path, folder, rows, every=()):
    """Write <folder>/<gi>.json ({"rows": [...]}) from (group index, row) pairs, replacing the folder.
    every: group indices that get a file even with no rows."""
    shutil.rmtree(out / folder, ignore_errors=True)
    files = {gi: [] for gi in every}
    for gi, row in rows:
        files.setdefault(gi, []).append(row)
    for gi, r in files.items():
        dump({"rows": r}, out / folder / f"{gi}.json")


def state_pairs(states):
    return [[b, int(c)] for b, c in states or []]


def waiting_genus(con, n, out: Path):
    """Observations named only to genus. Per group [genera, observations] for India and per state, and
    wg/<gi>.json rows [genus, taxon, observations in India, [[state index, n]], species of the genus on the list,
    of them with no open record, threatened, endemic]. A genus with no species on the list takes its group from
    its iNaturalist iconic group."""
    end = CODES.index("end")
    # Every name the list knows for a species counts: a source may still use a genus that the Catalogue of
    # Life now treats as a synonym (iNaturalist's Athyma is Limenitis here).
    con.sql(f"""
        CREATE OR REPLACE TABLE genus_stats AS
        WITH n AS (SELECT id, name FROM site UNION SELECT id, name FROM names_in_r
                   UNION SELECT id, name FROM evidence_r WHERE name IS NOT NULL
                   UNION SELECT coalesce(m.canonical, a.key), a.name FROM alias a LEFT JOIN idmap m ON m.id = a.key
                   WHERE a.key IS NOT NULL),
        g AS (SELECT DISTINCT split_part(n.name, ' ', 1) AS genus, i.kingdom, s.*
              FROM n JOIN site s USING (id) JOIN ids i USING (id) WHERE s.status < 2)
        SELECT genus, kingdom, mode(gi) AS gi, count(*) AS docs,
               count(*) FILTER (WHERE NOT observed) AS unid, count(*) FILTER (WHERE iucn IN {THREATENED}) AS threat,
               count(*) FILTER (WHERE (labels_mask >> {end}) & 1 = 1) AS endemic
        FROM g GROUP BY 1, 2""")
    # A genus name can belong to a plant and to an animal: match the kingdom when both sides know it.
    iconic = " ".join(f"WHEN '{k}' THEN {GROUPS.index(v)}" for k, v in ICONIC_GROUP.items())
    kingdom = " ".join(f"WHEN '{k}' THEN '{v[0]}'" for k, v in INAT_HINTS.items())
    con.sql(f"""
        CREATE OR REPLACE TABLE wait_genus AS
        WITH g AS (SELECT *, CASE iconic {kingdom} END AS hk FROM inat_genus),
        m AS (SELECT g.genus, g.hk, arg_min(s, CASE WHEN s.kingdom = g.hk THEN 0 ELSE 1 END) AS s
              FROM (SELECT DISTINCT genus, hk FROM g) g JOIN genus_stats s
                ON s.genus = g.genus AND (s.kingdom IS NULL OR g.hk IS NULL OR s.kingdom = g.hk)
              GROUP BY ALL)
        SELECT g.* EXCLUDE (hk), coalesce(m.s.gi, CASE g.iconic {iconic} ELSE {GROUPS.index("Other")} END) AS gi,
               coalesce(m.s.docs, 0) AS docs, coalesce(m.s.unid, 0) AS unid, coalesce(m.s.threat, 0) AS threat,
               coalesce(m.s.endemic, 0) AS endemic
        FROM g LEFT JOIN m ON m.genus = g.genus AND m.hk IS NOT DISTINCT FROM g.hk""")
    india, by_state = per_area(con.sql(
        "SELECT state_lgd, gi, count(DISTINCT genus), sum(n) FROM wait_genus GROUP BY ALL").fetchall(), n, 2)
    group_files(out, "wg", ((gi, [genus, taxon, int(n_india), state_pairs(states), docs, unid, threat, endemic])
                            for gi, genus, taxon, n_india, states, docs, unid, threat, endemic in con.sql("""
            SELECT w.gi, w.genus, any_value(w.taxon), coalesce(sum(w.n) FILTER (WHERE w.state_lgd IS NULL), 0),
                   list([b.b, w.n] ORDER BY b.b) FILTER (WHERE b.b IS NOT NULL),
                   any_value(w.docs), any_value(w.unid), any_value(w.threat), any_value(w.endemic)
            FROM wait_genus w LEFT JOIN state_bit b USING (state_lgd)
            GROUP BY w.gi, w.genus ORDER BY w.gi, w.genus""").fetchall()))
    return {"india": india, "by_state": by_state}


def waiting(con, n, out: Path, places, coarse=None):
    """iNaturalist observations that wait for a name (needs ID), per species and area.
    Returns the summary part: per group [species, observations, species with no open record in that area],
    for India and per state. Writes w/<gi>.json: the species' g/<gi>.json row (key, name, sources, status, IUCN, labels,
    states with an open record, year), then iNaturalist taxon, observations in India, [[state index, observations], ...], so the
    site can rank each species and link it to iNaturalist's Identify page without the group file."""
    con.sql("""
        CREATE OR REPLACE TABLE wait AS
        WITH m AS (SELECT DISTINCT name, id FROM evidence_r WHERE source = 'iNaturalist' AND label = 'nid'),
        w AS (SELECT m.id, w.* FROM inat_wait w JOIN m USING (name)),
        t AS (SELECT id, arg_min(taxon, CASE WHEN raw = name THEN 0 ELSE 1 END) AS taxon FROM w GROUP BY id)
        SELECT w.id, w.state_lgd, any_value(t.taxon) AS taxon, sum(w.n) AS n
        FROM w JOIN t USING (id) GROUP BY w.id, w.state_lgd
    """)
    # "First": no open record in that area (India: anywhere; a state: in that state).
    india, by_state = per_area(con.sql("""
            SELECT w.state_lgd, s.gi, count(*), sum(w.n),
                   count(*) FILTER (WHERE CASE WHEN w.state_lgd IS NULL THEN NOT s.observed
                                               ELSE NOT list_contains(s.states_observed, w.state_lgd) END)
            FROM wait w JOIN site s USING (id) GROUP BY ALL""").fetchall(), n, 3)
    group_files(out, "w", ((gi, [*row, taxon, int(n_india), state_pairs(states)])
                           for gi, *row, taxon, n_india, states in con.sql(f"""
        SELECT s.gi, {ROW_SQL}, any_value(w.taxon), coalesce(sum(w.n) FILTER (WHERE w.state_lgd IS NULL), 0),
               list([b.b, w.n] ORDER BY b.b) FILTER (WHERE b.b IS NOT NULL)
        FROM wait w JOIN site s USING (id) LEFT JOIN state_bit b USING (state_lgd)
        GROUP BY ALL ORDER BY s.gi, s.name""").fetchall()))
    counts = (coarse or {}).get("counts", {})
    return {"places": places, "india": india, "by_state": by_state, "genus": waiting_genus(con, n, out),
            "coarse": {"india": counts.get("india", {}), "by_state": {k: v for k, v in counts.items() if k != "india"}}}


def species_files(con, out: Path):
    """sp/<shard>.json for the species page: {key: [name, group index, sources, status, IUCN, labels,
    states with an open record, iNaturalist taxon, observations waiting in India, [[state index, n]],
    year described, authority, paper of a new species [sources, journal, link, after the description, latest year
    after, year of the paper], year and DOI of the IUCN assessment (from IUCN's CC BY copy on GBIF), GloBI partner
    species (null: no recorded interaction), an interaction recorded in India, 2 km cells with an open record placed in
    India (area of occupancy; null: not counted), records from India with a type status, records from India with a
    photo, DNA barcode (2: from India, BOLD; 1: anywhere, iBOL on GBIF; 0: none), names in Indian languages
    [[language code, name]], a known population trend (State of India's Birds; null: not covered), a record placed in
    India with a trait, places with an exact record (null: not counted), papers in the Bibliography of South Asian
    Ornithology and the year of the latest (birds; null: none)]}.
    Shards as for the snapshot's species files (site_data.shard_of). Names with no key have no page."""
    shutil.rmtree(out / "sp", ignore_errors=True)
    parts = {}
    for key, *row, taxon, n_india, states, year, authority, paper, iucn_year, iucn_doi, partners, inter_india, cells, \
            types, photos, barcode, names, trend, traits, precise, papers, papers_latest in con.sql("""
            SELECT s.key, s.name, s.gi, s.sources_mask, s.status, s.iucn_i, s.labels_mask, s.states_obs_mask,
                   any_value(w.taxon), coalesce(sum(w.n) FILTER (WHERE w.state_lgd IS NULL), 0),
                   list([b.b, w.n] ORDER BY b.b) FILTER (WHERE b.b IS NOT NULL), s.year, s.authority, s.paper,
                   s.iucn_year, s.iucn_doi, s.partners, s.interactions_india, s.cells_2km,
                   s.types, s.photos, s.barcode, s.local_names, s.trend_known, s.traits, s.places_precise,
                   s.papers, s.papers_latest
            FROM site s LEFT JOIN wait w USING (id) LEFT JOIN state_bit b ON b.state_lgd = w.state_lgd
            WHERE s.key IS NOT NULL GROUP BY ALL""").fetchall():
        parts.setdefault(shard_of(key), {})[key] = [*row, taxon, int(n_india), state_pairs(states), year, authority,
                                                    json.loads(paper) if paper else None, iucn_year, iucn_doi,
                                                    partners, inter_india, cells, types, photos, barcode,
                                                    [[x["lang"], x["name"]] for x in names] if names else None,
                                                    trend, traits, precise, papers, papers_latest]
    for i, part in parts.items():
        dump(part, out / "sp" / f"{i}.json")


# Kinds of link, from the species' own side: a GloBI type and whether the species is its subject (outgoing).
WEB_TOP = 30   # partners kept per species and kind of link (the most records first); the total is kept too
WEB_FEEDS = ("eats", "preysOn", "kills")
WEB_FLOWERS = ("pollinates", "visitsFlowersOf", "visits", "dispersesSeedsOf", "hasDispersalVector")
WEB_LIVES = ("hasHost", "parasiteOf", "pathogenOf", "ectoparasiteOf", "endoparasiteOf", "parasitoidOf",
             "endoparasitoidOf", "kleptoparasiteOf", "hyperparasiteOf", "epiphyteOf", "laysEggsOn", "livesOn",
             "livesInsideOf", "hasVector", "hasReservoirHost")


def web_files(con, edges, out: Path):
    """web/<shard>.json for the species web: {key: {"n": {kind: partners}, "p": {kind: [[partner name, its key on the
    list or null, records, records in India, [GloBI types]]]}}}, the WEB_TOP partners with most records per kind.
    Kinds: eats, eaten (by), flowers (pollinates, visits, disperses seeds, from either side), lives (on or in a host),
    hosts, other. A partner is a species on the list when one of its names is (synonyms count), else GloBI's name."""
    from pipeline.site_data import shard_of
    shutil.rmtree(out / "web", ignore_errors=True)
    q = lambda xs: "(" + ", ".join(f"'{x}'" for x in xs) + ")"
    con.sql("CREATE OR REPLACE TABLE name_id AS SELECT name, arg_min(id, p) AS id FROM id_names GROUP BY name")
    con.sql(f"""
        CREATE OR REPLACE TABLE web AS
        WITH e AS (
            SELECT n.id, x.partner, x.type, x.records, x.records_india,
                   CASE WHEN x.type IN {q(WEB_FEEDS)} THEN CASE WHEN x.outgoing THEN 'eats' ELSE 'eaten' END
                        WHEN x.type IN {q(WEB_FLOWERS)} THEN 'flowers'
                        WHEN x.type IN {q(WEB_LIVES)} THEN CASE WHEN x.outgoing THEN 'lives' ELSE 'hosts' END
                        ELSE 'other' END AS kind
            FROM '{edges}' x JOIN name_id n ON n.name = x.name
            WHERE n.id IN (SELECT id FROM listed WHERE key IS NOT NULL)),
        p AS (
            SELECT e.id, e.kind, coalesce(i.name, e.partner) AS pname,
                   CASE WHEN NOT starts_with(m.id, 'n:') THEN m.id END AS pkey,
                   sum(e.records) AS records, sum(e.records_india) AS india, list(DISTINCT e.type ORDER BY e.type) AS types
            FROM e LEFT JOIN name_id m ON m.name = e.partner LEFT JOIN ids i ON i.id = m.id
            WHERE m.id IS NULL OR m.id <> e.id
            GROUP BY e.id, e.kind, coalesce(m.id, e.partner), coalesce(i.name, e.partner), pkey)
        SELECT id, kind, pname, pkey, records, india, types,
               row_number() OVER (PARTITION BY id, kind ORDER BY records DESC, pname) AS rank,
               count(*) OVER (PARTITION BY id, kind) AS total
        FROM p""")
    parts = {}
    for key, kind, total, rows in con.sql(f"""
            SELECT id, kind, any_value(total), list({{'n': pname, 'k': pkey, 'r': records, 'i': india, 't': types}} ORDER BY rank)
            FROM web WHERE rank <= {int(WEB_TOP)} GROUP BY id, kind ORDER BY id, kind""").fetchall():
        sp = parts.setdefault(shard_of(key), {}).setdefault(key, {"n": {}, "p": {}})
        sp["n"][kind] = total
        sp["p"][kind] = [[r["n"], r["k"], int(r["r"]), int(r["i"]), r["t"]] for r in rows]
    for i, part in parts.items():
        dump(part, out / "web" / f"{i}.json")
    return len(parts)


def described_summary(con):
    """Range of the years described, and how many species have no year in the sources."""
    lo, hi, unknown = first(con, "SELECT min(year), max(year), count(*) FILTER (WHERE year IS NULL) FROM listed")
    return {"from": lo, "to": hi, "unknown": unknown}


RECENT_YEARS = 10
ASSESSABLE_STATES = 5   # not assessed by IUCN, but with open records in this many states or more
NICHE_PLACES = 10       # places with an exact record (1 km or better): a common minimum to relate a species to climate maps
EVIDENCE = ["types", "photos", "barcodes", "barcodes_india", "local_names"]
REDLIST = ["assessed", "assessable", "out_of_date", "dd_newer", "threatened_not_recent", "endemic_not_assessed"]


def recent_from(period):
    """The first year that counts as recent for a list: 10 years before the list's year ("2026-10-26" -> 2016).
    A period with no year (a test) counts from this year."""
    year = int(period[:4]) if str(period)[:4].isdigit() else time.gmtime().tm_year
    return year - RECENT_YEARS


def group_totals(con, species_sql, n, since=None):
    """Per group [documented, with an open record, [species per IUCN category], threatened with an open record,
    open record in a state, of them recorded in a state in `since` or later (None when since is None)], from SQL that
    gives the species on a list with gi, iucn, observed, states_observed and last_year."""
    india = [[0, 0, [0] * len(IUCN_CATS), 0, 0, None if since is None else 0] for _ in range(n)]
    recent = f"last_year >= {int(since)}" if since is not None else "false"
    for gi, cat, docs, obs, thr, placed, rec in con.sql(f"""
            SELECT gi, coalesce(iucn, 'NE'), count(*), count(*) FILTER (WHERE observed),
                   count(*) FILTER (WHERE observed AND iucn IN {THREATENED}),
                   count(*) FILTER (WHERE observed AND len(states_observed) > 0),
                   count(*) FILTER (WHERE observed AND len(states_observed) > 0 AND {recent})
            FROM ({species_sql}) WHERE gi >= 0 GROUP BY ALL""").fetchall():
        row = india[gi]
        row[0] += docs; row[1] += obs; row[2][IUCN_CATS.index(cat)] += docs; row[3] += thr; row[4] += placed
        if since is not None:
            row[5] += rec
    return india


def site_files(con, out: Path, meta, districts_path, notes, places=None, coarse=None):
    """summary.json, g/<gi>.json, w/<gi>.json, search/<p>.json and search/places.json (format agreed with the site)."""
    states = states_list(districts_path)
    bit = {int(s["code"]): i for i, s in enumerate(states)}
    con.execute("CREATE OR REPLACE TABLE state_bit AS SELECT unnest($1) AS state_lgd, unnest($2) AS b",
                [list(bit), list(bit.values())])
    con.sql("""
        CREATE OR REPLACE TABLE site AS
        SELECT m.*, coalesce((SELECT sum(1::BIGINT << b) FROM state_bit WHERE list_contains(m.states_observed, state_lgd)), 0)
                    AS states_obs_mask
        FROM master m
    """)
    shutil.rmtree(out / "search", ignore_errors=True)
    n = len(GROUPS)
    since = recent_from(meta["period"])
    india = group_totals(con, "SELECT gi, iucn, observed, states_observed, last_year FROM listed", n, since)
    # Per state and group [with an open record, threatened with an open record, recorded there since `since`].
    by_state = {}
    for st, gi, obs, thr, rec in con.sql(f"""
            SELECT s.state_lgd, m.gi, count(*) FILTER (WHERE s.observed),
                   count(*) FILTER (WHERE s.observed AND m.iucn IN {THREATENED}),
                   count(*) FILTER (WHERE s.observed AND s.last_year >= {since})
            FROM master_state s JOIN listed m USING (id)
            GROUP BY ALL""").fetchall():
        by_state.setdefault(str(st), [[0, 0, 0] for _ in range(n)])[gi] = [obs, thr, rec]
    # Per group, in one pass: names not on the list, known only from observations that wait for a name (status 2);
    # the Linnean gap, species on the list described in `since` or later; the Darwinian gap, species on the list with
    # a DNA sequence or sample from India on GBIF (label dna).
    # Red List assessments, from IUCN's CC BY copy (category, year) with the list's own records: assessed; not
    # assessed but with open records in ASSESSABLE_STATES states or more; assessed before `since` (IUCN aims to
    # reassess every 5-10 years); Data Deficient with a placed record after the assessment; threatened with no placed
    # record since `since`; endemic and not assessed.
    unlisted, described_recent, dna = ([0] * n for _ in range(3))
    redlist = {k: [0] * n for k in REDLIST}
    interactions, interactions_india = [0] * n, [0] * n   # the Eltonian gap (GloBI)
    traits = [0] * n   # the Raunkiæran gap: a record placed in India with a life stage, a sex, or flowers or fruits
    # The Prestonian gap: species with a known population trend (State of India's Birds), null for a group it does not cover.
    trend_known = [None] * n
    niche = [0] * n   # the Hutchinsonian gap: records placed to 1 km or better at NICHE_PLACES places or more
    # Evidence per species: a type specimen and a photo from India (Linnean), a DNA barcode anywhere and from India
    # (Darwinian), a name in an Indian language.
    evidence = {k: [0] * n for k in EVIDENCE}
    papers = [None] * n   # birds with a paper in the Bibliography of South Asian Ornithology (it covers birds only)
    for gi, u, d, s, ia, ii, tr, tk, ni, pa, *rest in con.sql(f"""
            SELECT gi, count(*) FILTER (WHERE status = 2), count(*) FILTER (WHERE status < 2 AND year >= {since}),
                   count(*) FILTER (WHERE status < 2 AND list_contains(labels, 'dna')),
                   count(*) FILTER (WHERE status < 2 AND partners IS NOT NULL),
                   count(*) FILTER (WHERE status < 2 AND interactions_india),
                   count(*) FILTER (WHERE status < 2 AND traits),
                   CASE WHEN bool_or(trend_known IS NOT NULL) THEN count(*) FILTER (WHERE status < 2 AND trend_known) END,
                   count(*) FILTER (WHERE status < 2 AND places_precise >= {NICHE_PLACES}),
                   count(*) FILTER (WHERE status < 2 AND papers > 0),
                   count(*) FILTER (WHERE status < 2 AND types > 0), count(*) FILTER (WHERE status < 2 AND photos > 0),
                   count(*) FILTER (WHERE status < 2 AND barcode > 0), count(*) FILTER (WHERE status < 2 AND barcode = 2),
                   count(*) FILTER (WHERE status < 2 AND len(local_names) > 0),
                   count(*) FILTER (WHERE status < 2 AND iucn <> 'NE'),
                   count(*) FILTER (WHERE status < 2 AND iucn = 'NE' AND observed AND len(states_observed) >= {ASSESSABLE_STATES}),
                   count(*) FILTER (WHERE status < 2 AND iucn <> 'NE' AND iucn_year < {since}),
                   count(*) FILTER (WHERE status < 2 AND iucn = 'DD' AND last_year > iucn_year),
                   count(*) FILTER (WHERE status < 2 AND iucn IN {THREATENED} AND NOT coalesce(last_year >= {since}, false)),
                   count(*) FILTER (WHERE status < 2 AND iucn = 'NE' AND list_contains(labels, 'end'))
            FROM master GROUP BY gi""").fetchall():
        unlisted[gi], described_recent[gi], dna[gi], interactions[gi], interactions_india[gi], traits[gi] = u, d, s, ia, ii, tr
        trend_known[gi], niche[gi] = tk, ni
        if GROUPS[gi] == "Birds":
            papers[gi] = pa
        for k, v in zip(EVIDENCE, rest):
            evidence[k][gi] = v
        for k, v in zip(REDLIST, rest[len(EVIDENCE):]):
            redlist[k][gi] = v
    totals = {"documented": sum(r[0] for r in india), "observed": sum(r[1] for r in india),
              "in_state": sum(r[4] for r in india), "recent": sum(r[5] for r in india), "unlisted": sum(unlisted),
              "described_recent": sum(described_recent), "dna": sum(dna),
              "redlist": {k: sum(v) for k, v in redlist.items()}}
    measured = value(con, "SELECT count(*) > 0 FROM globi")   # no GloBI table: not measured, not 0
    if measured:
        totals.update(interactions=sum(interactions), interactions_india=sum(interactions_india))
    traits_measured = value(con, "SELECT count(*) > 0 FROM ledger_trait")   # an older ledger: not measured, not 0
    if traits_measured:
        totals["traits"] = sum(traits)
    papers_measured = value(con, "SELECT count(*) > 0 FROM lit")
    if papers_measured:
        totals["papers"] = sum(p or 0 for p in papers)
    evidence_measured = value(con, "SELECT count(*) > 0 FROM evid")   # no evidence table: not measured, not 0
    if evidence_measured:
        totals.update({k: sum(v) for k, v in evidence.items()})
    summary = {**meta, "sources": SOURCES,
               "labels": [{"code": c, "name": nm, "kind": k} for c, nm, k in LABELS],
               "iucn": IUCN_CATS, "groups": GROUPS, "states": states, "india": india, "by_state": by_state,
               "unlisted": unlisted, "described_recent": described_recent, "dna": dna, "redlist": redlist,
               "interactions": interactions if measured else None,
               "interactions_india": interactions_india if measured else None,
               "traits": traits if traits_measured else None,
               "trend_known": trend_known if any(v is not None for v in trend_known) else None,
               "niche": niche if value(con, "SELECT count(places_precise) > 0 FROM gbif_places") else None,
               **{k: v if evidence_measured else None for k, v in evidence.items()},
               "papers": papers if papers_measured else None,
               "recent_from": since,
               "waiting": waiting(con, n, out, places or {}, coarse),
               "totals": totals, "described": described_summary(con), "notes": notes, **RIGHTS}
    dump(summary, out / "summary.json")
    species_files(con, out)
    group_files(out, "g", ((gi, row) for gi, *row in con.sql(
        f"SELECT gi, {ROW_SQL} FROM site s WHERE status < 2 ORDER BY gi, s.name").fetchall()), range(n))
    buckets = {}
    for r in con.sql("""SELECT name, coalesce(key, ''), gi, status, iucn_i, sources_mask, labels_mask, year
                        FROM site ORDER BY lower(name), name""").fetchall():
        buckets.setdefault(prefix(r[0]), []).append(list(r))
    for p, rows in buckets.items():
        dump({"rows": rows}, out / "search" / f"{p}.json")
    places = [[title(nm), "state", int(code), int(code)] for code, nm in
              duckdb.sql(f"SELECT DISTINCT state_lgd, stname FROM '{districts_path}' WHERE state_lgd > 0").fetchall()]
    places += [[title(nm), "district", int(d), int(s)] for d, s, nm in
               duckdb.sql(f"SELECT dist_lgd, state_lgd, dtname FROM '{districts_path}' WHERE dist_lgd > 0").fetchall()]
    dump({"rows": sorted(places, key=lambda r: (r[0].lower(), r[1]))}, out / "search" / "places.json")
    return summary


# ---------------------------------------------------------------- changes since the previous list

CHANGE_KINDS = ("observed", "state", "documented", "dropped", "iucn")


def previous_list(con, parquet):
    """SQL for a published master.parquet as today's rule reads it: the species on the list, with key, name, gi,
    sources, observed (an open record), states_observed and iucn. Lists up to 2026-10-26 (with an identified column)
    counted iNaturalist needs ID as observed: there an open record is identified, or a record under the name as
    published (observed, in no state), and a species named only by iNaturalist (and IUCN) was not on the list."""
    cols = {c for (c, *_) in con.sql(f"DESCRIBE SELECT * FROM '{parquet}'").fetchall()}
    iucn = "iucn" if "iucn" in cols else "NULL::VARCHAR AS iucn"
    base = f"""coalesce(key, 'n:' || name) AS id, key, name, list_position({GROUPS!r}, "group") - 1 AS gi, sources, {iucn}"""
    if "identified" not in cols:
        return f"SELECT {base}, observed, states_observed FROM '{parquet}'"
    return f"""SELECT * FROM (
        SELECT {base}, identified OR list_contains(labels, 'vn') AS observed, states_identified AS states_observed
        FROM '{parquet}')
        WHERE observed OR len(list_filter(sources, lambda s: s NOT IN ('iNaturalist', 'IUCN'))) > 0"""


def changes(con, prev_parquet, prev_period, period_id, n_groups=len(GROUPS)):
    """Species that moved between the previous master list (a master.parquet) and this one (table master).
    Kinds: observed (a first open record in India), state (a first open record in a state), documented (new on the
    list), dropped (no longer on the list: renamed, merged, or left out as not from India), iucn (IUCN Red List
    category changed; the row ends with [before, now]).
    rows: [kind, key, name, group index, [states new for the species], [sources new for the species]]."""
    if not prev_parquet:
        return {"from": None, "to": period_id}
    p = previous_list(con, prev_parquet)
    rows = con.sql(f"""
        WITH p AS ({p}),
        c AS (SELECT key, name, gi, sources, observed, states_observed, coalesce(key, 'n:' || name) AS id
              FROM master WHERE status < 2),
        j AS (SELECT c.*, p.id IS NOT NULL AS was, p.observed AS p_obs,
                     list_filter(c.states_observed, lambda s: NOT list_contains(coalesce(p.states_observed, []), s)) AS new_states,
                     list_filter(c.sources, lambda s: NOT list_contains(coalesce(p.sources, []), s)) AS new_sources
              FROM c LEFT JOIN p USING (id))
        SELECT CASE WHEN NOT was THEN 'documented'
                    WHEN observed AND NOT p_obs THEN 'observed'
                    WHEN len(new_states) > 0 THEN 'state' END AS kind,
               coalesce(key, ''), name, gi, new_states, new_sources
        FROM j WHERE kind IS NOT NULL
        UNION ALL
        SELECT 'dropped', coalesce(key, ''), name, gi, [], [] FROM p WHERE id NOT IN (SELECT id FROM c)
        ORDER BY 1, 3""").fetchall()
    rows = [list(r) for r in rows]
    if "iucn" in {c for (c, *_) in con.sql("DESCRIBE master").fetchall()}:
        rows += [[*r[:4], [], [], [r[4], r[5]]] for r in con.sql(f"""
            SELECT 'iucn', coalesce(c.key, ''), c.name, c.gi, p.iucn, c.iucn
            FROM master c JOIN ({p}) p ON coalesce(c.key, 'n:' || c.name) = p.id
            WHERE c.status < 2 AND c.iucn IS NOT NULL AND c.iucn IS DISTINCT FROM p.iucn ORDER BY c.name""").fetchall()]
    counts = dict.fromkeys(CHANGE_KINDS, 0)
    groups = [[0, 0, 0] for _ in range(n_groups)]
    col = {"documented": 0, "observed": 1, "state": 2}
    for kind, _, _, gi, *_ in rows:
        counts[kind] += 1
        if kind in col and gi is not None and 0 <= gi < n_groups:
            groups[gi][col[kind]] += 1
    return {"from": prev_period, "to": period_id, "counts": counts, "groups": groups,
            "rows": [[k, key, name, gi, list(st), list(src), *extra] for k, key, name, gi, st, src, *extra in rows]}


# Measures of the weekly history (history.json), for India and per group.
MEASURES = ["documented", "unlisted", "observed", "in_state", "recent", "threatened", "waiting_species",
            "waiting_observations", "described_recent", "dna", "interactions", "interactions_india", "traits"]


def history_entry(summary):
    """One list's totals from its summary.json: per group [documented, not on the list (named only in observations
    that wait), with an open record, of them in a state, of them recorded in the last 10 years, threatened (IUCN CR,
    EN or VU), species and observations on iNaturalist named to species but not yet confirmed (needs ID)], and their
    sum for India; then species described in the last 10 years (the Linnean gap) and species with a DNA sequence or
    sample (the Darwinian gap). A measure a summary does not have (older lists) is null, not 0."""
    threat = [IUCN_CATS.index(c) for c in THREATENED]
    waiting = (summary.get("waiting") or {}).get("india") or []
    own = lambda key, gi: summary[key][gi] if summary.get(key) else None
    groups = []
    for gi, (d, o, cats, *rest) in enumerate(summary["india"]):
        placed, recent = (rest[1:3] + [None, None])[:2]
        groups.append([d, own("unlisted", gi), o, placed, recent, sum(cats[k] for k in threat),
                       *(waiting[gi][:2] if gi < len(waiting) else [0, 0]), own("described_recent", gi), own("dna", gi),
                       own("interactions", gi), own("interactions_india", gi), own("traits", gi)])
    india = [None if any(v is None for v in col) else sum(col) for col in zip(*groups)]
    return {"period": summary.get("period") or summary.get("month"), "india": india, "groups": groups}


def upgrade_history(h):
    """A history.json with other measures, read as today's: each value under its measure's name, null for a measure
    it did not have. A history from before open records (with identified) counted other things: None."""
    if not h or h.get("measures") == MEASURES:
        return h
    if "identified" in h.get("measures", []):
        return None
    at = {m: i for i, m in enumerate(h["measures"])}
    pick = lambda row: [row[at[m]] if m in at else None for m in MEASURES]
    return {**h, "measures": MEASURES, "lists": [{**e, "india": pick(e["india"]), "groups": [pick(g) for g in e["groups"]]}
                                                  for e in h["lists"]]}


def previous_summary(con, prev):
    """The previous list's summary.json, or, for a list from before open records (its totals have identified), its
    per-group totals read from its master.parquet with today's rule (previous_list); the waiting counts are its own."""
    s = (prev or {}).get("summary")
    if not s or "identified" not in (s.get("totals") or {}):
        return s
    india = group_totals(con, previous_list(con, prev["parquet"]), len(s["groups"]))
    return {**s, "india": india, "totals": {"documented": sum(r[0] for r in india), "observed": sum(r[1] for r in india)}}


def next_history(prev, summary):
    """This list's history: the previous list's history (or, for a list from before history.json or from before
    open records, one built from its summary) with this list added. prev: previous_layer() or None."""
    base = upgrade_history((prev or {}).get("history"))
    if not base and (prev or {}).get("summary"):
        base = history(None, prev["summary"])
    return history(base, summary)


def history(prev, summary):
    """history.json: the totals of every list so far, oldest first. This list replaces an entry of the same period."""
    entry = history_entry(summary)
    lists = [e for e in (prev or {}).get("lists", []) if e["period"] != entry["period"]] + [entry]
    return {"measures": MEASURES, "groups": summary["groups"], "lists": sorted(lists, key=lambda e: e["period"])}


def previous_period(latest, period):
    """The list to compare this one with: the period layers/master/latest.json names, or, when that is this period
    already (a second run in the same week), the one it names as previous. Monthly ids ("2026-10") sort before weekly
    ones ("2026-10-26"), so the first weekly list compares with the last monthly one."""
    if not latest:
        return None
    published = latest.get("period") or latest.get("month")
    if published == period:
        return latest.get("previous")
    return published if published and published < period else None


def build_id(built):
    """A build's folder name from its build time: "2026-10-28T16:00:44Z" -> "20261028T160044Z" (sorts in time order)."""
    return built.replace("-", "").replace(":", "")


BUILD_RE = re.compile(r"\d{8}T\d{6}Z")
KEEP_BUILDS = 2   # per week: the current build and the one before (a page open during the switch still finds its files)


def period_base(s3, period):
    """R2 prefix of a week's current build, from layers/master/<period>/current.json. Lists from before builds had
    their files in layers/master/<period>/ itself."""
    from pipeline import r2
    ptr = r2.get_json(s3, f"layers/master/{period}/current.json")
    return ptr["base"] if ptr else f"layers/master/{period}/"


def previous_layer(s3, period):
    """The previous master list: {"parquet", "period", "summary", "history"}, or None. With R2, the build its pointer
    names (never a local copy, which can be out of date); without, the newest local folder before this period."""
    from pipeline import r2
    if s3:
        pm = previous_period(r2.get_json(s3, "layers/master/latest.json"), period)
        if not pm:
            return None
        base = period_base(s3, pm)
        parquet = r2_file(s3, base + "master.parquet", CACHE / f"master_{pm}.parquet")
        if not parquet:
            return None
        return {"parquet": parquet, "period": pm, "summary": r2.get_json(s3, base + "summary.json"),
                "history": r2.get_json(s3, base + "history.json")}
    older = sorted(p.name for p in (LAYERS / "master").glob("*") if p.is_dir() and p.name < period)
    if not older or not (LAYERS / "master" / older[-1] / "master.parquet").exists():
        return None
    folder = LAYERS / "master" / older[-1]
    read = lambda name: json.loads((folder / name).read_text()) if (folder / name).exists() else None
    return {"parquet": folder / "master.parquet", "period": older[-1], "summary": read("summary.json"),
            "history": read("history.json")}


def waiting_total(summary):
    return sum(g[1] for g in ((summary or {}).get("waiting") or {}).get("india", [])) if summary else None


# ---------------------------------------------------------------- build

def build(con, paths, out: Path, meta, districts_path, inputs, cache=None, s3=None, deadline=None, http=None,
          match=True, prev=None):
    """Load every input present, match names, flag, label and write the layer. inputs: {name: path or doc or None}."""
    notes = []
    start(con)
    has_dna = load_gbif(con, paths)
    if not has_dna:
        notes.append("The label \"DNA only\" uses the record type only: this snapshot's GBIF data does not mark DNA sequences.")
    if not paths.get("unlocated"):
        notes.append("This snapshot's GBIF data does not include records that cannot go in a district, so no species has the label \"No exact location\" yet.")
    if inputs.get("zsi"):
        load_zsi(con, inputs["zsi"])
    if inputs.get("wcvp"):
        load_wcvp(con, inputs["wcvp"])
    if inputs.get("lichens"):
        load_lichens(con, inputs["lichens"])
    else:
        notes.append("The lichen checklist of India was not found: lichens are listed only from records and BSI.")
    if inputs.get("bryophytes"):
        load_bryophytes(con, inputs["bryophytes"])
    else:
        notes.append("The bryophyte checklist of India was not found: mosses and liverworts are listed only from records.")
    if inputs.get("bsi_monographs"):
        load_bsi(con, inputs["bsi_monographs"])   # BSI's regional and family books on lichens, algae and fungi
    if inputs.get("bsi"):
        load_bsi(con, inputs["bsi"])
    else:
        notes.append("BSI checklists are not loaded yet; BSI counts only the yearly BSI Plant Discoveries editions.")
    if inputs.get("inat"):
        load_inat(con, inputs["inat"])
        if not inputs["inat"].get("complete"):
            notes.append("iNaturalist species lists are incomplete (the daily request budget); the next run adds the rest.")
    else:
        notes.append("iNaturalist species lists are not fetched yet: research grade and needs ID are empty.")
    if inputs.get("inat_genus"):
        load_inat_genus(con, inputs["inat_genus"])
    if inputs.get("newspecies"):
        load_newspecies(con, inputs["newspecies"])
    load_described(con, inputs.get("described") or {})
    # GloBI: a recorded interaction anywhere (partners: distinct partner species), and one recorded in India.
    if inputs.get("globi"):
        con.sql(f"""CREATE OR REPLACE TABLE globi AS
                    SELECT name, partners, records_india > 0 AS india FROM '{inputs["globi"]}'""")
    else:
        con.sql("CREATE OR REPLACE TABLE globi (name VARCHAR, partners BIGINT, india BOOLEAN)")
        notes.append("GloBI's species table was not found: the Eltonian gap (interactions) is not measured.")
    # The Bibliography of South Asian Ornithology (pipeline/zotero.py): papers per bird name.
    if inputs.get("zotero"):
        con.sql(f"""CREATE OR REPLACE TABLE lit AS SELECT name, papers::BIGINT AS papers, latest_year::INTEGER AS latest
                    FROM read_csv('{inputs["zotero"]}', header = true, all_varchar = true)""")
    else:
        con.sql("CREATE OR REPLACE TABLE lit (name VARCHAR, papers BIGINT, latest INTEGER)")
        notes.append("The Bibliography of South Asian Ornithology was not found: papers per bird are not counted.")
    if inputs.get("soib"):
        from pipeline import soib
        con.sql(f"CREATE OR REPLACE TABLE soib AS {soib.trends_sql(inputs['soib'])}")
    else:
        con.sql("CREATE OR REPLACE TABLE soib (name VARCHAR, assessed BOOLEAN, known BOOLEAN)")
        notes.append("State of India's Birds was not found: the Prestonian gap (population trends) is not measured.")
    # Evidence per species (pipeline/evidence.py): type specimens and photos from India and barcodes anywhere
    # (GBIF), barcodes from India (BOLD, by name), names in Indian languages (Wikidata).
    if inputs.get("evidence"):
        con.sql(f"CREATE OR REPLACE TABLE evid AS SELECT * FROM '{inputs['evidence']}'")
    else:
        con.sql("CREATE OR REPLACE TABLE evid (key VARCHAR, types BIGINT, photos BIGINT, barcodes BIGINT, "
                "names STRUCT(lang VARCHAR, name VARCHAR)[])")
        notes.append("The evidence table was not found: type specimens, photos, DNA barcodes and local names are not measured.")
    if inputs.get("bold"):
        con.sql(f"CREATE OR REPLACE TABLE bold AS SELECT name FROM read_csv('{inputs['bold']}', header = true)")
    else:
        con.sql("CREATE OR REPLACE TABLE bold (name VARCHAR)")
    if not inputs.get("zsi"):
        notes.append("ZSI checklists not found.")
    if not inputs.get("wcvp"):
        notes.append("Kew WCVP not found.")
    cache = {} if cache is None else cache
    add_matches(con, cache)
    pending = to_match(con, cache)
    if match and pending:
        print(f"{len(pending)} names to match with GBIF", flush=True)
        match_names(pending, cache, s3, deadline, http)
        add_matches(con, cache)
        pending = to_match(con, cache)
    if pending:
        notes.append(f"{len(pending)} names are not yet matched with GBIF; the next run continues. "
                     "They are listed under their own name for now.")
    merged = resolve(con)
    described_years(con)
    flags(con)
    out.mkdir(parents=True, exist_ok=True)
    if inputs.get("globi_edges"):
        web_files(con, inputs["globi_edges"], out)
    else:
        shutil.rmtree(out / "web", ignore_errors=True)
    con.sql(f"""COPY (SELECT key, name, "group", sources, observed, iucn, labels, states_observed, last_year, iucn_year,
                            year, authority FROM listed) TO '{out / 'master.parquet'}' (FORMAT parquet, COMPRESSION zstd)""")
    con.sql(f"COPY (SELECT * EXCLUDE (id) FROM master_state WHERE id IN (SELECT id FROM listed)) "
            f"TO '{out / 'master_state.parquet'}' (FORMAT parquet, COMPRESSION zstd)")
    summary = site_files(con, out, meta, districts_path, notes, (inputs.get("inat") or {}).get("places"),
                         inputs.get("inat_coarse"))
    ch = changes(con, prev and prev["parquet"], prev and prev["period"], meta["period"])
    if prev:
        ch["waiting"] = {"before": waiting_total(prev.get("summary")), "now": waiting_total(summary)}
    dump(ch, out / "changes.json")
    dump(next_history(prev and {**prev, "summary": previous_summary(con, prev)}, summary), out / "history.json")
    summary["merged_ids"] = merged
    summary["names_pending_match"] = len(pending)
    return summary


def fingerprint(paths, inputs, cache, extra=None):
    """What a layer is built from: the same fingerprint gives the same files."""
    h = hashlib.sha256(json.dumps(extra, sort_keys=True).encode())
    for p in [*paths.values(), *(inputs.get(k) for k in ("zsi", "wcvp", "bsi", "bsi_monographs", "globi", "globi_edges", "soib", "lichens",
                                                     "bryophytes", "zotero", "evidence", "bold")), *(inputs.get("described") or {}).values()]:
        h.update((sha256(p) if isinstance(p, Path) and p.exists() else "-").encode())
    for k in ("inat", "newspecies", "inat_genus", "inat_coarse"):
        h.update(json.dumps(inputs.get(k), sort_keys=True).encode())
    h.update(json.dumps(cache, sort_keys=True).encode())
    h.update(sha256(Path(__file__)).encode())
    return h.hexdigest()[:16]


def publish(s3, out: Path, period, build, info):
    """Upload a build to its own folder, then point to it: every file (sync_files raises if one fails, and then no
    pointer moves), the manifest, the week's current.json, latest.json. The site reads one build or the other, never a
    mix. Then older builds and copies go (prune). A rerun skips what R2 holds."""
    from pipeline import r2
    base = f"layers/master/{period}/{build}/"
    files = [p for p in sorted(out.rglob("*")) if p.is_file() and p.name != "manifest.json"]
    sent = r2.sync_files(s3, ((p, base + p.relative_to(out).as_posix()) for p in files))
    r2.sync_file(s3, out / "manifest.json", base + "manifest.json")
    r2.put_json(s3, {"period": period, "build": build, "base": base}, f"layers/master/{period}/current.json")
    r2.put_json(s3, {**info, "base": base}, "layers/master/latest.json")
    gone = prune(s3, period, build)
    print(f"published {base}: {sent} of {len(files)} files uploaded (the rest were unchanged); "
          f"{gone} files of older builds and copies deleted", flush=True)


def prune(s3, period, current):
    """Retention of the master list in R2. This week (period): the current build and the one before. A past week:
    only the build its current.json names (its last build). In a week with a pointer, the files from before builds
    go too; a week with no pointer keeps them (its only copy). The build latest.json names is never deleted, nor
    anything outside layers/master/<week>/. Returns the files deleted."""
    from pipeline import r2
    live = (r2.get_json(s3, "layers/master/latest.json") or {}).get("base")
    by_week = {}
    for k in r2.list_keys(s3, "layers/master/"):
        parts = k.split("/")
        if len(parts) >= 4:
            by_week.setdefault(parts[2], []).append(k)
    gone = []
    for week, keys in by_week.items():
        ptr = r2.get_json(s3, f"layers/master/{week}/current.json")
        if not ptr:
            continue
        builds = sorted({k.split("/")[3] for k in keys if k.count("/") >= 4 and BUILD_RE.fullmatch(k.split("/")[3])})
        keep = (set(builds[-KEEP_BUILDS:]) | {current}) if week == period else {ptr["build"]}
        for k in keys:
            folder = k.split("/")[3]
            if k.endswith(f"/{week}/current.json") or (live and k.startswith(live)):
                continue
            if folder in keep and k.count("/") >= 4:
                continue
            gone.append(k)
    return r2.delete_keys(s3, gone)


def run(a):
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
    s3 = None
    if os.environ.get("R2_ENDPOINT"):
        from pipeline import r2
        s3 = r2.client()
    if a.cmd == "seed":
        return seed(s3)
    snapshot = a.snapshot
    if not snapshot:
        from pipeline import r2
        snapshot = (r2.get_json(s3, "latest.json") or {}).get("run_id") if s3 else None
        if not snapshot:
            raise SystemExit("no --snapshot given and no published snapshot found")
    week = period()
    out = LAYERS / "master" / week
    paths = snapshot_input(s3, snapshot)
    inat_doc, inat_month = layer_input(s3, "inat", "species_counts", "species_counts.json")
    ns_doc, ns_month = layer_input(s3, "newspecies", "file", "new_species.json")
    genus_doc, _ = layer_input(s3, "inat", "genus_counts", "genus_counts.json")
    coarse_doc, _ = layer_input(s3, "inat", "coarse_counts", "coarse_counts.json")
    http = requests.Session()
    http.headers["User-Agent"] = health.ua()
    from pipeline import soib
    inputs = {"zsi": zsi_input(s3), "wcvp": wcvp_input(s3), "bsi": bsi_input(s3), "globi": globi_input(s3), "globi_edges": globi_edges_input(s3),
              "soib": soib.refresh(http, s3, CACHE / "soib"), "lichens": lichens_input(s3),
              "bryophytes": bryophytes_input(s3), "zotero": zotero_input_refreshed(http, s3),
              "bsi_monographs": bsi_monographs_input(s3),
              "inat": inat_doc, "newspecies": ns_doc,
              "inat_genus": genus_doc, "inat_coarse": coarse_doc}
    cache = match_cache(s3)
    con = duckdb.connect()
    from pipeline import districts
    districts.ensure(health.ua())
    iucn_meta = iucn.table(con, http, s3)
    inputs["described"] = described.sync(http, s3)
    prev = previous_layer(s3, week)
    inputs["evidence"], inputs["bold"] = evidence_input(http, s3, paths, prev)
    extra = [iucn_meta.get("etag"), prev and sha256(prev["parquet"])]
    fp_before = fingerprint(paths, inputs, cache, extra)
    from pipeline import r2
    remote = r2.get_json(s3, period_base(s3, week) + "manifest.json") if s3 else None
    local = json.loads((out / "manifest.json").read_text()) if (out / "manifest.json").exists() else None
    old = local or remote
    if old and old.get("inputs") == fp_before and not old.get("names_pending_match") and not a.force:
        print(f"layers/master/{week}: already built from the same inputs ({fp_before}); nothing to do")
        if not local:
            return  # built and published by an earlier run
    else:
        deadline = time.monotonic() + a.minutes * 60 if a.minutes else None
        meta = {"period": week, "snapshot": snapshot, "built": now()}
        summary = build(con, paths, out, meta, districts.PATH, inputs, cache, s3, deadline, http, match=not a.no_match,
                        prev=prev)
        manifest = {**meta, "build": build_id(meta["built"]), "inputs": fingerprint(paths, inputs, cache, extra), "names_pending_match": summary["names_pending_match"],
                    "merged_ids": summary["merged_ids"], "totals": summary["totals"],
                    "sources": {"snapshot": snapshot, "inat_species_counts": inat_month, "newspecies": ns_month,
                                "zsi": bool(inputs["zsi"]), "wcvp": bool(inputs["wcvp"]), "bsi_checklist": bool(inputs["bsi"]),
                                "iucn": iucn_meta},
                    "files": {p.relative_to(out).as_posix(): p.stat().st_size for p in sorted(out.rglob("*")) if p.is_file()}}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
        print(json.dumps({"totals": summary["totals"], "pending": summary["names_pending_match"],
                          "notes": summary["notes"]}, indent=1))
    if a.publish:
        if not s3:
            raise SystemExit("--publish needs the R2_* environment variables")
        built = json.loads((out / "manifest.json").read_text())
        if remote and remote.get("inputs") == built["inputs"] and not a.force:
            print(f"layers/master/{week} is already published from the same inputs")
            return
        info = {"period": week, "previous": prev and prev["period"], "updated": now(), "snapshot": snapshot}
        publish(s3, out, week, built.get("build") or build_id(built["built"]), info)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", nargs="?", default="build", choices=["build", "seed"])
    p.add_argument("--snapshot", help="published snapshot run id, e.g. 2026-10 (default: the latest)")
    p.add_argument("--minutes", type=int, help="stop GBIF name matching after this many minutes; the next run continues")
    p.add_argument("--no-match", action="store_true", help="do not ask GBIF for new names (use the cache only)")
    p.add_argument("--force", action="store_true", help="rebuild even if the inputs are unchanged")
    p.add_argument("--publish", action="store_true")
    run(p.parse_args())


if __name__ == "__main__":
    main()
