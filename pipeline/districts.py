"""LGD district boundaries from bharatlas (CC0-1.0 / CC-BY-4.0, Local Government Directory)."""

from pathlib import Path

import requests

from pipeline import r2, util

ROOT = Path(__file__).resolve().parent.parent
URL = "https://pub-0429b8e3b5a946e69ea007df844a6f1c.r2.dev/admin/districts/LGD_Districts.parquet"
PATH = ROOT / "data" / "ref" / "LGD_Districts.parquet"


def ensure(user_agent):
    """Download the district file if it is not on disk. Return its provenance for the manifest."""
    if not PATH.exists():
        http = requests.Session()
        http.headers["User-Agent"] = user_agent
        util.stream(http, URL, PATH)
    digest = r2.sha256(PATH)
    return {"layer": "lgd_districts", "url": URL, "bytes": PATH.stat().st_size, "sha256": digest,
            "source": "Local Government Directory, via bharatlas", "licence": "CC0-1.0 / CC-BY-4.0"}
