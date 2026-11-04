"""LGD district boundaries from bharatlas (CC0-1.0 / CC-BY-4.0, Local Government Directory)."""

from pathlib import Path

from pipeline import r2, util

ROOT = Path(__file__).resolve().parent.parent
URL = "https://pub-0429b8e3b5a946e69ea007df844a6f1c.r2.dev/admin/districts/LGD_Districts.parquet"
PATH = ROOT / "data" / "ref" / "LGD_Districts.parquet"


def ref_file(url, path: Path, user_agent, **about):
    """Download a reference file if it is not on disk. Return its provenance for the manifest."""
    if not path.exists():
        from pipeline import health  # health imports this module
        util.stream(health.session(user_agent), url, path)
    return {**about, "url": url, "bytes": path.stat().st_size, "sha256": r2.sha256(path)}


def ensure(user_agent):
    """Download the district file if it is not on disk. Return its provenance for the manifest."""
    return ref_file(URL, PATH, user_agent, layer="lgd_districts", source="Local Government Directory, via bharatlas",
                    licence="CC0-1.0 / CC-BY-4.0")
