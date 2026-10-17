"""Master list: every species documented from India, with the sources that list it.

Per species (and per state where the place is known) we track three things: observed, identified and
the IUCN category.
  documented  on the list of any source: ZSI checklists, BSI checklists, Kew WCVP (plants native to India),
              GBIF, iNaturalist, new species since 2015 (Plazi, BSI Plant Discoveries)
  observed    at least one observation in any source: a GBIF record of any kind (photo, sighting, specimen,
              sound, DNA sample, record cited from a paper), or an iNaturalist observation of any grade
  identified  at least one observation confirmed to species: a GBIF record named to species (labelled by
              its basis of record), or an iNaturalist research-grade observation. iNaturalist "needs ID"
              with a species name proposed is observed, not identified.
A checklist entry is not an observation: a species only on checklists is "documented, checklist only".

Names: every name is matched to the Catalogue of Life (eXtended Release, the taxonomy of GBIF's SQL
downloads): GBIF species keys as they are, ZSI's own Catalogue of Life match, then exact names, then
GBIF's name match against the Catalogue of Life (one request per name, cached in R2 cache/master/).
A name that does not match stays on the list with the label "name not matched".

Inputs (all optional except the snapshot):
  snapshot      snapshots/<run>/{species,ledger,species_decade}.parquet (+ unlocated, candidates when built)
  ZSI           data/fnf/zsi/zsi_checklist_matched.csv, else R2 cache/master/zsi_checklist.csv
  WCVP          data/fnf/wcvp/wcvp_india.parquet, else R2 cache/master/wcvp_india.parquet
  BSI checklist data/bsi/bsi_checklist.csv, else R2 cache/bsi/bsi_checklist.csv
  iNaturalist   layers/inat/<month>/species_counts.json (species per state, research grade and needs ID)
  new species   layers/newspecies/<month>/new_species.json
  IUCN          the Red List checklist on GBIF (pipeline/iucn.py)

Output: data/layers/master/<month>/ (and R2 layers/master/<month>/ with --publish, then layers/master/latest.json)
  master.parquet        one row per species: key, name, group, sources[], observed, identified, iucn, labels[],
                        states_observed[], states_identified[]
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
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests

from pipeline import health, iucn, site_data
from pipeline.boundaries import title
from pipeline.groups import GROUP_SQL, GROUPS
from pipeline.layer_newspecies import expand, gbif_match

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

SOURCES = ["ZSI", "BSI", "WCVP", "GBIF", "iNaturalist", "Plazi", "IUCN"]
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
    ("lm", "Location missing", "other"),
    ("do", "DNA only", "other"),
    ("end", "Endemic to India", "other"),
    ("ns", "New species since 2015", "other"),
    ("nm", "Name not matched", "other"),
]
CODES = [c for c, _, _ in LABELS]
# NE = not assessed. EW and EX come last so the first seven indices stay fixed.
IUCN_CATS = ["CR", "EN", "VU", "NT", "LC", "DD", "NE", "EW", "EX"]
THREATENED = ("CR", "EN", "VU")
BASIS_LABEL = {"HUMAN_OBSERVATION": "ho", "OBSERVATION": "ho", "PRESERVED_SPECIMEN": "sp", "MATERIAL_CITATION": "pap",
               "MATERIAL_SAMPLE": "dna", "MACHINE_OBSERVATION": "mo", "OCCURRENCE": "oc"}
NEW_SINCE = 2015

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
# BSI checklist group text -> (kingdom, phylum, class).
BSI_HINTS = [(r"lichen", ("Fungi", "Ascomycota", "Lecanoromycetes")), (r"fung", ("Fungi", None, None)),
             (r"bryo|moss|liverwort|hornwort", ("Plantae", "Bryophyta", None)),
             (r"alga|diatom", ("Plantae", "Chlorophyta", None)),
             (r"pterido|fern|lycophyt", ("Plantae", "Tracheophyta", "Polypodiopsida")),
             (r"", ("Plantae", "Tracheophyta", None))]


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dump(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))


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

def sha256(path: Path):
    from pipeline import r2
    return r2.sha256(path)


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
        COPY (SELECT checklist, family, name, rank, mark, col_accepted_id, col_accepted_name, col_family, match_type,
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
    for name in ("species", "ledger", "species_decade", "unlocated", "candidates"):
        p = folder / f"{name}.parquet"
        if not p.exists() and s3:
            r2_file(s3, f"snapshots/{run_id}/{name}.parquet", p)
        paths[name] = p if p.exists() else None
    missing = [n for n in ("species", "ledger", "species_decade") if not paths[n]]
    if missing:
        raise SystemExit(f"snapshot {run_id}: {missing} not found locally or in R2")
    return paths


def layer_input(s3, layer, field, filename):
    """The newest local layers/<layer>/<month>/<filename>, else the one R2 layers/<layer>/latest.json names."""
    from pipeline import r2
    local = sorted((LAYERS / layer).glob(f"*/{filename}"))
    if local:
        return json.loads(local[-1].read_text()), local[-1].parent.name
    latest = r2.get_json(s3, f"layers/{layer}/latest.json") if s3 else None
    if latest and latest.get(field):
        return r2.get_json(s3, latest[field]), latest.get("month")
    return None, None


# ---------------------------------------------------------------- loading

NAMES_COLS = ("source VARCHAR, name VARCHAR, key VARCHAR, kingdom VARCHAR, phylum VARCHAR, class VARCHAR, "
              "\"order\" VARCHAR, family VARCHAR, genus VARCHAR, grp VARCHAR, endemic BOOLEAN, new BOOLEAN, tier INTEGER")
EVIDENCE_COLS = ("source VARCHAR, name VARCHAR, key VARCHAR, state_lgd INTEGER, label VARCHAR, "
                 "observed BOOLEAN, identified BOOLEAN, located BOOLEAN")
# Canonical "Genus epithet": subgenus in brackets dropped, infraspecific part dropped.
BINOMIAL = """CREATE OR REPLACE MACRO binomial(s) AS coalesce(nullif(regexp_extract(
                  regexp_replace(trim(s), '\\s*\\([A-Z][a-z]+\\)', ''), '^([A-Z][a-z-]+ (× ?)?[a-z][a-z-]+)', 1), ''),
              nullif(trim(s), ''))"""


def start(con):
    """Empty tables every loader appends to.
    names_in: one row per source x name (documentation), with what is known of the classification.
      tier: how good the classification is (0 = GBIF's own; 5 = a hint from the source).
    evidence: observations. state_lgd NULL = India, place not known."""
    con.sql(BINOMIAL)
    con.sql(f"CREATE OR REPLACE TABLE names_in ({NAMES_COLS})")
    con.sql(f"CREATE OR REPLACE TABLE evidence ({EVIDENCE_COLS})")
    con.sql("CREATE OR REPLACE TABLE alias (name VARCHAR, key VARCHAR, display VARCHAR, prio INTEGER)")


def load_gbif(con, paths):
    """GBIF species (records with coordinates), their kinds of record, states, and records with no coordinates."""
    basis = " ".join(f"WHEN '{b}' THEN '{c}'" for b, c in BASIS_LABEL.items())
    con.sql(f"""INSERT INTO names_in SELECT 'GBIF', name, species_key, kingdom, phylum, class, "order", family, genus,
                NULL, false, false, 0 FROM '{paths["species"]}'""")
    con.sql(f"""INSERT INTO evidence SELECT DISTINCT 'GBIF', NULL, species_key, NULL, CASE basis {basis} ELSE 'oc' END,
                true, true, true FROM '{paths["species_decade"]}'""")
    con.sql(f"""INSERT INTO evidence SELECT DISTINCT 'GBIF', NULL, species_key, state_lgd, NULL, true, true, true
                FROM '{paths["ledger"]}' WHERE state_lgd IS NOT NULL""")
    con.sql(f"""INSERT INTO alias SELECT name, species_key, name, 0 FROM '{paths["species"]}'""")
    # DNA only, where the ledger knows which records are DNA sequences (snapshots built after that column was added).
    cols = [c[0] for c in con.sql(f"DESCRIBE SELECT * FROM '{paths['ledger']}'").fetchall()]
    dna_sql = (f"""SELECT species_key AS key FROM '{paths["ledger"]}' GROUP BY 1
                   HAVING max(last_year_not_dna) IS NULL AND max(last_year) IS NOT NULL"""
               if "last_year_not_dna" in cols else "SELECT NULL::VARCHAR AS key WHERE false")
    con.sql(f"CREATE OR REPLACE TABLE ledger_dna_only AS {dna_sql}")
    if paths.get("unlocated"):
        con.sql(f"""INSERT INTO names_in SELECT 'GBIF', name, species_key, NULL, NULL, NULL, NULL, NULL, genus, grp,
                    false, false, 1 FROM '{paths["unlocated"]}' WHERE species_key IS NOT NULL""")
        con.sql(f"""INSERT INTO evidence SELECT DISTINCT 'GBIF', NULL, species_key, state_lgd,
                    CASE basis {basis} ELSE 'oc' END, true, true, false
                    FROM '{paths["unlocated"]}' WHERE species_key IS NOT NULL""")
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
    con.sql("""INSERT INTO alias SELECT DISTINCT binomial(name), col_accepted_id, binomial(coalesce(col_accepted_name, name)), 2
               FROM zsi WHERE matched AND rank = 'species'""")


def load_wcvp(con, path):
    """Kew WCVP: vascular plants native to India; endemic_india from Kew's distribution data."""
    con.sql(f"""INSERT INTO names_in SELECT 'WCVP', binomial(species), NULL, 'Plantae', 'Tracheophyta', NULL, NULL,
                family, genus, NULL, coalesce(endemic_india, false), false, 5 FROM '{path}'""")


def load_bsi(con, path):
    """BSI checklists (pipeline/bsi_checklist.py). status containing 'endemic' marks an endemic species."""
    rows = con.sql(f"""SELECT binomial(name), family, "group", coalesce(status, '') ILIKE '%endemic%'
                       FROM read_csv('{path}', header = true, all_varchar = true) WHERE name IS NOT NULL""").fetchall()
    con.executemany("INSERT INTO names_in VALUES ('BSI', ?, NULL, ?, ?, ?, NULL, ?, NULL, NULL, ?, false, 5)",
                    [[n, *hint_row(BSI_HINTS, g), fam, end] for n, fam, g, end in rows])


def load_inat(con, doc):
    """iNaturalist species lists per state: research grade = identified; needs ID = observed."""
    rows, names = [], {}
    for code, lists in doc["lists"].items():
        state = None if code == "india" else int(code)
        for quality, label, ident in (("research", "rg", True), ("needs_id", "nid", False)):
            for _, name, iconic, _ in lists.get(quality, []):
                rows.append([name, state, label, ident])
                names.setdefault(name, iconic)
    con.executemany("INSERT INTO evidence VALUES ('iNaturalist', binomial(?), NULL, ?, ?, true, ?, true)", rows)
    con.executemany("""INSERT INTO names_in VALUES ('iNaturalist', binomial(?), NULL, ?, ?, ?, NULL, NULL, NULL, NULL,
                       false, false, 5)""",
                    [[n, *INAT_HINTS.get(i or "", (None, None, None))] for n, i in names.items()])


def load_newspecies(con, doc):
    """Species described from India since 2015 (Plazi; BSI Plant Discoveries)."""
    rows = []
    for r in expand(doc):
        grp = r["group"] if r["group"] in GROUPS else None
        for src, tag in (("Plazi", "Plazi"), ("BSI", "BSI Plant Discoveries")):
            if tag in r["sources"]:
                rows.append([src, r["name"], r["key"], grp, (r["year"] or 0) >= NEW_SINCE])
    con.executemany("""INSERT INTO names_in VALUES (?, binomial(?), ?, NULL, NULL, NULL, NULL, NULL, NULL, ?, false, ?, 5)""",
                    rows)


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
    WCVP and BSI. ZSI names were matched against the same Catalogue of Life release in fnf, so not asked again."""
    rows = con.sql("""
        WITH want AS (
            SELECT name, CASE WHEN label = 'rg' THEN 0 ELSE 1 END AS prio FROM evidence
            WHERE key IS NULL AND source = 'iNaturalist'
            UNION ALL SELECT name, CASE source WHEN 'WCVP' THEN 2 ELSE 3 END FROM names_in
            WHERE key IS NULL AND source IN ('WCVP', 'BSI'))
        SELECT name FROM want WHERE name IS NOT NULL AND NOT EXISTS (SELECT 1 FROM alias a WHERE a.name = want.name)
        GROUP BY name ORDER BY min(prio), name
    """).fetchall()
    return [n for (n,) in rows if n not in cache]


def match_names(con, names, cache, s3, deadline=None, http=None):
    """Ask GBIF for each name (one at a time, about 1 a second), saving the cache every 10 minutes and at the end.
    Stops at the deadline or when GBIF stops answering; the next run continues. Returns how many were asked."""
    http = http or requests.Session()
    http.headers.setdefault("User-Agent", health.ua())
    asked, next_save = 0, time.monotonic() + CHECKPOINT
    try:
        for name in names:
            if deadline is not None and time.monotonic() > deadline:
                print(f"time limit: {asked} names matched this run, {len(names) - asked} left for the next", flush=True)
                break
            try:
                gbif_match(http, name, cache, need_classification=True)
            except requests.RequestException as e:
                print(f"GBIF match stopped ({type(e).__name__}); the next run continues", flush=True)
                break
            asked += 1
            if time.monotonic() > next_save:
                next_save = time.monotonic() + CHECKPOINT
                print(f"{asked} of {len(names)} names matched; saving the cache", flush=True)
                save_match_cache(cache, s3)
    finally:
        if asked:
            save_match_cache(cache, s3)
    return asked


def add_matches(con, cache):
    """Matches from the cache become aliases, with their classification (tier 1 for the group)."""
    rows = [[n, m["key"], m.get("accepted_name") or n, *(m.get("classification") or {}).values()]
            for n, m in cache.items() if m and m.get("key")]
    con.sql("CREATE OR REPLACE TABLE matched (name VARCHAR, key VARCHAR, display VARCHAR, kingdom VARCHAR, "
            "phylum VARCHAR, class VARCHAR, \"order\" VARCHAR, family VARCHAR)")
    if rows:
        con.executemany("INSERT INTO matched VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [r + [None] * (8 - len(r)) for r in rows])
    con.sql("INSERT INTO alias SELECT name, key, display, 3 FROM matched")


def resolve(con):
    """Give every row an id: its key, else the key its name has (alias), else 'n:<name>' (name not matched).
    Then fold ids that share a name and kingdom into one (GBIF's key first), as names.merge_duplicates does
    for GBIF keys. Creates tables ids (id, name, grp, kingdom), idmap (id -> canonical)."""
    con.sql("""CREATE OR REPLACE TABLE alias1 AS
               SELECT name, arg_min(key, prio * 10 + CASE WHEN prio = 0 THEN 0 ELSE 1 END) AS key FROM alias
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
        SELECT id, arg_min(coalesce(grp, {GROUP_SQL}), t) AS grp, arg_min(kingdom, t) AS kingdom
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
    return con.sql("SELECT count(*) FROM idmap WHERE id <> canonical").fetchone()[0]


# ---------------------------------------------------------------- flags and labels

def flags(con):
    """Creates tables master (one row per species) and master_state (one row per species x state)."""
    src_idx = " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(SOURCES))
    lab_idx = " ".join(f"WHEN '{c}' THEN {i}" for i, c in enumerate(CODES))
    cat_idx = " ".join(f"WHEN '{c}' THEN {i}" for i, c in enumerate(IUCN_CATS))
    # IUCN: the assessed name equal to the display name first, then any accepted name, then a synonym.
    con.sql("""
        CREATE OR REPLACE TABLE id_iucn AS
        WITH names AS (SELECT id, name, 0 AS p FROM ids
                       UNION SELECT id, name, 1 FROM names_in_r UNION SELECT id, name, 1 FROM evidence_r
                       WHERE name IS NOT NULL)
        SELECT n.id, arg_min(i.category, n.p * 10 + CASE WHEN i.accepted THEN 0 ELSE 5 END) AS iucn
        FROM names n JOIN iucn i ON i.name = n.name JOIN ids d ON d.id = n.id
        WHERE i.kingdom IS NULL OR d.kingdom IS NULL OR i.kingdom = d.kingdom
        GROUP BY n.id
    """)
    con.sql("""
        CREATE OR REPLACE TABLE id_flags AS
        SELECT i.id, coalesce(bool_or(e.observed), false) AS observed, coalesce(bool_or(e.identified), false) AS identified,
               coalesce(bool_or(e.located), false) AS located,
               list(DISTINCT e.label) FILTER (WHERE e.label IS NOT NULL) AS ev_labels
        FROM ids i LEFT JOIN evidence_r e USING (id) GROUP BY i.id
    """)
    con.sql(f"""
        CREATE OR REPLACE TABLE id_labels AS
        WITH l AS (
            SELECT id, unnest(ev_labels) AS code FROM id_flags
            UNION SELECT id, 'chk' FROM id_flags WHERE NOT observed
            UNION SELECT id, 'lm' FROM id_flags WHERE observed AND NOT located
            UNION SELECT id, 'end' FROM names_in_r WHERE endemic
            UNION SELECT id, 'ns' FROM names_in_r WHERE new
            UNION SELECT id, 'nm' FROM ids WHERE starts_with(id, 'n:')
            UNION SELECT id, 'do' FROM id_flags
                  WHERE observed AND NOT list_has_any(ev_labels, ['rg', 'nid'])
                    AND (ev_labels = ['dna'] OR (id IN (SELECT key FROM ledger_dna_only)
                                                AND NOT list_has_any(ev_labels, ['ho', 'pap', 'mo']))))
        SELECT id, list(code ORDER BY CASE code {lab_idx} END) AS labels, sum(1::BIGINT << (CASE code {lab_idx} END)) AS labels_mask
        FROM l GROUP BY id
    """)
    con.sql(f"""
        CREATE OR REPLACE TABLE id_sources AS
        WITH s AS (SELECT id, source FROM names_in_r UNION SELECT id, source FROM evidence_r
                   UNION SELECT id, 'IUCN' FROM id_iucn)
        SELECT id, list(source ORDER BY CASE source {src_idx} END) AS sources, sum(1::BIGINT << (CASE source {src_idx} END)) AS sources_mask
        FROM s GROUP BY id
    """)
    con.sql("""
        CREATE OR REPLACE TABLE master_state AS
        SELECT e.id, CASE WHEN NOT starts_with(e.id, 'n:') THEN e.id END AS key, any_value(i.name) AS name, e.state_lgd,
               bool_or(e.source = 'GBIF' AND e.located) AS gbif_located,
               bool_or(e.source = 'GBIF' AND NOT e.located) AS gbif_no_coordinates,
               bool_or(e.label = 'rg') AS inat_research, bool_or(e.label = 'nid') AS inat_needs_id,
               bool_or(e.observed) AS observed, bool_or(e.identified) AS identified
        FROM evidence_r e JOIN ids i USING (id) WHERE e.state_lgd IS NOT NULL
        GROUP BY e.id, e.state_lgd ORDER BY state_lgd, name
    """)
    con.sql("""
        CREATE OR REPLACE TABLE id_states AS
        SELECT id, coalesce(list(state_lgd ORDER BY state_lgd) FILTER (WHERE observed), []) AS states_observed,
               coalesce(list(state_lgd ORDER BY state_lgd) FILTER (WHERE identified), []) AS states_identified
        FROM master_state GROUP BY id
    """)
    con.sql(f"""
        CREATE OR REPLACE TABLE master AS
        SELECT i.id, CASE WHEN NOT starts_with(i.id, 'n:') THEN i.id END AS key, i.name, i.grp AS "group",
               list_position({GROUPS!r}, i.grp) - 1 AS gi,
               s.sources, s.sources_mask, f.observed, f.identified,
               CASE WHEN f.identified THEN 2 WHEN f.observed THEN 1 ELSE 0 END AS status,
               coalesce(c.iucn, 'NE') AS iucn, CASE coalesce(c.iucn, 'NE') {cat_idx} END AS iucn_i,
               l.labels, l.labels_mask,
               coalesce(t.states_observed, []) AS states_observed, coalesce(t.states_identified, []) AS states_identified
        FROM ids i JOIN id_flags f USING (id) JOIN id_sources s USING (id) JOIN id_labels l USING (id)
        LEFT JOIN id_iucn c USING (id) LEFT JOIN id_states t USING (id)
        ORDER BY gi, i.name
    """)


# ---------------------------------------------------------------- site files

def states_list(districts_path):
    rows = duckdb.sql(f"SELECT DISTINCT state_lgd, stname FROM '{districts_path}' WHERE state_lgd > 0 ORDER BY 1").fetchall()
    return [{"code": str(c), "name": title(n)} for c, n in rows]


def site_files(con, out: Path, meta, districts_path, notes):
    """summary.json, g/<gi>.json, search/<p>.json and search/places.json (format agreed with the site)."""
    states = states_list(districts_path)
    bit = {int(s["code"]): i for i, s in enumerate(states)}
    con.execute("CREATE OR REPLACE TABLE state_bit AS SELECT unnest($1) AS state_lgd, unnest($2) AS b",
                [list(bit), list(bit.values())])
    con.sql("""
        CREATE OR REPLACE TABLE site AS
        SELECT m.*, coalesce((SELECT sum(1::BIGINT << b) FROM state_bit WHERE list_contains(m.states_observed, state_lgd)), 0)
                    AS states_obs_mask,
               coalesce((SELECT sum(1::BIGINT << b) FROM state_bit WHERE list_contains(m.states_identified, state_lgd)), 0)
                    AS states_id_mask
        FROM master m
    """)
    for d in ("g", "search"):
        shutil.rmtree(out / d, ignore_errors=True)
    n = len(GROUPS)
    india = [[0, 0, 0, [0] * len(IUCN_CATS), 0] for _ in range(n)]
    for gi, cat, docs, obs, ident, thr in con.sql(f"""
            SELECT gi, iucn_i, count(*), count(*) FILTER (WHERE observed), count(*) FILTER (WHERE identified),
                   count(*) FILTER (WHERE observed AND iucn IN {THREATENED}) FROM master GROUP BY ALL""").fetchall():
        row = india[gi]
        row[0] += docs; row[1] += obs; row[2] += ident; row[3][cat] += docs; row[4] += thr
    by_state = {}
    for st, gi, obs, ident, thr in con.sql(f"""
            SELECT s.state_lgd, m.gi, count(*) FILTER (WHERE s.observed), count(*) FILTER (WHERE s.identified),
                   count(*) FILTER (WHERE s.observed AND m.iucn IN {THREATENED})
            FROM master_state s JOIN master m USING (id)
            GROUP BY ALL""").fetchall():
        by_state.setdefault(str(st), [[0, 0, 0] for _ in range(n)])[gi] = [obs, ident, thr]
    totals = dict(zip(("documented", "observed", "identified"), con.sql(
        "SELECT count(*), count(*) FILTER (WHERE observed), count(*) FILTER (WHERE identified) FROM master").fetchone()))
    summary = {**meta, "sources": SOURCES,
               "labels": [{"code": c, "name": nm, "kind": k} for c, nm, k in LABELS],
               "iucn": IUCN_CATS, "groups": GROUPS, "states": states, "india": india, "by_state": by_state,
               "totals": totals, "notes": notes, **getattr(site_data, "RIGHTS", {})}
    dump(summary, out / "summary.json")

    row_sql = "coalesce(key, ''), name, sources_mask, status, iucn_i, labels_mask, states_obs_mask, states_id_mask"
    for gi in range(n):
        rows = con.sql(f"SELECT {row_sql} FROM site WHERE gi = {gi} ORDER BY name").fetchall()
        dump({"rows": [list(r) for r in rows]}, out / "g" / f"{gi}.json")
    buckets = {}
    for r in con.sql("""SELECT name, coalesce(key, ''), gi, status, iucn_i, sources_mask, labels_mask
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


# ---------------------------------------------------------------- build

def build(con, paths, out: Path, meta, districts_path, inputs, cache=None, s3=None, deadline=None, http=None,
          match=True):
    """Load every input present, match names, flag, label and write the layer. inputs: {name: path or doc or None}."""
    notes = []
    start(con)
    has_dna = load_gbif(con, paths)
    if not has_dna:
        notes.append("DNA only: from the kind of record only (this snapshot's ledger does not mark DNA sequences).")
    if not paths.get("unlocated"):
        notes.append("Records with no coordinates (query L) are not in this snapshot: 'location missing' is empty.")
    if inputs.get("zsi"):
        load_zsi(con, inputs["zsi"])
    if inputs.get("wcvp"):
        load_wcvp(con, inputs["wcvp"])
    if inputs.get("bsi"):
        load_bsi(con, inputs["bsi"])
    else:
        notes.append("BSI checklists are not loaded yet; BSI counts only BSI Plant Discoveries (new species).")
    if inputs.get("inat"):
        load_inat(con, inputs["inat"])
        if not inputs["inat"].get("complete"):
            notes.append("iNaturalist species lists are incomplete (the daily request budget); the next run adds the rest.")
    else:
        notes.append("iNaturalist species lists are not fetched yet: research grade and needs ID are empty.")
    if inputs.get("newspecies"):
        load_newspecies(con, inputs["newspecies"])
    if not inputs.get("zsi"):
        notes.append("ZSI checklists not found.")
    if not inputs.get("wcvp"):
        notes.append("Kew WCVP not found.")
    cache = {} if cache is None else cache
    add_matches(con, cache)
    pending = to_match(con, cache)
    if match and pending:
        print(f"{len(pending)} names to match with GBIF", flush=True)
        match_names(con, pending, cache, s3, deadline, http)
        add_matches(con, cache)
        pending = to_match(con, cache)
    if pending:
        notes.append(f"{len(pending)} names are not yet matched with GBIF; the next run continues. "
                     "They are listed under their own name for now.")
    merged = resolve(con)
    flags(con)
    out.mkdir(parents=True, exist_ok=True)
    con.sql(f"""COPY (SELECT key, name, "group", sources, observed, identified, iucn, labels, states_observed,
                       states_identified FROM master) TO '{out / 'master.parquet'}' (FORMAT parquet, COMPRESSION zstd)""")
    con.sql(f"COPY (SELECT * EXCLUDE (id) FROM master_state) TO '{out / 'master_state.parquet'}' "
            "(FORMAT parquet, COMPRESSION zstd)")
    summary = site_files(con, out, meta, districts_path, notes)
    summary["merged_ids"] = merged
    summary["names_pending_match"] = len(pending)
    return summary


def fingerprint(paths, inputs, cache, extra=None):
    """What a layer is built from: the same fingerprint gives the same files."""
    h = hashlib.sha256(json.dumps(extra, sort_keys=True).encode())
    for p in [*paths.values(), *(inputs.get(k) for k in ("zsi", "wcvp", "bsi"))]:
        h.update((sha256(p) if isinstance(p, Path) and p.exists() else "-").encode())
    for k in ("inat", "newspecies"):
        h.update(json.dumps(inputs.get(k), sort_keys=True).encode())
    h.update(json.dumps(cache, sort_keys=True).encode())
    h.update(sha256(Path(__file__)).encode())
    return h.hexdigest()[:16]


def publish(s3, out: Path, month, info):
    from pipeline import r2
    files = [p for p in sorted(out.rglob("*")) if p.is_file() and p.name != "manifest.json"]
    sent = sum(r2.sync_file(s3, p, f"layers/master/{month}/{p.relative_to(out).as_posix()}", immutable=False)
               for p in files)
    r2.sync_file(s3, out / "manifest.json", f"layers/master/{month}/manifest.json", immutable=False)
    r2.put_json(s3, info, "layers/master/latest.json")
    print(f"published layers/master/{month}/: {sent} of {len(files)} files uploaded (the rest were unchanged)")


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
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    out = LAYERS / "master" / month
    paths = snapshot_input(s3, snapshot)
    inat_doc, inat_month = layer_input(s3, "inat", "species_counts", "species_counts.json")
    ns_doc, ns_month = layer_input(s3, "newspecies", "file", "new_species.json")
    inputs = {"zsi": zsi_input(s3), "wcvp": wcvp_input(s3), "bsi": bsi_input(s3), "inat": inat_doc, "newspecies": ns_doc}
    cache = match_cache(s3)
    con = duckdb.connect()
    http = requests.Session()
    http.headers["User-Agent"] = health.ua()
    from pipeline import districts
    districts.ensure(health.ua())
    iucn_meta = iucn.table(con, http, s3)
    fp_before = fingerprint(paths, inputs, cache, iucn_meta.get("etag"))
    from pipeline import r2
    remote = r2.get_json(s3, f"layers/master/{month}/manifest.json") if s3 else None
    local = json.loads((out / "manifest.json").read_text()) if (out / "manifest.json").exists() else None
    old = local or remote
    if old and old.get("inputs") == fp_before and not old.get("names_pending_match") and not a.force:
        print(f"layers/master/{month}: already built from the same inputs ({fp_before}); nothing to do")
        if not local:
            return  # built and published by an earlier run
    else:
        deadline = time.monotonic() + a.minutes * 60 if a.minutes else None
        meta = {"month": month, "snapshot": snapshot, "built": now()}
        summary = build(con, paths, out, meta, districts.PATH, inputs, cache, s3, deadline, http, match=not a.no_match)
        manifest = {**meta, "inputs": fingerprint(paths, inputs, cache, iucn_meta.get("etag")), "names_pending_match": summary["names_pending_match"],
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
            print(f"layers/master/{month} is already published from the same inputs")
            return
        info = {"month": month, "updated": now(), "snapshot": snapshot, "base": f"layers/master/{month}/"}
        publish(s3, out, month, info)


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
