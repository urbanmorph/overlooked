"""Queue check, part B: a fresh sample of the India needs-ID queue on iNaturalist, to freeze and re-check later.

Per group (the pilot's iNaturalist taxa for the 24 groups): observations in India (place 6681) that need an ID,
created in the last 120 days, named to species or genus, with an open-licence first photo (cc0, cc-by, cc-by-nc,
as the pilot). Random pages (order_by=random) until 400 rows per group are kept or 8 pages are drawn. Kept: the
current taxon is a candidate species of the group (exact, then GBIF synonyms) or a genus with a candidate species;
not one of the pilot's observations.

State: data/corpus_v0/queue_sample_state.json (the draw date and every kept row per group), saved after every
request, so a stopped run continues with the same date window; a group already complete is not asked again.
Output: data/corpus_v0/queue_sample.parquet. Read only: nothing is posted.
Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/queue_sample.py
"""

from datetime import date, timedelta

import inat
import pandas as pd
from candidates import candidates
from lib import (
    DATA,
    accepted_names,
    atomic_parquet,
    atomic_write_json,
    binomial,
    log,
    read_json,
)
from logic import medium_from_api_url, queue_match

STATE = DATA / "queue_sample_state.json"
PER_GROUP, MAX_PAGES, DAYS = 400, 8, 120
LICENCES = ("cc0", "cc-by", "cc-by-nc")
RANKS = "species,subspecies,variety,form,genus"
PILOT = "/Users/sathya/Projects/biodiversity/fnf/out/id_pilot_sample.csv"
# The pilot's group taxa (fnf scripts/13_id_pilot_sample.py GROUPS, ids from its 2026-10-15 snapshot).
TAXA = {
    "Poaceae": 47434, "Chlorophyta": 50863, "Proboscidea": 43691, "Actinopterygii": 47178, "Hymenoptera": 47201,
    "Bryophyta": 311249, "Scandentia": 46280, "Pholidota": 43357, "Odonata": 47792, "Perissodactyla": 43327,
    "Lepidoptera": 47157, "Carnivora": 41573, "Cyperaceae": 47161, "Chiroptera": 40268, "Eulipotyphla": 533971,
    "Elasmobranchii": 47273, "Marchantiophyta": 64615, "Artiodactyla": 152870, "Diptera": 47822,
    "Hemiptera": 47744, "Fungi": 47170, "Lycopodiopsida": 47623, "Amphibia": 20978, "Papilionoidea": 47224,
    "Orchidaceae": 47217, "Aves": 3, "Primates": 43367, "Rodentia": 43698, "Rhodophyta": 57774,
    "Coleoptera": 47208, "Arachnida": 47119, "Magnoliopsida": 47124, "Mollusca": 47115, "Reptilia": 26036,
    "Polypodiopsida": 121943, "Lecanoromycetes": 54743, "Lagomorpha": 43094,
}  # fmt: skip
GROUPS = {
    "Birds": (["Aves"], []),
    "Large mammals": (["Carnivora", "Artiodactyla", "Perissodactyla", "Primates", "Proboscidea", "Pholidota"], []),
    "Bats": (["Chiroptera"], []),
    "Rodents & shrews": (["Rodentia", "Eulipotyphla", "Lagomorpha", "Scandentia"], []),
    "Reptiles": (["Reptilia"], []),
    "Amphibians": (["Amphibia"], []),
    "Fish": (["Actinopterygii", "Elasmobranchii"], []),
    "Butterflies": (["Papilionoidea"], []),
    "Moths": (["Lepidoptera"], ["Papilionoidea"]),
    "Dragonflies": (["Odonata"], []),
    "Beetles": (["Coleoptera"], []),
    "Bees, wasps & ants": (["Hymenoptera"], []),
    "Flies": (["Diptera"], []),
    "True bugs": (["Hemiptera"], []),
    "Spiders & kin": (["Arachnida"], []),
    "Molluscs": (["Mollusca"], []),
    "Orchids": (["Orchidaceae"], []),
    "Grasses & sedges": (["Poaceae", "Cyperaceae"], []),
    "Ferns": (["Polypodiopsida", "Lycopodiopsida"], []),
    "Flowering plants (dicots)": (["Magnoliopsida"], []),
    "Mosses & liverworts": (["Bryophyta", "Marchantiophyta"], []),
    "Fungi": (["Fungi"], ["Lecanoromycetes"]),
    "Lichens": (["Lecanoromycetes"], []),
    "Algae & diatoms": (["Rhodophyta", "Chlorophyta"], []),
}


def row(o, group, cand, how):
    t, ph = o.get("taxon") or {}, (o.get("photos") or [{}])[0]
    return {
        "obs_id": o["id"],
        "group": group,
        "created_at": o.get("created_at"),
        "observed_on": o.get("observed_on"),
        "taxon_id": t.get("id"),
        "taxon_name": t.get("name"),
        "taxon_rank": t.get("rank"),
        "community_taxon_id": o.get("community_taxon_id"),
        "candidate": cand,
        "level": how,
        "photo_id": ph.get("id"),
        "licence": ph.get("license_code"),
        "url": medium_from_api_url(ph.get("url")),
        "observer_login": (o.get("user") or {}).get("login"),
        "observer_name": (o.get("user") or {}).get("name"),
    }


def main():
    state = read_json(STATE) or {"drawn": date.today().isoformat(), "groups": {}}
    d1 = (date.fromisoformat(state["drawn"]) - timedelta(days=DAYS)).isoformat()
    cand = candidates()
    by_group = cand.groupby("group").species.apply(set).to_dict()
    genera = cand.assign(g=cand.species.str.split().str[0]).groupby("group").g.apply(set).to_dict()
    pilot = set(pd.read_csv(PILOT, usecols=["id"]).id)
    try:
        for group, (inc, exc) in GROUPS.items():
            g = state["groups"].setdefault(group, {"pages": 0, "total": None, "rows": {}})
            q = {
                "place_id": 6681, "verifiable": "true", "quality_grade": "needs_id", "created_d1": d1,
                "taxon_id": ",".join(str(TAXA[n]) for n in inc), "rank": RANKS, "photo_license": ",".join(LICENCES),
                "per_page": 200, "order_by": "random",
            }  # fmt: skip
            if exc:
                q["without_taxon_id"] = ",".join(str(TAXA[n]) for n in exc)
            while len(g["rows"]) < PER_GROUP and g["pages"] < MAX_PAGES:
                if g["total"] is not None and g["pages"] * 200 >= 3 * g["total"]:
                    break  # a small group: random pages have seen it all several times over
                js = inat.search({**q, "page": g["pages"] + 1})
                g["pages"] += 1
                g["total"] = js.get("total_results", 0)
                res = [o for o in js.get("results", []) if o["id"] not in pilot]
                names = {binomial(o["taxon"]["name"]) for o in res if o.get("taxon")} - {None}
                acc = accepted_names(sorted(names)) if names else {}
                for o in res:
                    t, ph = o.get("taxon") or {}, (o.get("photos") or [{}])[0]
                    if str(o["id"]) in g["rows"] or ph.get("license_code") not in LICENCES:
                        continue
                    c, how = queue_match(group, t.get("name"), t.get("rank"), by_group, genera, acc)
                    if c and medium_from_api_url(ph.get("url")):
                        g["rows"][str(o["id"])] = row(o, group, c, how)
                atomic_write_json(STATE, state)
                if g["total"] <= 200:
                    break
            log(f"{group}: {len(g['rows'])} kept from {g['pages']} pages ({g['total']} in the queue window)")
    finally:
        atomic_write_json(STATE, state)
    rows = [r for g in state["groups"].values() for r in list(g["rows"].values())[:PER_GROUP]]
    df = pd.DataFrame(rows).drop_duplicates("obs_id")
    df["drawn"] = state["drawn"]
    atomic_parquet(df, DATA / "queue_sample.parquet")
    log(f"queue sample: {len(df):,} rows; by level {df.level.value_counts().to_dict()}")


if __name__ == "__main__":
    main()
