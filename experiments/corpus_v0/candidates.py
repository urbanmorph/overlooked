"""Per-group candidate species, exactly as the model check's bioclip-2.5-filled run: species with an Indian
GBIF record (model_check common.india_species) that the filled BioCLIP 2.5 label set can name.

Cache: data/corpus_v0/candidates.parquet (species, group). A rerun reads the cache.
"""

import pandas as pd
from lib import DATA, atomic_parquet, log

CACHE = DATA / "candidates.parquet"


def filled_index():
    """name -> row in the filled label list (published BioCLIP 2.5 rows, then rows added from BioCLIP 2)."""
    from zeroshot import clip_labels

    index, _, labels = clip_labels("bioclip-2.5")
    b2_index, _, _ = clip_labels("bioclip-2")
    n = len(labels)
    extra = 0
    for name in b2_index:
        if name not in index:
            index[name] = n + extra
            extra += 1
    return index


def candidates():
    if CACHE.exists():
        return pd.read_parquet(CACHE)
    from common import india_species

    sp = india_species()
    index = filled_index()
    c = sp[sp.species.isin(index)][["species", "group"]].reset_index(drop=True)
    atomic_parquet(c, CACHE)
    log(f"candidates: {len(c):,} of {len(sp):,} Indian species can be named by bioclip-2.5-filled")
    return c


if __name__ == "__main__":
    c = candidates()
    print(c.group.value_counts().to_string())
