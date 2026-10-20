"""Map answer-key species names to their accepted species in the GBIF backbone (GBIF /v1/species/match).

Cache: data/model_check/gbif_match.json (name -> the match fields used). Saved every SAVE_EVERY lookups and
on exit, so a stopped run continues; names already in the cache are never looked up again.
No key is needed; requests are few (one per distinct answer-key species) and run 4 at a time.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from common import DATA, atomic_write_json
from scoring import accepted_from_match

CACHE = DATA / "gbif_match.json"
URL = "https://api.gbif.org/v1/species/match"
SAVE_EVERY = 200
KEEP = (
    "matchType",
    "rank",
    "status",
    "confidence",
    "species",
    "genus",
    "scientificName",
    "usageKey",
    "acceptedUsageKey",
)


def _match(session, name, tries=5):
    for attempt in range(tries):
        try:
            r = session.get(URL, params={"name": name, "verbose": "false"}, timeout=30)
            r.raise_for_status()
            m = r.json()
            return name, {k: m.get(k) for k in KEEP}
        except requests.RequestException as e:
            if attempt == tries - 1:
                raise
            print(f"  GBIF retry {attempt + 1} for {name!r}: {type(e).__name__}", flush=True)
            time.sleep(2**attempt)


def gbif_matches(names):
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = sorted({n for n in names if n and n not in cache})
    if todo:
        print(f"GBIF match: {len(cache)} cached, {len(todo)} to look up", flush=True)
        try:
            with requests.Session() as s, ThreadPoolExecutor(4) as pool:
                for i, (name, m) in enumerate(pool.map(lambda n: _match(s, n), todo), 1):
                    cache[name] = m
                    if i % SAVE_EVERY == 0:
                        atomic_write_json(CACHE, cache)
                        print(f"  GBIF match: {i}/{len(todo)}", flush=True)
        finally:
            atomic_write_json(CACHE, cache)
    return cache


def accepted_names(names):
    """name -> accepted species name in the GBIF backbone (None if no species-level match)."""
    cache = gbif_matches(names)
    return {n: accepted_from_match(cache.get(n)) for n in names}


if __name__ == "__main__":
    from common import answer_key

    acc = accepted_names(answer_key().true_species.unique().tolist())
    changed = {k: v for k, v in acc.items() if v and v != k}
    print(
        f"{len(acc)} names; {sum(v is None for v in acc.values())} without a species match; "
        f"{len(changed)} map to a different accepted name, e.g. {list(changed.items())[:5]}"
    )
