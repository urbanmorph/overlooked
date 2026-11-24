"""Kew WCVP native ranges (pipeline/wcvp_ranges.py): every species-rank name, its accepted species, whether Kew gives
the species a range, and the botanical regions of India (TDWG level 3) where it is native."""

import zipfile

import duckdb

from pipeline import wcvp_ranges

NAMES = """plant_name_id|taxon_rank|taxon_status|taxon_name|accepted_plant_name_id
1|Species|Accepted|Piper nigrum|
2|Species|Synonym|Piper velayudhanii|1
3|Species|Accepted|Coffea arabica|
4|Species|Accepted|Tectona grandis|
5|Species|Accepted|Nova nulla|
6|Variety|Accepted|Piper nigrum var. x|
7|Species|Accepted|Hima laya|
8|Species|Accepted|Border plant|
9|Species|Accepted|Far plant|
"""
DIST = """plant_locality_id|plant_name_id|area_code_l3|introduced|extinct|location_doubtful
a|1|IND|0|0|0
b|1|SRL|0|0|0
c|3|ETH|0|0|0
d|3|IND|1|0|0
e|4|IND|0|0|0
f|4|ASS|0|0|1
g|7|EHM|0|0|0
h|7|WHM|0|1|0
i|8|MYA|0|0|0
j|9|MDG|0|0|0
"""


def kew_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("wcvp_names.csv", NAMES)
        z.writestr("wcvp_distribution.csv", DIST)
    return path


def test_ranges_from_kew(tmp_path):
    out = wcvp_ranges.build(kew_zip(tmp_path / "wcvp.zip"), tmp_path / "ranges.parquet")
    rows = duckdb.sql(f"SELECT name, accepted, has_range, india_native, india_introduced, near_india FROM '{out}'").fetchall()
    r = {n: (a, k, sorted(nat), sorted(intro)) for n, a, k, nat, intro, _ in rows}
    near = {n: x for n, *_, x in rows}
    assert near["Border plant"] and not near["Far plant"]        # native in Myanmar: next to India; Madagascar: not
    assert near["Piper nigrum"] and not near["Coffea arabica"]  # native in India counts as near
    assert r["Piper nigrum"] == ("Piper nigrum", True, ["IND"], [])
    assert r["Piper velayudhanii"] == ("Piper nigrum", True, ["IND"], [])     # a synonym takes its species' range
    assert r["Coffea arabica"] == ("Coffea arabica", True, [], ["IND"])       # introduced in India
    assert r["Tectona grandis"] == ("Tectona grandis", True, ["ASS", "IND"], [])   # doubtful still counts as native
    assert r["Nova nulla"] == ("Nova nulla", False, [], [])                    # no range: unknown, not "not native"
    assert r["Hima laya"] == ("Hima laya", True, ["EHM", "WHM"], [])           # extinct there: still its native range
    assert "Piper nigrum var. x" not in r                                      # species rank only


def test_a_second_run_with_the_same_zip_writes_nothing(tmp_path):
    z = kew_zip(tmp_path / "wcvp.zip")
    out = wcvp_ranges.build(z, tmp_path / "ranges.parquet")
    before = out.stat().st_mtime_ns
    assert wcvp_ranges.build(z, tmp_path / "ranges.parquet") == out and out.stat().st_mtime_ns == before


def test_a_new_layout_rebuilds_from_the_same_zip(tmp_path, monkeypatch):
    z = kew_zip(tmp_path / "wcvp.zip")
    out = wcvp_ranges.build(z, tmp_path / "ranges.parquet")
    before = out.stat().st_mtime_ns
    monkeypatch.setattr(wcvp_ranges, "LAYOUT", wcvp_ranges.LAYOUT + 1)
    wcvp_ranges.build(z, out)
    assert out.stat().st_mtime_ns != before
