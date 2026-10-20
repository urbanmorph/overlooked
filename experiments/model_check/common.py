"""Shared inputs for the model check: the fnf pilot's answer key, its per-group Indian candidate species,
and the scoring rules. Reads the fnf project (read only) and writes caches to data/model_check/.

The group rules, the India species list and the scoring follow fnf/scripts/15_id_pilot_model.py, so the
results compare with the pilot (BioCLIP 2: 62.6% top-1 species, 78.4% genus, 80.6% top-5 on 5,604 photos).
"""

import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

FNF = Path("/Users/sathya/Projects/biodiversity/fnf")
PHOTOS = FNF / "data" / "raw" / "inat_photos"
SAMPLE = FNF / "out" / "id_pilot_sample.csv"
SQL_AGG = FNF / "data" / "raw" / "0023859-260928105237408.zip"
BIOCLIP2_DIR = FNF / "data" / "raw" / "bioclip"

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "model_check"
DATA.mkdir(parents=True, exist_ok=True)
HERE = Path(__file__).resolve().parent

SPECIES_RANKS = ["species", "subspecies", "variety", "form", "hybrid"]
WEAK = ["True bugs", "Beetles", "Fungi", "Lichens", "Spiders & kin"]
STRONG = ["Dragonflies", "Bees, wasps & ants", "Butterflies", "Birds", "Rodents & shrews"]

BUTTERFLY_FAMILIES = ("Papilionidae", "Pieridae", "Nymphalidae", "Lycaenidae", "Hesperiidae", "Riodinidae")
LARGE_MAMMAL_ORDERS = ("Carnivora", "Proboscidea", "Artiodactyla", "Perissodactyla", "Primates", "Pholidota")
LICHEN_CLASSES = ("Lecanoromycetes", "Lichinomycetes", "Arthoniomycetes")
# Copied from fnf/scripts/15_id_pilot_model.py (same group rules as the pilot).
GROUP_SQL = f"""CASE
    WHEN class = 'Aves' THEN 'Birds'
    WHEN class = 'Mammalia' AND "order" IN {LARGE_MAMMAL_ORDERS} THEN 'Large mammals'
    WHEN class = 'Mammalia' AND "order" = 'Chiroptera' THEN 'Bats'
    WHEN class = 'Mammalia' AND "order" IN ('Rodentia', 'Eulipotyphla', 'Scandentia', 'Lagomorpha') THEN 'Rodents & shrews'
    WHEN class IN ('Squamata', 'Testudines', 'Crocodylia', 'Reptilia') THEN 'Reptiles'
    WHEN class = 'Amphibia' THEN 'Amphibians'
    WHEN phylum = 'Chordata' AND class IN ('Actinopterygii', 'Teleostei', 'Holostei', 'Elasmobranchii') THEN 'Fish'
    WHEN "order" = 'Lepidoptera' AND family IN {BUTTERFLY_FAMILIES} THEN 'Butterflies'
    WHEN "order" = 'Lepidoptera' THEN 'Moths'
    WHEN "order" = 'Odonata' THEN 'Dragonflies'
    WHEN "order" = 'Coleoptera' THEN 'Beetles'
    WHEN "order" = 'Hymenoptera' THEN 'Bees, wasps & ants'
    WHEN "order" = 'Diptera' THEN 'Flies'
    WHEN "order" = 'Hemiptera' THEN 'True bugs'
    WHEN class = 'Arachnida' THEN 'Spiders & kin'
    WHEN phylum = 'Mollusca' THEN 'Molluscs'
    WHEN phylum = 'Tracheophyta' AND family = 'Orchidaceae' THEN 'Orchids'
    WHEN phylum = 'Tracheophyta' AND family IN ('Poaceae', 'Cyperaceae') THEN 'Grasses & sedges'
    WHEN phylum = 'Tracheophyta' AND class IN ('Polypodiopsida', 'Lycopodiopsida') THEN 'Ferns'
    WHEN phylum = 'Tracheophyta' AND class = 'Magnoliopsida' THEN 'Flowering plants (dicots)'
    WHEN phylum IN ('Bryophyta', 'Marchantiophyta', 'Anthocerotophyta') THEN 'Mosses & liverworts'
    WHEN kingdom = 'Fungi' AND class IN {LICHEN_CLASSES} THEN 'Lichens'
    WHEN kingdom = 'Fungi' THEN 'Fungi'
    WHEN phylum IN ('Rhodophyta', 'Chlorophyta') THEN 'Algae & diatoms'
END"""


def binomial(name):
    parts = str(name).split()
    return " ".join(parts[:2]) if len(parts) >= 2 else None


def research_photos():
    """All research-grade rows of the pilot sample (5,626 photos; one photo per observation)."""
    s = pd.read_csv(SAMPLE)
    s = s[s.quality_grade == "research"].reset_index(drop=True)
    s["true_species"] = np.where(s.taxon_rank.isin(SPECIES_RANKS), s.taxon_name.map(binomial), None)
    s["true_genus"] = s.taxon_name.str.split().str[0]
    return s


def answer_key():
    """The pilot's answer key: research grade, named to species or below (5,604 photos)."""
    s = research_photos()
    return s[s.true_species.notna()].reset_index(drop=True)


def india_species():
    """Species with an Indian GBIF record, by group (as the pilot). Cached as parquet."""
    cache = DATA / "india_species.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    import duckdb

    agg = pd.read_csv(  # noqa: F841 (duckdb reads it by name)
        SQL_AGG,
        sep="\t",
        usecols=["kingdom", "phylum", "class", "order", "family", "species", "year"],
        dtype={"year": "Int64"},
    )
    df = duckdb.sql("""
        SELECT species, any_value(kingdom) AS kingdom, any_value(phylum) AS phylum, any_value(class) AS class,
               any_value("order") AS "order", any_value(family) AS family, max("year") AS last_year
        FROM agg WHERE species IS NOT NULL GROUP BY species""").df()
    df["group"] = duckdb.sql(f"SELECT {GROUP_SQL} AS g FROM df").df().g.values
    df = df[df.group.notna()].reset_index(drop=True)
    df.to_parquet(cache)
    return df


def atomic_savez(path, **arrays):
    """Write an .npz via a temp file and rename, so a kill mid-write never leaves a broken cache."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".npz")
    os.close(fd)
    np.savez(tmp, **arrays)
    os.replace(tmp, path)


def atomic_write_json(path, obj):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def pct(x):
    return round(100 * float(np.mean(x)), 1) if len(x) else None
