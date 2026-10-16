"""Check every source before a refresh: one cheap request each, one at a time, 1.5 s apart.

Each check reports ok, HTTP status, time, and a fingerprint (ETag, Last-Modified, size or a count)
that later steps use to fetch only what changed. Critical sources stop the run; the others are
marked stale and keep last month's data.

Usage: python -m pipeline.health [--out health.json]
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from pipeline import districts

ROOT = Path(__file__).resolve().parent.parent
GAP = 1.5
TIMEOUT = 40


def ua():
    email = os.environ.get("GBIF_EMAIL", "")
    return f"overlooked-india (+https://github.com/urbanmorph/overlooked{'; ' + email if email else ''})"


def _probe(http, method, url, expect=None, **kw):
    t = time.time()
    try:
        r = http.request(method, url, timeout=TIMEOUT, allow_redirects=True, **kw)
        ms = round((time.time() - t) * 1000)
        ok = r.ok and (expect(r) if expect else True)
        fp = {k: r.headers.get(k) for k in ("ETag", "Last-Modified", "Content-Length") if r.headers.get(k)}
        return r, {"ok": bool(ok), "status": r.status_code, "ms": ms, "fingerprint": fp}
    except requests.RequestException as e:
        return None, {"ok": False, "status": None, "ms": round((time.time() - t) * 1000), "error": type(e).__name__}


def _json_count(key):
    def check(r):
        try:
            return key in r.json()
        except ValueError:
            return False
    return check


def _html_contains(text):
    return lambda r: "text/html" in r.headers.get("Content-Type", "") and text.lower() in r.text.lower()


def check_all(r2_client=None):
    load_dotenv(ROOT / ".env", override=True)
    http = requests.Session()
    http.headers["User-Agent"] = ua()
    results = {}

    def add(name, critical, used_for, method, url, expect=None, **kw):
        r, res = _probe(http, method, url, expect, **kw)
        res.update(critical=critical, used_for=used_for, url=url)
        results[name] = (r, res)
        time.sleep(GAP)
        return r, res

    # GBIF: search API, with a fingerprint of how much changed recently.
    r, res = add("gbif_api", True, "all modules", "GET",
                 "https://api.gbif.org/v1/occurrence/search?country=IN&hasCoordinate=true&occurrenceStatus=PRESENT&limit=0",
                 _json_count("count"))
    if r is not None and res["ok"]:
        res["fingerprint"]["india_records"] = r.json()["count"]
    # GBIF downloads: the account can log in and list its downloads.
    user = os.environ.get("GBIF_USER")
    if user:
        add("gbif_downloads", True, "monthly downloads", "GET",
            f"https://api.gbif.org/v1/occurrence/download/user/{user}?limit=1",
            auth=(user, os.environ.get("GBIF_PASSWORD", "")))
        results["gbif_downloads"][1]["url"] = "https://api.gbif.org/v1/occurrence/download/user/<account>"
    else:
        results["gbif_downloads"] = (None, {"ok": False, "critical": True, "used_for": "monthly downloads",
                                            "error": "GBIF_USER not set"})
    add("lgd_boundaries", False, "district map and placement", "HEAD", districts.URL)
    add("plazi", False, "module 3: new species", "GET",
        "https://tb.plazi.org/GgServer/srsStats/stats?outputFields=doc.count&FP-matCit.country=India&format=JSON",
        _json_count("data"))
    add("ipni", False, "module 3: new plant names", "GET",
        "https://www.ipni.org/api/1/search?q=published:2025&perPage=1", _json_count("totalResults"))
    add("index_fungorum", False, "module 3: new fungus names", "GET",
        "https://www.indexfungorum.org/ixfwebservice/fungus.asmx/NewNamesInRange?rank=sp.&startDate=20250101&endDate=20250102",
        lambda r: "xml" in r.headers.get("Content-Type", ""))
    add("inaturalist", False, "iNaturalist (via GBIF; direct checks planned)", "GET",
        "https://api.inaturalist.org/v1/observations?place_id=6681&quality_grade=research&per_page=0",
        _json_count("total_results"))
    add("ibp_gbif_dataset", False, "India Biodiversity Portal (via GBIF)", "GET",
        "https://api.gbif.org/v1/dataset/c6b86c40-ff71-4e5e-902c-111f400d0d56", _json_count("modified"))
    add("kew_wcvp", False, "plant checklist (later module)", "HEAD",
        "https://sftp.kew.org/pub/data-repositories/WCVP/wcvp.zip")
    add("bsi_plant_discoveries", False, "module 3: new plant species and records", "GET",
        "https://bsi.gov.in/page/en/national-wild-life-action-plan", _html_contains("Plant Discoveries"))
    add("bsi_ivh", False, "BSI type specimens", "GET",
        "https://ivh.bsi.gov.in/phanerogams/en?search_bar=CAL00003107&selection=szBarcode", _html_contains("CAL0000310"))

    # R2: the pipeline's own keys can reach the bucket.
    if r2_client is not None or os.environ.get("R2_ENDPOINT"):
        from pipeline import r2
        t = time.time()
        try:
            s3 = r2_client or r2.client()
            # The bucket key may read and write but not list; a lookup proves the key works
            # (found or "not found" both mean access is fine; "access denied" does not).
            r2.exists(s3, "latest.json")
            res = {"ok": True, "status": 200}
        except Exception as e:  # any failure here is a stop
            res = {"ok": False, "status": None, "error": type(e).__name__}
        res.update(ms=round((time.time() - t) * 1000), critical=True, used_for="publishing", url="r2://<bucket>")
        results["r2"] = (None, res)

    report = {
        "checked": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": {k: v[1] for k, v in results.items()},
    }
    report["critical_failures"] = [k for k, v in report["sources"].items() if v.get("critical") and not v["ok"]]
    report["warnings"] = [k for k, v in report["sources"].items() if not v.get("critical") and not v["ok"]]
    return report


def changed(report, previous, name):
    """True if a source's fingerprint differs from the previous check (or there was none)."""
    if not previous or name not in previous.get("sources", {}):
        return True
    a = report["sources"].get(name, {}).get("fingerprint") or {}
    b = previous["sources"][name].get("fingerprint") or {}
    return not a or a != b


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out")
    a = p.parse_args()
    report = check_all()
    text = json.dumps(report, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    for k, v in report["sources"].items():
        mark = "ok  " if v["ok"] else ("STOP" if v.get("critical") else "warn")
        print(f"{mark} {k:24} {v.get('status')!s:5} {v.get('ms', '')!s:>6} ms  {v.get('error', '')}")


if __name__ == "__main__":
    main()
