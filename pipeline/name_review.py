"""Names to check: species on the India list that no Indian checklist lists, with a congener that one does, and an
older name that GBIF's match places under them (as Pteropus giganteus, the Indian flying fox's old name, is placed
under the Southeast Asian Pteropus vampyrus). Such a species may hold another species' records under its old name.
A person who knows the group decides; the right corrections go into pipeline/ref/name_overrides.csv.

Not yet in the master build: most candidates are matching failures (ZSI OCR errors, newer splits, cultivated plants),
not misfilings, so review/names.json waits until the rule removes them (public_rows: no IUCN range data). The internal report
(scripts/override_candidates.py) adds IUCN's range, which puts the strongest first.
"""

from pipeline.util import dump

CHECKLISTS = {"ZSI", "BSI", "WCVP", "Lichens", "Bryophytes"}


def candidates(rows, cache, iucn_india=None):
    """rows: (key, name, sources, states_observed); cache: the GBIF name match ({name: {key, synonym, ...}});
    iucn_india: {name: whether IUCN's range includes India} for the species IUCN assessed."""
    iucn_india = iucn_india or {}
    listed_genus = {}
    for key, name, sources, _ in rows:
        if CHECKLISTS & set(sources):
            listed_genus.setdefault(name.split()[0], []).append(name)
    syn = {}
    for name, m in cache.items():
        if m and m.get("synonym") and m.get("key"):
            syn.setdefault(m["key"], []).append(name)
    out = []
    for key, name, sources, states in rows:
        genus = name.split()[0]
        if key in syn and not CHECKLISTS & set(sources) and listed_genus.get(genus):
            out.append({"key": key, "name": name, "sources": "; ".join(sources), "states": len(states or []),
                        "iucn_india": iucn_india.get(name), "synonyms": "; ".join(sorted(syn[key])),
                        "congeners_on_checklists": "; ".join(sorted(listed_genus[genus]))})
    return sorted(out, key=lambda r: (r["iucn_india"] is not False, -r["states"], r["name"]))


def public_rows(rows, cache):
    """[key, name, states with an open record, [older names], [congeners on a checklist]], most states first."""
    return [[r["key"], r["name"], r["states"], r["synonyms"].split("; "), r["congeners_on_checklists"].split("; ")]
            for r in candidates(rows, cache)]


def review_file(rows, cache, out):
    """review/names.json: {"n": rows, "rows": public_rows}."""
    found = public_rows(rows, cache)
    dump({"n": len(found), "rows": found}, out / "review" / "names.json")
    return len(found)
