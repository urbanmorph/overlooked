"""The iNaturalist layer run writes every file, with the iNaturalist calls stubbed."""

import json
from types import SimpleNamespace

from pipeline import inat, layer_inat


def test_run_writes_species_genus_and_coarse_files(tmp_path, monkeypatch):
    monkeypatch.setattr(inat, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(inat, "LAYERS", tmp_path / "layers")
    month = "2026-10"
    places = {"32": {"place_id": "9627"}}
    inat.store("places.json", places)
    monkeypatch.setattr(inat, "places", lambda client: places)
    inat.store(f"species_counts_{month}.json", {
        f"{c}|{q}": {"place_id": p, "page": 1, "total": 1, "rows": [[1, "Aus bus", "Aves", 2]]}
        for c, p in (("32", "9627"), ("india", "6681")) for q in inat.QUALITIES})
    monkeypatch.setattr(inat, "genus_counts", lambda client, areas, m: inat.store(f"genus_counts_{m}.json", {
        c: {"place_id": p, "page": 1, "total": 1, "rows": [[9, "Aus", "Aves", 3]]} for c, p in areas}))
    monkeypatch.setattr(inat, "coarse_counts", lambda client, areas, m: inat.store(f"coarse_counts_{m}.json", {
        f"{c}|{g}": 1 for c, _ in areas for g in inat.GROUPS}))
    client = SimpleNamespace(used=0)  # any request would fail: everything comes from the cache or the stubs
    layer_inat.run(SimpleNamespace(), month, client, None)
    out = tmp_path / "layers" / month
    assert json.loads((out / "species_counts.json").read_text())["lists"]["32"]["research"] == [[1, "Aus bus", "Aves", 2]]
    assert json.loads((out / "genus_counts.json").read_text())["lists"]["india"] == [[9, "Aus", "Aves", 3]]
    coarse = json.loads((out / "coarse_counts.json").read_text())
    assert coarse["complete"] and coarse["counts"]["32"]["Aves"] == 1
    assert sorted(p.name for p in out.iterdir()) == ["coarse_counts.json", "genus_counts.json", "species_counts.json"]
