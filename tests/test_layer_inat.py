"""The iNaturalist layer run writes every file, with the iNaturalist calls stubbed."""

import json
from types import SimpleNamespace

from pipeline import inat, layer_inat


def test_run_writes_species_genus_and_coarse_files(tmp_path, monkeypatch):
    monkeypatch.setattr(inat, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(inat, "LAYERS", tmp_path / "layers")
    month = "2026-10"
    inat.store(f"backlog_{month}.json", {"as_of": "d", "places": {}, "backlog": [], "identifiers": []})
    inat.store("places.json", {"32": {"place_id": "9627"}})
    inat.store(f"species_counts_{month}.json", {
        f"{c}|{q}": {"place_id": p, "page": 1, "total": 1, "rows": [[1, "Aus bus", "Aves", 2]]}
        for c, p in (("32", "9627"), ("india", "6681")) for q in inat.QUALITIES})
    monkeypatch.setattr(inat, "genus_counts", lambda client, areas, m: inat.store(f"genus_counts_{m}.json", {
        c: {"place_id": p, "page": 1, "total": 1, "rows": [[9, "Aus", "Aves", 3]]} for c, p in areas}))
    monkeypatch.setattr(inat, "coarse_counts", lambda client, areas, m: inat.store(f"coarse_counts_{m}.json", {
        f"{c}|{g}": 1 for c, _ in areas for g in inat.COARSE_GROUPS}))
    monkeypatch.setattr(inat, "quiet_check", lambda client, species, m: {})
    quiet = tmp_path / "india.json"
    quiet.write_text(json.dumps({"rows": [["K1", "Cus dus", 0, 0, 0, 1990]]}))
    client = SimpleNamespace(used=0)
    layer_inat.run(SimpleNamespace(quiet_file=str(quiet)), month, client, None)
    out = tmp_path / "layers" / month
    assert json.loads((out / "species_counts.json").read_text())["lists"]["32"]["research"] == [[1, "Aus bus", "Aves", 2]]
    assert json.loads((out / "genus_counts.json").read_text())["lists"]["india"] == [[9, "Aus", "Aves", 3]]
    coarse = json.loads((out / "coarse_counts.json").read_text())
    assert coarse["complete"] and coarse["counts"]["32"]["Aves"] == 1
    assert json.loads((out / "quiet.json").read_text())["of"] == 1
