"""Biogeographic zones and provinces of India (Rodgers, Panwar and Mathur, Wildlife Institute of India): 10 zones,
26 provinces. Boundaries from bharatlas (GODL-India, via CoRE Stack). A record takes the province its point is in; the
outlines are simplified to about 100 m (SIMPLIFY_DEG), no coarser than the 110 m points (3 decimals) and 6 times faster
to test; a point within places.NEAR_KM of a province takes the nearest one.

There is no Eastern Ghats unit in this classification: its nearest is 6C, Deccan Peninsula: Eastern Highlands."""

from pathlib import Path

import duckdb

from pipeline import districts
from pipeline.places import place_in

ROOT = Path(__file__).resolve().parent.parent
URL = "https://pub-0429b8e3b5a946e69ea007df844a6f1c.r2.dev/environment/biogeographic/Biogeographic_Zones.parquet"
PATH = ROOT / "data" / "ref" / "Biogeographic_Zones.parquet"
SIMPLIFY_DEG = 0.001
CREDIT = "Biogeographic zones of India: Wildlife Institute of India (Rodgers, Panwar and Mathur), GODL-India"

# (province code, province, zone), in the WII order. The bit of a province in a mask is its index here.
PROVINCES = [
    ("1A", "Trans-Himalaya: Ladakh Mountains", "Trans-Himalaya"),
    ("1B", "Trans-Himalaya: Tibetan Plateau", "Trans-Himalaya"),
    ("2A", "Himalaya: North West", "Himalaya"),
    ("2B", "Himalaya: West", "Himalaya"),
    ("2C", "Himalaya: Central", "Himalaya"),
    ("2D", "Himalaya: East", "Himalaya"),
    ("3A", "Desert: Thar", "Desert"),
    ("3B", "Desert: Kutchchh", "Desert"),
    ("4A", "Semi-Arid: Punjab Plains", "Semi-Arid"),
    ("4B", "Semi-Arid: Gujarat Rajputana", "Semi-Arid"),
    ("5A", "Western Ghats: Malabar Plains", "Western Ghats"),
    ("5B", "Western Ghats: Mountains", "Western Ghats"),
    ("6A", "Deccan Peninsula: Central Highlands", "Deccan Peninsula"),
    ("6B", "Deccan Peninsula: Chhota Nagpur", "Deccan Peninsula"),
    ("6C", "Deccan Peninsula: Eastern Highlands", "Deccan Peninsula"),
    ("6D", "Deccan Peninsula: Central Plateau", "Deccan Peninsula"),
    ("6E", "Deccan Peninsula: Deccan South", "Deccan Peninsula"),
    ("7A", "Gangetic Plain: Upper", "Gangetic Plain"),
    ("7B", "Gangetic Plain: Lower", "Gangetic Plain"),
    ("8A", "Coasts: West Coast", "Coasts"),
    ("8B", "Coasts: East Coast", "Coasts"),
    ("8C", "Coasts: Lakshadweep", "Coasts"),
    ("9A", "North-East: Bramhaputra Valley", "North-East"),
    ("9B", "North-East: North-East Hills", "North-East"),
    ("10A", "Islands: Andamans", "Islands"),
    ("10B", "Islands: Nicobars", "Islands"),
]


def ensure(user_agent):
    """Download the boundary file if it is not on disk. Return its provenance for the manifest."""
    return districts.ref_file(URL, PATH, user_agent, layer="biogeographic_zones",
                              source="Wildlife Institute of India, via bharatlas (CoRE Stack)", licence="GODL-India")


def place(con: duckdb.DuckDBPyConnection, points: str, path=PATH):
    """Create table point_province (lat, lon, prov, how) for the distinct points of table points (lat, lon)."""
    con.sql("INSTALL spatial; LOAD spatial")
    con.sql("SET geometry_always_xy = true")
    con.sql(f"""CREATE OR REPLACE TABLE provinces AS
                SELECT prov_code AS prov, ST_SimplifyPreserveTopology(geometry, {SIMPLIFY_DEG}) AS geometry
                FROM '{path}'""")
    con.sql(f"CREATE OR REPLACE TABLE _ppts AS SELECT DISTINCT lat, lon FROM {points} WHERE lat IS NOT NULL")
    place_in(con, "_ppts", "provinces", "prov", "point_province")
    con.sql("DROP TABLE _ppts")
