"""Small helpers that every extractor and builder shares: logs, timestamps, JSON output, streamed downloads."""

import json
from datetime import datetime, timezone
from pathlib import Path


def log(*a):
    print(*a, flush=True)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dump(obj, path: Path):
    """Compact JSON for the site (folders made as needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False))


def stream(http, url, dest: Path, kind=None, progress_mb=None):
    """Download url to dest through a .part file, renamed only when complete, so a cut download is never used.
    With kind, the answer must have that word in its Content-Type: False (and no file) when it has not, for
    example a site that answers a missing PDF with its home page and HTTP 200. Optional progress line every
    progress_mb MB."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    got, step = 0, (progress_mb or 0) << 20
    with http.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        if kind and kind not in r.headers.get("Content-Type", "").lower():
            return False
        with open(part, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if step and got // step > (got - len(chunk)) // step:
                    log(f"  {dest.name}: {got >> 20} MB")
    part.replace(dest)
    return True
