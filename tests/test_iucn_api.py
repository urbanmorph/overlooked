"""IUCN Red List API: the latest global assessment of every assessed species of the India list, with population
trend, threats and habitats. A fake API stands in for api.iucnredlist.org."""

import json
import time

import pytest

from pipeline import iucn_api


def assessment(aid, name, cat="LC", year="2020", trend="Stable", india=True):
    return {"assessment_id": aid, "sis_taxon_id": aid * 10, "taxon": {"scientific_name": name}, "year_published": year,
            "assessment_date": f"{year}-01-01T00:00:00.000+00:00", "criteria": "B1ab(iii)" if cat in ("CR", "EN", "VU") else None,
            "red_list_category": {"code": cat}, "population_trend": {"description": {"en": trend}, "code": "0"},
            "possibly_extinct": False, "possibly_extinct_in_the_wild": False, "latest": True,
            "threats": [{"code": "1_1", "timing": "Ongoing", "scope": "Minority (<50%)", "severity": "Negligible declines"}],
            "habitats": [{"code": "1_5", "majorImportance": "Yes", "suitability": "Suitable"}],
            "systems": [{"description": {"en": "Terrestrial"}, "code": "0"}],
            "locations": ([{"code": "IN", "origin": "Native", "presence": "Extant", "is_endemic": True}] if india else [])
            + [{"code": "NP", "origin": "Native", "presence": "Extant", "is_endemic": False}],
            "url": f"https://www.iucnredlist.org/species/{aid * 10}/{aid}",
            "citation": f"Smith, A. & Rao, B. {year}. {name}. The IUCN Red List of Threatened Species {year}: e.T{aid * 10}A{aid}.",
            "credits": [{"credit_type_name": "assessor", "full": "Smith, A. & Rao, B."},
                        {"credit_type_name": "evaluator", "full": "Cox, N.A."}]}


def listed(aid, name, cat="LC", latest=True, scope="1"):
    return {"assessment_id": aid, "taxon_scientific_name": name, "red_list_category_code": cat, "latest": latest,
            "scopes": [{"code": scope}], "year_published": "2020"}


class FakeApi:
    """India's list over two pages; Cus dus is assessed but not mapped to India; Zus zus is not assessed."""

    def __init__(self, version="2026-1"):
        self.version, self.calls = version, []
        self.pages = {1: [listed(1, "Aus bus"), listed(9, "Aus bus", latest=False)], 2: [listed(2, "Bus cus", "EN")]}
        self.full = {1: assessment(1, "Aus bus"), 2: assessment(2, "Bus cus", "EN", trend="Decreasing"),
                     3: assessment(3, "Cus dus", "DD", "2008", trend="Unknown", india=False)}

    def get(self, path, params=None):
        self.calls.append(path)
        if path == "information/red_list_version":
            return {"red_list_version": self.version}
        if path == "countries/IN":
            return {"assessments": self.pages.get(params["page"], [])}, len(self.pages)
        if path == "taxa/scientific_name":
            name = f'{params["genus_name"]} {params["species_name"]}'
            return {"assessments": [listed(3, "Cus dus", "DD")]} if name == "Cus dus" else None
        if path.startswith("assessment/"):
            return self.full[int(path.split("/")[1])]
        raise AssertionError(path)


def test_compact_keeps_what_the_gaps_need():
    c = iucn_api.compact(assessment(2, "Bus cus", "EN", trend="Decreasing"))
    assert c["name"] == "Bus cus" and c["category"] == "EN" and c["year"] == 2020 and c["trend"] == "Decreasing"
    assert c["threats"] == [["1_1", "Ongoing", "Minority (<50%)", "Negligible declines"]]
    assert c["habitats"] == [["1_5", "Yes", "Suitable"]]
    assert c["india"] == {"origin": "Native", "presence": "Extant", "endemic": True}
    assert iucn_api.compact(assessment(3, "Cus dus", india=False))["india"] is None
    # Each assessment is cited like a journal paper (IUCN's citation guidance): keep its citation and assessors.
    assert c["citation"].startswith("Smith, A. & Rao, B. 2020. Bus cus. The IUCN Red List") and c["assessors"] == "Smith, A. & Rao, B." 


def test_harvest_reads_india_then_looks_up_the_rest_then_every_assessment(tmp_path):
    api, store = FakeApi(), iucn_api.Store(tmp_path / "store.json")
    assert iucn_api.harvest(api, store, ["Aus bus", "Bus cus", "Cus dus", "Zus zus"]) is True
    assert store.data["india"] == {"Aus bus": 1, "Bus cus": 2}          # latest, global scope only
    assert store.data["names"] == {"Cus dus": 3, "Zus zus": None}       # not in India's list: by name
    assert sorted(store.data["assessments"]) == ["1", "2", "3"]
    rows = {r["name"]: r for r in iucn_api.rows(store)}
    assert rows["Bus cus"]["trend"] == "Decreasing" and rows["Bus cus"]["in_india_list"] is True
    assert rows["Cus dus"]["in_india_list"] is False and rows["Cus dus"]["india_presence"] is None
    assert "Zus zus" not in rows


def test_a_second_run_asks_only_the_version(tmp_path):
    store = iucn_api.Store(tmp_path / "store.json")
    iucn_api.harvest(FakeApi(), store, ["Aus bus", "Cus dus"])
    again = FakeApi()
    assert iucn_api.harvest(again, iucn_api.Store(tmp_path / "store.json"), ["Aus bus", "Cus dus"]) is True
    assert again.calls == ["information/red_list_version"]


def test_a_new_red_list_version_reads_the_list_again_and_keeps_the_assessments(tmp_path):
    store = iucn_api.Store(tmp_path / "store.json")
    iucn_api.harvest(FakeApi(), store, ["Aus bus", "Bus cus"])
    new = FakeApi("2026-2")
    iucn_api.harvest(new, store, ["Aus bus", "Bus cus"])
    assert new.calls.count("countries/IN") == 2 and not [c for c in new.calls if c.startswith("assessment/")]


def test_a_time_limit_stops_cleanly_and_the_next_run_continues(tmp_path, monkeypatch):
    saved = []
    store = iucn_api.Store(tmp_path / "store.json")
    monkeypatch.setattr(store, "save", lambda: saved.append(1))
    assert iucn_api.harvest(FakeApi(), store, ["Aus bus", "Cus dus"], deadline=time.monotonic() - 1) is False
    assert saved                                                       # progress kept on the way out
    rest = FakeApi()
    assert iucn_api.harvest(rest, store, ["Aus bus", "Cus dus"]) is True


class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self.body, self.headers = status, body, headers or {}

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_the_client_waits_on_a_rate_limit_retries_a_server_error_and_returns_none_for_not_found(monkeypatch):
    monkeypatch.setattr(iucn_api, "PAUSE", 0)
    waits = []
    monkeypatch.setattr(iucn_api.time, "sleep", waits.append)
    answers = [Resp(429, headers={"Retry-After": "3"}), Resp(502), Resp(200, {"ok": 1}, {"total-pages": "4"}), Resp(404)]

    class Session:
        def __init__(self):
            self.headers = {}

        def get(self, url, params=None, timeout=None):
            return answers.pop(0)

    api = iucn_api.Api("tok", session=Session())
    assert api.get("countries/IN", {"page": 1}) == ({"ok": 1}, 4)
    assert waits[0] == 3                                                # Retry-After respected
    assert api.get("taxa/scientific_name", {}) is None
    with pytest.raises(iucn_api.ApiDown):
        iucn_api.Api("tok", session=type("S", (), {"headers": {}, "get": lambda *a, **k: Resp(503)})(), tries=2).get("x")


def test_only_the_population_trend_reaches_the_public_files():
    """The extractor writes only to cache/, locally and in R2, and the site never serves cache/. The master list takes
    the population trend alone (published with the owner's go-ahead, 31 October 2026); threats, habitats and the rest
    stay internal."""
    assert iucn_api.CACHE.relative_to(iucn_api.ROOT).parts[:2] == ("data", "cache")
    assert iucn_api.R2_PREFIX.startswith("cache/")
    data_function = (iucn_api.ROOT / "functions" / "data" / "[[path]].js").read_text()
    assert "key.startsWith('cache/')" in data_function
    master = (iucn_api.ROOT / "pipeline" / "master.py").read_text()
    assert "SELECT name, trend FROM '{inputs['iucn_detail']}'" in master
    assert not any(f in master for f in ("threats", "habitats", "possibly_extinct", "criteria", "assessors"))


def test_the_list_is_the_newest_local_build_else_the_published_one_in_r2(tmp_path, monkeypatch):
    """On Actions there is no local build: the names come from the master.parquet that R2's latest.json names."""
    from tests.r2_fake import FakeS3
    monkeypatch.setenv("R2_BUCKET", "b")
    s3 = FakeS3()
    s3.store["layers/master/latest.json"] = json.dumps({"base": "layers/master/2026-10-26/B2/"}).encode()
    s3.store["layers/master/2026-10-26/B2/master.parquet"] = b"published"
    got = iucn_api.master_path(s3, tmp_path / "layers", tmp_path / "cache")
    assert got.read_bytes() == b"published"
    local = tmp_path / "layers" / "2026-10-26" / "master.parquet"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"local")
    assert iucn_api.master_path(s3, tmp_path / "layers", tmp_path / "cache") == local
    assert iucn_api.master_path(None, tmp_path / "none", tmp_path / "cache") is None
