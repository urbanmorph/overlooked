"""District map for the site: simplified LGD outlines as compact SVG paths.

Coordinates are rounded to 0.01 degree (about 1 km) and written as integer steps from the previous
point, which keeps the file small (about 100 KB compressed for all districts). Longitude is scaled by
cos(23 degrees) so India keeps its familiar shape.

Usage: python -m pipeline.boundaries <out.json>
"""

import json
import math
import sys
from pathlib import Path

import duckdb

from pipeline import districts as source
from pipeline.places import load_districts

TOLERANCE = 0.02          # degrees, simplification
SCALE = 100               # units per degree
X_FACTOR = math.cos(math.radians(23))
LAT_TOP = 38.0

SMALL_WORDS = {"and", "of", "&"}


def title(name):
    words = name.replace(",", ", ").split()
    return " ".join(w.lower() if w.lower() in SMALL_WORDS and i else w.capitalize() for i, w in enumerate(words))


def ring_path(ring):
    pts = []
    for lon, lat in ring:
        p = (round(lon * SCALE * X_FACTOR), round((LAT_TOP - lat) * SCALE))
        if not pts or p != pts[-1]:
            pts.append(p)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        return None, pts
    out = [f"M{pts[0][0]} {pts[0][1]}"]
    steps = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        steps.append(f"{x1 - x0} {y1 - y0}")
    out.append("l" + " ".join(steps) + "z")
    return "".join(out).replace(" -", "-"), pts


def build(path=source.PATH):
    con = duckdb.connect()
    load_districts(con, str(path))
    rows = con.sql(f"""
        SELECT dist_lgd, dtname, stname, state_lgd,
               ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_Force2D(geometry), {TOLERANCE})) AS g
        FROM districts ORDER BY state_lgd, dtname
    """).fetchall()
    out, xs, ys = [], [], []
    for dist, name, state, state_lgd, g in rows:
        geom = json.loads(g)
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        parts = []
        for poly in polys:
            for ring in poly:
                d, pts = ring_path(ring)
                if d:
                    parts.append(d)
                    xs += [p[0] for p in pts]
                    ys += [p[1] for p in pts]
                elif pts:
                    # A tiny island: draw a 1-unit square so the district stays visible.
                    x, y = pts[0]
                    parts.append(f"M{x} {y}h1v1h-1z")
                    xs.append(x); ys.append(y)
        out.append({"id": dist, "name": name, "state": title(state), "state_lgd": state_lgd, "d": "".join(parts)})
    pad = 10
    view = [min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad]
    return {"viewBox": view, "tolerance_deg": TOLERANCE, "source": "Local Government Directory, via bharatlas",
            "districts": out}


if __name__ == "__main__":
    data = build()
    Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
    Path(sys.argv[1]).write_text(json.dumps(data, separators=(",", ":")))
