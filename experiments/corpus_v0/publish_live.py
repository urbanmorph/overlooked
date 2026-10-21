"""Copy one live shortlist run to R2 (docs/shortlist_data.md). Run only when the owner has agreed.

Uploads the JSON files of data/shortlist/<run>/ only: g/*.json to layers/shortlist/<run>/g/ (immutable: a run never
changes), then latest.json to layers/shortlist/latest.json (short cache) last, so the page never points at a run
whose group files are not all there. Never shown.parquet or shown.sha256 (they stay on this machine).
pipeline.r2.sync_file skips a file R2 already holds with the same SHA-256, so a rerun uploads nothing and a stopped
upload continues. R2 credentials come from .env through pipeline.r2.client() and are never printed.

Run: data/model_check/.venv/bin/python -u experiments/corpus_v0/publish_live.py <run>
"""

import json
import sys

from lib import ROOT, log

PREFIX = "layers/shortlist"


def files(run):
    """(local path, R2 key) in upload order: every group file the run's latest.json lists, then latest.json."""
    d = ROOT / "data" / "shortlist" / run
    latest = json.loads((d / "latest.json").read_text())
    if latest["run"] != run:
        raise SystemExit(f"{d}/latest.json is for run {latest['run']}, not {run}")
    out = []
    for g in latest["groups"]:
        for n in range(1, g.get("pages", 1) + 1):
            name = f"{g['key']}.json" if n == 1 else f"{g['key']}.{n}.json"
            p = d / "g" / name
            if not p.exists():
                raise SystemExit(f"missing {p}")
            out.append((p, f"{PREFIX}/{run}/g/{name}"))
    out.append((d / "latest.json", f"{PREFIX}/latest.json"))
    return out


def main():
    from dotenv import load_dotenv

    from pipeline import r2

    load_dotenv(ROOT / ".env", override=True)
    run = sys.argv[1]
    plan = files(run)
    s3 = r2.client()
    sent = 0
    for path, key in plan:
        latest = key.endswith("/latest.json")
        if r2.sync_file(s3, path, key, immutable=not latest):
            sent += 1
            log(f"  uploaded {key} ({path.stat().st_size / 1000:.1f} KB)")
    log(f"run {run}: {sent} of {len(plan)} files uploaded (the rest were already there)")


if __name__ == "__main__":
    main()
