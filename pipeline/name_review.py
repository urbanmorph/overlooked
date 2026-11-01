"""Names to check: species on the India list that no Indian checklist lists, with a congener that one does, and an
older name that GBIF's match places under them (as Pteropus giganteus, the Indian flying fox's old name, is placed
under the Southeast Asian Pteropus vampyrus). Such a species may hold another species' records under its old name.
A person who knows the group decides; the right corrections go into pipeline/ref/name_overrides.csv.

Not candidates (1 Nov 2026, after ZSI names lost to OCR and to bracketed years came back, pipeline/zsi_parse.py):
a species another India list has (on_lists: State of India's Birds, eBird's records from India), a species one of
whose older names is the name a checklist uses with the same epithet (its genus moved: ZSI's Tarucus ananda is
Castalius ananda), a
subspecies whose species a checklist lists, and a species split from a listed one (an older name of it is a
subspecies of the listed species: Corvus macrorhynchos culminatus is now Corvus culminatus).

Newer bird splits (India's population named apart from a species the 2023 checklists list, such as Ardea coromanda
from Bubulcus ibis) are on eBird's list (pipeline/ebird_india.py), so they leave the list too.

The strong sign: an older name that a checklist uses for another species (a different epithet), as Cenchrus
polystachios, which the Catalogue of Life places under the American Setaria parviflora. The public file (review_file,
review/names.json) has no IUCN range data (IUCN's terms); it has animals, and plants and fungi only with the strong
sign: without it most plants in the rule are cultivated (the tomato), and fungi and algae have no Indian checklist. The internal report
(scripts/override_candidates.py) adds IUCN's range, which puts the strongest first.
"""

import re

from pipeline.util import dump

CHECKLISTS = {"ZSI", "BSI", "WCVP", "Lichens", "Bryophytes"}
NOT_PUBLIC = ("Plants", "Mosses", "Fungi", "Algae")   # group name prefixes


def stem(name):
    """A name's epithet without its Latin gender ending: a genus move keeps it (torquata, torquatus)."""
    return re.sub(r"(us|um|a|is|e)$", "", name.split()[1]) if len(name.split()) > 1 else name


def candidates(rows, cache, iucn_india=None, checklist_names=(), on_lists=()):
    """rows: (key, name, sources, states_observed[, group]); cache: the GBIF name match ({name: {key, synonym, ...}});
    iucn_india: {name: whether IUCN's range includes India} for the species IUCN assessed; checklist_names: the
    names as the checklists print them; on_lists: keys another India list has."""
    iucn_india, checklist_names, on_lists = iucn_india or {}, set(checklist_names), set(on_lists)
    listed_genus, listed = {}, set(checklist_names)
    for key, name, sources, *_ in rows:
        if CHECKLISTS & set(sources):
            listed_genus.setdefault(name.split()[0], []).append(name)
            listed.add(name)
    syn = {}
    for name, m in cache.items():
        if m and m.get("synonym") and m.get("key"):
            syn.setdefault(m["key"], []).append(name)
    out = []
    for key, name, sources, states, *group in rows:
        words = name.split()
        if key not in syn or CHECKLISTS & set(sources) or not listed_genus.get(words[0]) or key in on_lists:
            continue
        on_checklist = [o for o in syn[key] if o in checklist_names]
        if (any(stem(o) == stem(name) for o in on_checklist)                         # its genus moved: the same species
                or (len(words) > 2 and " ".join(words[:2]) in listed)                 # a subspecies of a listed species
                or any(" ".join(o.split()[:2]) in listed for o in syn[key] if len(o.split()) > 2)):   # split from it
            continue
        out.append({"key": key, "name": name, "group": group[0] if group else None, "strong": bool(on_checklist),
                    "sources": "; ".join(sources),
                    "states": len(states or []), "iucn_india": iucn_india.get(name), "synonyms": "; ".join(sorted(syn[key])),
                    "congeners_on_checklists": "; ".join(sorted(listed_genus[words[0]]))})
    return sorted(out, key=lambda r: (not r["strong"], r["iucn_india"] is not False, -r["states"], r["name"]))


def public_rows(rows, cache, checklist_names=(), on_lists=()):
    """Animals, and plants and fungi with the strong sign: [key, name, states with an open record, [older names],
    [congeners on a checklist]]; the strong sign first, then most states."""
    return [[r["key"], r["name"], r["states"], r["synonyms"].split("; "), r["congeners_on_checklists"].split("; ")]
            for r in candidates(rows, cache, checklist_names=checklist_names, on_lists=on_lists)
            if r["strong"] or not (r["group"] or "").startswith(NOT_PUBLIC)]


def review_file(rows, cache, out, checklist_names=(), on_lists=()):
    """review/names.json: {"n": rows, "rows": public_rows}."""
    found = public_rows(rows, cache, checklist_names, on_lists)
    dump({"n": len(found), "rows": found}, out / "review" / "names.json")
    return len(found)
