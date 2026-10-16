"""Module 3: follow-up on species described from India since 2015. A dated layer, like the iNaturalist one.

Steps (each saved in R2 cache/newspecies/state_<month>.json, so a run can stop and continue):
  1. names     new species from Plazi (Indian holotype, "sp. nov.") and BSI Plant Discoveries (new to science)
  2. downloads GBIF query Y (records since 2015 by species, year, kind) and query V (unmatched names as published),
               one after the other
  3. match     each name to a species in the latest snapshot: exact name, then GBIF's match against the
               Catalogue of Life (synonyms), then the name as published in GBIF records
  4. status    "recorded": a record dated after the description year that is not copied from a paper;
               "later papers": only records copied from later papers; "no public record since"
Output: layers/newspecies/<month>/new_species.json and layers/newspecies/latest.json

Usage: python -m pipeline.layer_newspecies [--publish]
"""

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests

from pipeline import bsi, gbif, health

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "newspecies"
FIRST_YEAR = 2015
COL_XR = "7ddf754f-d193-4cc9-b351-99906754a03b"   # Catalogue of Life eXtended Release, as a GBIF checklist
SP_NOV = re.compile(r"^\s*(sp\.?\s*nov\.?|nov\.?\s*sp\.?)\s*$", re.I)
QUERIES = ["recent_history", "verbatim_names"]
# BSI report sections, for names not matched to a species in the snapshot.
BSI_GROUP = {"SEED PLANTS": "Plants: other flowering plants & conifers", "PTERIDOPHYTES": "Plants: ferns & lycophytes",
             "BRYOPHYTES": "Mosses & liverworts", "LICHENS": "Lichens", "ALGAE": "Algae & diatoms", "FUNGI": "Fungi",
             "MICROBES": "Other"}
DONE, FAILED = "SUCCEEDED", ("FAILED", "KILLED", "CANCELLED", "FILE_ERASED")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def binomial(name):
    parts = re.sub(r"[^A-Za-z\- ]", " ", name or "").split()
    return " ".join(parts[:2]) if len(parts) >= 2 and parts[0][:1].isupper() and parts[1].islower() else None


def plazi_names(http):
    out = []
    fields = "tax.name+tax.status+bib.year+bib.source+matCit.typeStatus+matCit.region+doc.uuid"
    for year in range(FIRST_YEAR, datetime.now(timezone.utc).year + 1):
        url = (f"https://tb.plazi.org/GgServer/srsStats/stats?outputFields={fields}&groupingFields={fields}"
               f"&FP-matCit.country=India&FP-bib.year={year}&FP-matCit.typeStatus=holotype&format=JSON")
        r = http.get(url, timeout=120)
        r.raise_for_status()
        for row in r.json()["data"]:
            name = binomial(row.get("TaxName"))
            if name and SP_NOV.match(row.get("TaxStatus") or ""):
                out.append({"name": name, "year": int(row["BibYear"]), "source": "Plazi", "journal": row.get("BibSource"),
                            "state": row.get("MatCitRegion") or "", "link": f"https://tb.plazi.org/GgServer/summary/{row['DocUuid']}"})
        time.sleep(1.5)
    return out


def bsi_names(http, s3):
    out = []
    for year, entries in bsi.sync(http, s3).items():
        for e in entries:
            name = binomial(e["name"])
            if name and e["kind"] == "new_to_science" and e["rank"] == "species" and e["name_check"] != "needs_review":
                out.append({"name": name, "year": int(e["year"]), "source": "BSI Plant Discoveries",
                            "journal": "", "state": (e.get("states") or "").title(), "bsi_group": e.get("group") or "",
                            "link": "https://bsi.gov.in/page/en/national-wild-life-action-plan"})
    return out


def merge(names):
    """One row per name: earliest year; all sources kept."""
    by = {}
    for n in names:
        cur = by.get(n["name"])
        if not cur:
            by[n["name"]] = dict(n, sources=[n["source"]])
            continue
        if n["source"] not in cur["sources"]:
            cur["sources"].append(n["source"])
        if n["year"] < cur["year"]:
            cur.update(year=n["year"], journal=n["journal"] or cur["journal"], link=n["link"])
        cur["state"] = cur["state"] or n["state"]
    return sorted(by.values(), key=lambda r: (r["year"], r["name"]))


def gbif_match(http, name, cache):
    if name in cache:
        return cache[name]
    r = http.get("https://api.gbif.org/v2/species/match", params={"scientificName": name, "checklistKey": COL_XR}, timeout=60)
    time.sleep(1.1)
    if not r.ok:
        return None
    d = r.json()
    usage, accepted = d.get("usage") or {}, d.get("acceptedUsage") or {}
    exact = (d.get("diagnostics") or {}).get("matchType") == "EXACT"
    res = {"key": accepted.get("key") or usage.get("key"), "synonym": bool(d.get("synonym")),
           "name": usage.get("name")} if exact and usage.get("key") else None
    cache[name] = res
    return res


def run(publish):
    from pipeline import r2
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    CACHE.mkdir(parents=True, exist_ok=True)
    http = gbif.session()
    plain = requests.Session()
    plain.headers["User-Agent"] = health.ua()
    s3 = r2.client() if publish else None
    state_key = f"cache/newspecies/state_{month}.json"
    state = (r2.get_json(s3, state_key) if s3 else None) or {"month": month, "downloads": {q: {"status": "WAITING"} for q in QUERIES}}
    save = lambda: (r2.put_json(s3, state, state_key) if s3 else (CACHE / f"state_{month}.json").write_text(json.dumps(state)))
    if state.get("done"):
        print(f"new species layer for {month} is done ({state['done']}); nothing to do")
        return

    # 1. Names (once a month).
    if "names" not in state:
        names = merge(plazi_names(plain) + bsi_names(plain, s3))
        state["names"] = names
        state["names_at"] = now()
        save()
        print(f"names: {len(names)} new species since {FIRST_YEAR}")

    # 2. Downloads, one at a time.
    d = state["downloads"]
    for q in QUERIES:
        if d[q].get("key") and d[q]["status"] not in (DONE, *FAILED):
            d[q]["status"] = http.get(f"{gbif.API}/{d[q]['key']}", timeout=60).json()["status"]
    if any(x["status"] in FAILED for x in d.values()):
        for q, x in d.items():
            if x["status"] in FAILED:
                d[q] = {"status": "WAITING"}  # try again next run
    if not any(x.get("key") and x["status"] != DONE for x in d.values()):
        for q in QUERIES:
            if not d[q].get("key"):
                key = gbif.submit(http, gbif.build_sql(q))
                if key:
                    d[q] = {"key": key, "status": "PREPARING", "requested": now()}
                    print(f"{q}: requested {key}")
                else:
                    print("GBIF is busy for this account (429); next run tries again")
                break
    save()
    if not all(x["status"] == DONE for x in d.values()):
        print("waiting for GBIF:", {q: x["status"] for q, x in d.items()})
        return

    # 3. Fetch and match.
    metas = {}
    for q in QUERIES:
        meta = http.get(f"{gbif.API}/{d[q]['key']}", timeout=60).json()
        metas[q] = meta
        if not (gbif.RAW / f"{meta['key']}.zip").exists():
            gbif.fetch(http, meta)
        d[q]["doi"] = meta["doi"]
    from pipeline.ledger import unpack
    con = duckdb.connect()
    con.sql(f"""CREATE TABLE y AS SELECT * FROM read_csv('{unpack(d['recent_history']['key'])}', delim='\t', header=true, quote='',
                columns={{'specieskey':'VARCHAR','year':'INTEGER','basisofrecord':'VARCHAR','n_records':'BIGINT'}})""")
    con.sql(f"""CREATE TABLE v AS SELECT * FROM read_csv('{unpack(d['verbatim_names']['key'])}', delim='\t', header=true, quote='',
                columns={{'v_scientificname':'VARCHAR','year':'INTEGER','basisofrecord':'VARCHAR','n_records':'BIGINT'}})""")
    species_by_name = {}
    if s3:
        latest = r2.get_json(s3, "latest.json")
        f = CACHE / "species.parquet"
        s3.download_file(r2.bucket(), latest["base"] + "species.parquet", str(f))
        species_by_name = dict(con.sql(f"SELECT name, species_key FROM '{f}'").fetchall())
        from pipeline.groups import GROUP_SQL
        group_of = dict(con.sql(f"SELECT species_key, {GROUP_SQL} FROM '{f}'").fetchall())
        snapshot_run = latest["run_id"]
    else:
        snapshot_run, group_of = None, {}
    match_cache_key = "cache/newspecies/gbif_match.json"
    mcache = (r2.get_json(s3, match_cache_key) if s3 else None) or {}

    # Records after the description year, by key and by name as published.
    def after(rows):
        obs = sum(n for y, b, n in rows if b != "MATERIAL_CITATION")
        papers = sum(n for y, b, n in rows if b == "MATERIAL_CITATION")
        latest = max((y for y, b, n in rows if b != "MATERIAL_CITATION"), default=None)
        return obs, papers, latest

    out = []
    for i, n in enumerate(state["names"]):
        key, how = species_by_name.get(n["name"]), "exact name"
        if not key:
            m = gbif_match(http, n["name"], mcache)
            if m and m.get("key"):
                key, how = m["key"], "synonym" if m["synonym"] else "exact name (GBIF match)"
        rows = con.execute("SELECT year, basisofrecord, n_records FROM y WHERE specieskey = ? AND year > ?",
                           [key, n["year"]]).fetchall() if key else []
        if not rows:
            vrows = con.execute("""SELECT year, basisofrecord, n_records FROM v
                                   WHERE year > ? AND lower(v_scientificname) LIKE lower(?) || '%'""",
                                [n["year"], n["name"]]).fetchall()
            if vrows:
                rows, how = vrows, "name as published in GBIF"
        obs, papers, latest = after(rows)
        status = "recorded" if obs else ("later_papers" if papers else "none")
        grp = group_of.get(key) or BSI_GROUP.get(n.get("bsi_group", ""), "Not matched yet")
        out.append({**{k: n[k] for k in ("name", "year", "sources", "journal", "state", "link")}, "group": grp,
                    "bsi_group": n.get("bsi_group", ""), "key": key, "matched_by": how if (key or rows) else "not found",
                    "status": status, "latest_after": latest, "records_after": obs, "papers_after": papers})
        if s3 and i % 200 == 0:
            r2.put_json(s3, mcache, match_cache_key)
    if s3:
        r2.put_json(s3, mcache, match_cache_key)

    result = {"month": month, "built": now(), "snapshot": snapshot_run, "first_year": FIRST_YEAR,
              "downloads": [{"query": q, "key": d[q]["key"], "doi": d[q]["doi"], "created": metas[q].get("created"),
                             "records": metas[q].get("totalRecords")} for q in QUERIES],
              "sources": ["Plazi TreatmentBank (CC0)", "Botanical Survey of India, Plant Discoveries (reproduced with acknowledgement)"],
              "species": out}
    folder = ROOT / "data" / "layers" / "newspecies" / month
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "new_species.json").write_text(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
    counts = {s: sum(1 for r in out if r["status"] == s) for s in ("recorded", "later_papers", "none")}
    print(f"{len(out)} new species: {counts}")
    state["done"] = now()
    save()
    if s3:
        r2.sync_file(s3, folder / "new_species.json", f"layers/newspecies/{month}/new_species.json", immutable=False)
        r2.put_json(s3, {"month": month, "updated": now(), "file": f"layers/newspecies/{month}/new_species.json",
                         "snapshot": snapshot_run, "counts": counts}, "layers/newspecies/latest.json")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--publish", action="store_true")
    run(p.parse_args().publish)


if __name__ == "__main__":
    main()
