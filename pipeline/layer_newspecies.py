"""Module 3: follow-up on species described from India since FIRST_YEAR (2007). A dated layer, like the iNaturalist one.

Steps (each saved in R2 cache/newspecies/state_<month>.json, so a run can stop and continue):
  1. names     new species from Plazi (Indian holotype, "sp. nov."), BSI Plant Discoveries and ZSI Animal
               Discoveries (new to science)
  2. downloads GBIF query Y (records since FIRST_YEAR by species, year, kind) and query V (unmatched names as published),
               one after the other
  3. match     each name to a species in the latest snapshot: exact name, then GBIF's match against the
               Catalogue of Life (synonyms), then the name as published in GBIF records
  4. status    "recorded": a record dated after the description year that is not copied from a paper;
               "later papers": only records copied from later papers; "no public record since"
Output: layers/newspecies/<month>/new_species.json and layers/newspecies/latest.json

Usage: python -m pipeline.layer_newspecies [--publish] [--force] [--minutes 200]
"""

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests

from pipeline import bsi, gbif, health, zsi_discoveries
from pipeline.util import now

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "newspecies"
FIRST_YEAR = gbif.NEW_SPECIES_FROM
COL_XR = "7ddf754f-d193-4cc9-b351-99906754a03b"   # Catalogue of Life eXtended Release, as a GBIF checklist
SP_NOV = re.compile(r"^\s*(sp\.?\s*nov\.?|nov\.?\s*sp\.?)\s*$", re.I)
QUERIES = ["recent_history", "verbatim_names"]
# BSI report sections, for names not matched to a species in the snapshot.
BSI_GROUP = {"SEED PLANTS": "Plants: other flowering plants & conifers", "PTERIDOPHYTES": "Plants: ferns & lycophytes",
             "BRYOPHYTES": "Mosses & liverworts", "LICHENS": "Lichens", "ALGAE": "Algae & diatoms", "FUNGI": "Fungi",
             "MICROBES": "Other"}
DONE, FAILED = "SUCCEEDED", ("FAILED", "KILLED", "CANCELLED", "FILE_ERASED")



def binomial(name):
    parts = re.sub(r"[^A-Za-z\- ]", " ", name or "").split()
    return " ".join(parts[:2]) if len(parts) >= 2 and parts[0][:1].isupper() and parts[1].islower() else None


def plazi_names(http, done=None, save=None):
    """done: {year: rows} already fetched this month; save() is called after each year."""
    done = {} if done is None else done
    fields = "tax.name+tax.status+bib.year+bib.source+matCit.typeStatus+matCit.region+doc.uuid"
    for year in range(FIRST_YEAR, datetime.now(timezone.utc).year + 1):
        if str(year) in done:
            continue
        out = []
        url = (f"https://tb.plazi.org/GgServer/srsStats/stats?outputFields={fields}&groupingFields={fields}"
               f"&FP-matCit.country=India&FP-bib.year={year}&FP-matCit.typeStatus=holotype&format=JSON")
        r = http.get(url, timeout=120)
        r.raise_for_status()
        for row in r.json()["data"]:
            name = binomial(row.get("TaxName"))
            if name and SP_NOV.match(row.get("TaxStatus") or ""):
                out.append({"name": name, "year": int(row["BibYear"]), "source": "Plazi", "journal": row.get("BibSource"),
                            "state": row.get("MatCitRegion") or "", "link": f"https://tb.plazi.org/GgServer/summary/{row['DocUuid']}"})
        done[str(year)] = out
        if save:
            save()
        time.sleep(1.5)
    return [r for y in sorted(done) for r in done[y]]


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


def group_hint(n):
    """Overlooked group from the BSI or ZSI section, for names not matched to a species."""
    return BSI_GROUP.get(n.get("bsi_group", "")) or zsi_discoveries.ZSI_GROUP.get(n.get("zsi_group", ""))


def merge(names):
    """One row per name: earliest year; all sources kept."""
    by = {}
    for n in names:
        if len((n["name"].split() + ["", ""])[1]) < 2:   # "Cryptocephalus s": a cut name, not a species
            continue
        cur = by.get(n["name"])
        if not cur:
            by[n["name"]] = dict(n, sources=[n["source"]])
            continue
        if n["source"] not in cur["sources"]:
            cur["sources"].append(n["source"])
        if n["year"] < cur["year"]:
            cur.update(year=n["year"], journal=n["journal"] or cur["journal"], link=n["link"])
        cur["state"] = cur["state"] or n["state"]
        for k in ("bsi_group", "zsi_group"):  # section hints, whichever source listed the name first
            if n.get(k) and not cur.get(k):
                cur[k] = n[k]
    return sorted(by.values(), key=lambda r: (r["year"], r["name"]))


def gbif_match(http, name, cache, need_classification=False):
    hit = cache.get(name, "missing")
    if hit != "missing" and not (need_classification and hit and "classification" not in hit):
        return hit
    r = http.get("https://api.gbif.org/v2/species/match", params={"scientificName": name, "checklistKey": COL_XR}, timeout=60)
    time.sleep(1.1)
    if not r.ok:
        return None
    d = r.json()
    usage, accepted = d.get("usage") or {}, d.get("acceptedUsage") or {}
    exact = (d.get("diagnostics") or {}).get("matchType") == "EXACT"
    ranks = {c.get("rank", "").lower(): c.get("name") for c in d.get("classification") or []}
    res = {"key": accepted.get("key") or usage.get("key"), "synonym": bool(d.get("synonym")), "name": usage.get("name"),
           "accepted_name": accepted.get("canonicalName") or usage.get("canonicalName"),
           "classification": {r: ranks.get(r) for r in ("kingdom", "phylum", "class", "order", "family")}
           } if exact and usage.get("key") else None
    cache[name] = res
    return res


def group_from(con, c):
    """Overlooked group (fnf rules) from a classification dict, or None."""
    if not c or not any(c.values()):
        return None
    from pipeline.groups import GROUP_SQL
    row = con.execute(f"""SELECT {GROUP_SQL} FROM (SELECT ?::VARCHAR AS kingdom, ?::VARCHAR AS phylum,
                         ?::VARCHAR AS class, ?::VARCHAR AS "order", ?::VARCHAR AS family)""",
                      [c.get("kingdom"), c.get("phylum"), c.get("class"), c.get("order"), c.get("family")]).fetchone()
    return row[0] if row and row[0] != "Other" else ("Other" if row else None)


def after(rows):
    """Records after the description year: (observations, records from papers, latest year).
    rows: (year, basis of record, records, sequence_only); sequences with no coordinates do not count."""
    rows = [(y, b, n) for y, b, n, seq in rows if not seq]
    obs = sum(n for y, b, n in rows if b != "MATERIAL_CITATION")
    papers = sum(n for y, b, n in rows if b == "MATERIAL_CITATION")
    latest = max((y for y, b, n in rows if b != "MATERIAL_CITATION"), default=None)
    return obs, papers, latest


# The name as published, then the end of the text or a space: "Choroterpes latus Kluge, 2023", not "C. latusoides".
V_NAME = "(lower(v_scientificname) = lower(?) OR starts_with(lower(v_scientificname), lower(?) || ' '))"


def verbatim_rows(con, name, year):
    """Query V rows for a name as published, after the description year."""
    return con.execute(f"""SELECT year, basisofrecord, n_records, sequence_only FROM v
                           WHERE year > ? AND {V_NAME} ORDER BY year, basisofrecord""", [year, name, name]).fetchall()


def match_all(con, http, state, species_by_name, in_snapshot, group_of, mcache, deadline, save_cache):
    """Status of each name. Returns None if the time limit is reached first."""
    out = []
    next_save = time.monotonic() + 600
    for i, n in enumerate(state["names"]):
        if deadline and time.monotonic() > deadline:
            return None
        key, how = species_by_name.get(n["name"]), "exact name"
        if not key:
            m = gbif_match(http, n["name"], mcache)
            if m and m.get("key"):
                key, how = m["key"], "synonym" if m["synonym"] else "exact name (GBIF match)"
        rows = con.execute("SELECT year, basisofrecord, n_records, sequence_only FROM y WHERE specieskey = ? AND year > ?",
                           [key, n["year"]]).fetchall() if key else []
        if not rows:
            vrows = verbatim_rows(con, n["name"], n["year"])
            if vrows:
                rows, how = vrows, "name as published in GBIF"
        obs, papers, latest = after(rows)
        # Any public record in India at all, including the type material from the description itself.
        any_record = bool(key and (key in in_snapshot or con.execute(
            "SELECT 1 FROM y WHERE specieskey = ? AND NOT sequence_only LIMIT 1", [key]).fetchone()))
        any_record = any_record or bool(con.execute(
            f"SELECT 1 FROM v WHERE NOT sequence_only AND {V_NAME} LIMIT 1", [n["name"], n["name"]]).fetchone())
        status = "recorded" if obs else ("later_papers" if papers else "none")
        grp = group_of.get(key) or group_hint(n)
        if not grp:
            m = gbif_match(http, n["name"], mcache, need_classification=True)
            grp = group_from(con, (m or {}).get("classification")) or "Not matched yet"
        out.append({**{k: n[k] for k in ("name", "year", "sources", "journal", "state", "link")}, "group": grp,
                    "key": key, "matched_by": how if (key or rows) else "not found",
                    "status": status, "latest_after": latest, "records_after": obs, "papers_after": papers,
                    "any_record": any_record})
        if time.monotonic() > next_save:
            next_save = time.monotonic() + 600
            print(f"{i} of {len(state['names'])} names; saving the match cache", flush=True)
            save_cache()
    return out


# The page's file format. Version 1 (no "version" key) had a list of row objects under "species".
# Version 2 is columnar: one array per field, with repeated strings stored once in "lookups".
FORMAT_VERSION = 2
PAGE_FIELDS = ("name", "year", "sources", "journal", "state", "link", "group", "key", "matched_by", "status",
               "latest_after", "any_record")
LOOKUP_FIELDS = ("sources", "journal", "state", "group", "matched_by", "status")


def _link_prefix(link, counts):
    """A link used more than once is its own prefix; otherwise the prefix ends at the last '/'."""
    return link if counts[link] > 1 else link[:link.rfind("/") + 1]


def compact(rows):
    """Columnar form of the page fields of rows, for the site. expand() reverses it."""
    lookups = {f: [] for f in (*LOOKUP_FIELDS, "link")}
    index = {f: {} for f in lookups}

    def code(field, value):
        k = json.dumps(value)
        if k not in index[field]:
            index[field][k] = len(lookups[field])
            lookups[field].append(value)
        return index[field][k]

    link_counts = {}
    for r in rows:
        link_counts[r["link"]] = link_counts.get(r["link"], 0) + 1
    cols = {f: [] for f in (*PAGE_FIELDS, "link_rest")}
    for r in rows:
        for f in PAGE_FIELDS:
            v = r[f]
            if f in LOOKUP_FIELDS:
                v = code(f, v)
            elif f == "link":
                prefix = _link_prefix(v, link_counts)
                cols["link_rest"].append(v[len(prefix):])
                v = code("link", prefix)
            elif f == "any_record":
                v = int(bool(v))
            cols[f].append(v)
    return {"version": FORMAT_VERSION, "n": len(rows), "lookups": lookups, "columns": cols}


def expand(doc):
    """Rows (dicts of the page fields) from either format of the file."""
    if "version" not in doc:
        return doc["species"]
    lk, cols = doc["lookups"], doc["columns"]
    out = []
    for i in range(doc["n"]):
        r = {}
        for f in PAGE_FIELDS:
            v = cols[f][i]
            if f in LOOKUP_FIELDS:
                v = lk[f][v]
            elif f == "link":
                v = lk["link"][v] + cols["link_rest"][i]
            elif f == "any_record":
                v = bool(v)
            r[f] = v
        out.append(r)
    return out


def check_window(state):
    """A state built for another first year (names and GBIF queries Y and V) starts the month again.
    Returns True when it reset the state."""
    if state.get("window") == FIRST_YEAR:
        return False
    for k in ("names", "names_at", "plazi", "done"):
        state.pop(k, None)
    state["downloads"] = {q: {"status": "WAITING"} for q in QUERIES}
    state["window"] = FIRST_YEAR
    return True


def check_queries(state):
    """Downloads made with another text of queries Y or V are made again; the names stay.
    Returns True when it reset the downloads."""
    fp = hashlib.sha256("\n".join(gbif.build_sql(q) for q in QUERIES).encode()).hexdigest()[:16]
    if state.get("queries") == fp:
        return False
    state["downloads"] = {q: {"status": "WAITING"} for q in QUERIES}
    state.pop("done", None)
    state["queries"] = fp
    return True


def run(publish, force=False, minutes=None):
    from pipeline import r2
    deadline = time.monotonic() + minutes * 60 if minutes else None
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    CACHE.mkdir(parents=True, exist_ok=True)
    http = gbif.session()
    plain = requests.Session()
    plain.headers["User-Agent"] = health.ua()
    s3 = r2.client() if publish else None
    state_key = f"cache/newspecies/state_{month}.json"
    state = (r2.get_json(s3, state_key) if s3 else None) or {"month": month, "downloads": {q: {"status": "WAITING"} for q in QUERIES}}
    save = lambda: (r2.put_json(s3, state, state_key) if s3 else (CACHE / f"state_{month}.json").write_text(json.dumps(state)))
    if check_window(state):
        print(f"new-species window is now {FIRST_YEAR} onwards; names and GBIF downloads start again")
        save()
    if check_queries(state):
        print("the GBIF queries changed; the downloads start again")
        save()
    if force:
        state.pop("done", None)
    if state.get("done"):
        print(f"new species layer for {month} is done ({state['done']}); nothing to do")
        return

    # 1. Names (once a month).
    if "names" not in state:
        names = merge(plazi_names(plain, state.setdefault("plazi", {}), save) + bsi_names(plain, s3)
                      + zsi_discoveries.names(plain, s3, FIRST_YEAR))
        state["names"] = names
        state["names_at"] = now()
        state.pop("plazi", None)
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
        gbif.ensure(http, meta)
        d[q]["doi"] = meta["doi"]
    from pipeline.ledger import unpack
    con = duckdb.connect()
    con.sql(f"""CREATE TABLE y AS SELECT * FROM read_csv('{unpack(d['recent_history']['key'])}', delim='\t', header=true, quote='',
                columns={{'specieskey':'VARCHAR','year':'INTEGER','basisofrecord':'VARCHAR','sequence_only':'BOOLEAN',
                         'n_records':'BIGINT'}})""")
    con.sql(f"""CREATE TABLE v AS SELECT * FROM read_csv('{unpack(d['verbatim_names']['key'])}', delim='\t', header=true, quote='',
                columns={{'v_scientificname':'VARCHAR','year':'INTEGER','basisofrecord':'VARCHAR','sequence_only':'BOOLEAN',
                         'n_records':'BIGINT'}})""")
    species_by_name = {}
    if s3:
        latest = r2.get_json(s3, "latest.json")
        f = CACHE / "species.parquet"
        s3.download_file(r2.bucket(), latest["base"] + "species.parquet", str(f))
        species_by_name = dict(con.sql(f"SELECT name, species_key FROM '{f}'").fetchall())
        in_snapshot = set(species_by_name.values())
        from pipeline.groups import GROUP_SQL
        group_of = dict(con.sql(f"SELECT species_key, {GROUP_SQL} FROM '{f}'").fetchall())
        snapshot_run = latest["run_id"]
    else:
        snapshot_run, group_of, in_snapshot = None, {}, set()
    match_cache_key = "cache/newspecies/gbif_match.json"
    mcache = (r2.get_json(s3, match_cache_key) if s3 else None) or {}

    try:
        out = match_all(con, http, state, species_by_name, in_snapshot, group_of, mcache, deadline,
                        lambda: s3 and r2.put_json(s3, mcache, match_cache_key))
    finally:
        if s3:  # keep the matches done, also when the run stops or fails
            r2.put_json(s3, mcache, match_cache_key)
    if out is None:
        print(f"time limit reached; {len(mcache)} names matched so far; the next run continues")
        return

    result = {"month": month, "built": now(), "snapshot": snapshot_run, "first_year": FIRST_YEAR,
              "downloads": [{"query": q, "key": d[q]["key"], "doi": d[q]["doi"], "created": metas[q].get("created"),
                             "records": metas[q].get("totalRecords")} for q in QUERIES],
              "sources": ["Plazi TreatmentBank (CC0)", "Botanical Survey of India, Plant Discoveries (reproduced with acknowledgement)",
                          "Zoological Survey of India, Animal Discoveries (reproduced with acknowledgement)"],
              **compact(out)}
    folder = ROOT / "data" / "layers" / "newspecies" / month
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "new_species.json").write_text(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
    counts = {s: sum(1 for r in out if r["status"] == s) for s in ("recorded", "later_papers", "none")}
    counts["any_record"] = sum(1 for r in out if r["any_record"])
    print(f"{len(out)} new species: {counts}")
    if s3:
        r2.sync_file(s3, folder / "new_species.json", f"layers/newspecies/{month}/new_species.json", immutable=False)
        r2.put_json(s3, {"month": month, "updated": now(), "file": f"layers/newspecies/{month}/new_species.json",
                         "snapshot": snapshot_run, "counts": counts}, "layers/newspecies/latest.json")
    state["done"] = now()  # last, so a failed upload is done again by the next run
    save()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--publish", action="store_true")
    p.add_argument("--force", action="store_true", help="recompute this month from the downloads already made")
    p.add_argument("--minutes", type=int, help="stop cleanly after this many minutes; the next run continues")
    a = p.parse_args()
    run(a.publish, a.force, a.minutes)


if __name__ == "__main__":
    main()
