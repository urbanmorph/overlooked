"""An extractor's state as one JSON object, kept locally and in R2 (cache/..., never served): loaded from R2's copy
(an old local copy never hides newer progress made on Actions), saved through a .part file and uploaded when it
changed, every SAVE_EVERY seconds (maybe_save) and on exit, also when the run fails (with Store(...) as st).

merge=True is for answers that only grow (OCR pages, Wikidata answers): the local and R2 copies are merged a section
deep, R2's answer winning a conflict. Without it, a snapshot (a week's counts, a sync cursor) is R2's copy whole."""

import json
import time
from pathlib import Path

from pipeline import r2
from pipeline.util import dump

SAVE_EVERY = 600   # seconds between saves of a run's progress


def merged(local, remote):
    """local's entries with remote's over them, a section deep."""
    out = dict(local)
    for k, v in remote.items():
        out[k] = {**out[k], **v} if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Store:
    def __init__(self, path: Path, s3=None, key=None, merge=False):
        self.path, self.s3, self.key = path, s3 if key else None, key
        remote = r2.get_json(self.s3, key) if self.s3 is not None else None
        local = json.loads(path.read_text()) if path.exists() else None
        if merge and remote is not None and local is not None:
            self.data = merged(local, remote)
        else:
            self.data = remote if remote is not None else local if local is not None else {}
        # Written once now when a copy lacks what the other has; else only when the run changes something.
        self.dirty = (self.s3 is not None and remote != self.data) or local != self.data
        self.saved = json.dumps(self.data, sort_keys=True) if not self.dirty else None
        self.saved_at = time.monotonic()

    def changed(self):
        return self.dirty or json.dumps(self.data, sort_keys=True) != self.saved

    def save(self):
        if self.changed():
            dump(self.data, self.path)
            if self.s3 is not None:
                r2.sync_file(self.s3, self.path, self.key, immutable=False)
            self.saved, self.dirty = json.dumps(self.data, sort_keys=True), False
        self.saved_at = time.monotonic()

    def maybe_save(self):
        """Save when SAVE_EVERY seconds have passed since the last save."""
        if time.monotonic() - self.saved_at >= SAVE_EVERY:
            self.save()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.save()
        return False
