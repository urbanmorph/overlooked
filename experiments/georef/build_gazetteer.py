"""Gazetteer for the place-name matcher, from bharatlas layers (LGD admin units; GatiShakti protected areas).

Layer files are downloaded once to data/georef/layers/ (a .part file is renamed only when complete, so a cut
download is fetched again). Villages: only the name, code and bounding-box columns are read from the remote
Parquet file (HTTP range requests), and kept as data/georef/layers/villages.parquet. A second run with the
files present downloads nothing; the gazetteer is rebuilt only when it is missing.

Output: data/georef/gazetteer.parquet with kind, name, state_lgd, dist_lgd, lat, lon, radius_km;
data/georef/layers/manifest.json with each file's URL, size and SHA-256.

Usage: .venv/bin/python experiments/georef/build_gazetteer.py [--force]
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pipeline import districts, r2, util

BASE = "https://pub-0429b8e3b5a946e69ea007df844a6f1c.r2.dev"
LAYERS = {
    "states": f"{BASE}/admin/states/LGD_States.parquet",
    "subdistricts": f"{BASE}/admin/subdistricts/LGD_Subdistricts.parquet",
    "blocks": f"{BASE}/admin/blocks/LGD_Blocks.parquet",
    "wildlife": f"{BASE}/environment/forests/GatiShakti_Wildlife_Sanctuaries_and_National_Parks.parquet",
}
VILLAGES_URL = f"{BASE}/admin/villages/LGD_Villages.parquet"
DIR = ROOT / "data" / "georef" / "layers"
OUT = ROOT / "data" / "georef" / "gazetteer.parquet"
ALIASES = Path(__file__).resolve().parent / "ref" / "district_aliases.csv"
# A protected area counts in a district when at least this share of its area is there.
PA_SHARE = 0.15
# Delhi's districts are called North, East, South West...: give them "Delhi" so they do not match directions.
DELHI = 7


def fetch_layers(user_agent):
    http = requests.Session()
    http.headers["User-Agent"] = user_agent
    for name, url in LAYERS.items():
        dest = DIR / Path(url).name
        if not dest.exists():
            util.log(f"downloading {name}")
            util.stream(http, url, dest, progress_mb=10)
    villages = DIR / "villages.parquet"
    if not villages.exists():
        util.log("reading village names and boxes from the remote file (column read)")
        con = duckdb.connect()
        con.sql("INSTALL httpfs; LOAD httpfs")
        part = villages.with_name("villages.parquet.part")
        con.sql(f"""COPY (SELECT vil_lgd, vilname11, vilnam_soi, state_lgd, dist_lgd, subdt_lgd,
                                  xmin, ymin, xmax, ymax FROM '{VILLAGES_URL}')
                    TO '{part}' (FORMAT parquet, COMPRESSION zstd)""")
        part.replace(villages)
    manifest = {}
    for f in sorted(DIR.glob("*.parquet")):
        manifest[f.name] = {"bytes": f.stat().st_size, "sha256": r2.sha256(f)}
    manifest["sources"] = {**LAYERS, "villages": VILLAGES_URL, "districts": districts.URL}
    (DIR / "manifest.json").write_text(json.dumps(manifest, indent=1))


# Name cleaning in SQL: drop bracketed notes ("(CT)", "(Part)") and numbers ("108 Kalthur").
CLEAN = "trim(regexp_replace(regexp_replace({c}, '\\(.*?\\)|\\[.*?\\]', ' ', 'g'), '\\b[0-9]+\\b', ' ', 'g'))"


def build(con):
    con.sql("LOAD spatial")
    d = districts.PATH
    con.sql(f"""CREATE TABLE dist AS SELECT dist_lgd, state_lgd,
                  CASE WHEN state_lgd = {DELHI} AND dtname <> 'New Delhi' THEN dtname || ' Delhi' ELSE dtname END AS name,
                  geometry FROM '{d}' WHERE dist_lgd > 0""")
    area = "ST_Area_Spheroid(ST_FlipCoordinates({g})) / 1e6"
    centre = "ST_PointOnSurface({g})"
    parts = [f"""SELECT 'district' AS kind, name, state_lgd, dist_lgd, ST_Y({centre.format(g='geometry')}) AS lat,
                        ST_X({centre.format(g='geometry')}) AS lon, sqrt({area.format(g='geometry')} / pi()) AS radius_km
                 FROM dist"""]
    for kind, f, col in (("subdistrict", "LGD_Subdistricts.parquet", "sdtname"),
                         ("block", "LGD_Blocks.parquet", "block_name")):
        parts.append(f"""SELECT '{kind}', {CLEAN.format(c=col)}, state_lgd, dist_lgd,
                                ST_Y({centre.format(g='geometry')}), ST_X({centre.format(g='geometry')}),
                                sqrt({area.format(g='geometry')} / pi())
                         FROM '{DIR / f}' WHERE dist_lgd > 0 AND {col} IS NOT NULL""")
    # Villages: centre and half diagonal of the bounding box.
    box = "(ymin + ymax) / 2, (xmin + xmax) / 2, 111.2 * sqrt(power(ymax - ymin, 2) + power((xmax - xmin) * cos(radians((ymin + ymax) / 2)), 2)) / 2"
    for col in ("vilname11", "vilnam_soi"):
        parts.append(f"""SELECT 'village', {CLEAN.format(c=col)}, state_lgd, dist_lgd, {box}
                         FROM '{DIR / 'villages.parquet'}' WHERE dist_lgd > 0 AND length(trim({col})) > 1""")
    # Protected areas: one row per district holding at least PA_SHARE of the area, at the centre of that part.
    con.sql(f"""CREATE TABLE pa AS SELECT gid, name, pa_name, ST_MakeValid(geometry) AS g
                FROM '{DIR / LAYERS['wildlife'].rsplit('/', 1)[1]}' WHERE geometry IS NOT NULL""")
    con.sql("""CREATE TABLE pa_part AS
                SELECT p.gid, p.name, p.pa_name, d.state_lgd, d.dist_lgd, ST_Intersection(p.g, d.geometry) AS g,
                       ST_Area(ST_Intersection(p.g, d.geometry)) / nullif(ST_Area(p.g), 0) AS share
                FROM pa p JOIN dist d ON ST_Intersects(p.g, d.geometry)""")
    for col in ("name", "pa_name"):
        parts.append(f"""SELECT 'pa', {col}, state_lgd, dist_lgd, ST_Y({centre.format(g='g')}), ST_X({centre.format(g='g')}),
                                sqrt({area.format(g='g')} / pi())
                         FROM pa_part WHERE share >= {PA_SHARE} AND {col} IS NOT NULL""")
    parts.append(f"""SELECT 'alias', a.alias, d.state_lgd, d.dist_lgd, g.lat, g.lon, g.radius_km
                     FROM read_csv('{ALIASES}', header=true) a
                     JOIN dist d ON d.state_lgd = a.state_lgd AND d.name = a.district
                     JOIN (SELECT dist_lgd, ST_Y({centre.format(g='geometry')}) AS lat, ST_X({centre.format(g='geometry')}) AS lon,
                                  sqrt({area.format(g='geometry')} / pi()) AS radius_km FROM dist) g USING (dist_lgd)""")
    con.sql("CREATE TABLE gaz AS " + " UNION ALL ".join(parts))
    missing = con.sql(f"""SELECT a.alias, a.district FROM read_csv('{ALIASES}', header=true) a
                          ANTI JOIN dist d ON d.state_lgd = a.state_lgd AND d.name = a.district""").fetchall()
    if missing:
        sys.exit(f"aliases name districts that LGD does not have: {missing}")
    con.sql("DELETE FROM gaz WHERE name IS NULL OR length(name) < 2")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="rebuild the gazetteer from the cached layers")
    a = p.parse_args()
    ua = "overlooked-india georef test (+https://github.com/urbanmorph/overlooked)"
    districts.ensure(ua)
    fetch_layers(ua)
    if OUT.exists() and not a.force:
        util.log(f"{OUT} exists; nothing to do (--force to rebuild)")
        return
    con = duckdb.connect()
    build(con)
    part = OUT.with_name(OUT.name + ".part")
    con.sql(f"COPY (SELECT * FROM gaz ORDER BY kind, state_lgd, dist_lgd, name) TO '{part}' (FORMAT parquet)")
    part.replace(OUT)
    for row in con.sql("SELECT kind, count(*) FROM gaz GROUP BY 1 ORDER BY 2 DESC").fetchall():
        util.log(*row)


if __name__ == "__main__":
    main()
