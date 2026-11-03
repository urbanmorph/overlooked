"""R2 uploads: sync_files sends many files at once, skips what R2 holds, retries, and reports what failed."""

import pytest

from pipeline import r2
from tests.r2_fake import FakeS3


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "b")
    monkeypatch.setattr(r2, "RETRY_PAUSE", 0)
    out = []
    for i in range(40):
        p = tmp_path / f"f{i}.json"
        p.write_text(f'{{"i": {i}}}')
        out.append((p, f"k/f{i}.json"))
    return out


def test_uploads_several_at_once_and_a_second_run_sends_nothing(files):
    s3 = FakeS3(pause=0.02)
    assert r2.sync_files(s3, files, workers=8) == 40
    assert 1 < s3.most <= 8 and sorted(s3.store) == sorted(k for _, k in files)
    assert r2.sync_files(s3, files, workers=8) == 0          # idempotent: R2 holds the same content
    files[3][0].write_text('{"i": "changed"}')
    assert r2.sync_files(s3, files, workers=8) == 1          # only the changed file goes again


def test_a_failed_upload_is_tried_again(files):
    s3 = FakeS3(fail={"k/f5.json": 2})
    assert r2.sync_files(s3, files, workers=4) == 40
    assert "k/f5.json" in s3.store


def test_a_file_that_keeps_failing_stops_nothing_else_and_is_named(files):
    s3 = FakeS3(fail={"k/f7.json": -1})
    with pytest.raises(r2.UploadFailed) as e:
        r2.sync_files(s3, files, workers=4)
    assert e.value.keys == ["k/f7.json"] and "k/f7.json" in str(e.value)
    assert len(s3.store) == 39                               # the rest are in R2
    s3.fail = {}
    assert r2.sync_files(s3, files, workers=4) == 1          # a rerun sends only what is still to send


def test_list_and_delete_keys_under_a_prefix(files):
    s3 = FakeS3()
    r2.sync_files(s3, files[:5])
    s3.put_object(Bucket="b", Key="other/x.json", Body=b"{}")
    keys = r2.list_keys(s3, "k/")
    assert keys == sorted(k for _, k in files[:5])                 # every page, only the prefix
    assert r2.delete_keys(s3, keys[:3]) == 3
    assert r2.list_keys(s3, "k/") == keys[3:] and "other/x.json" in s3.store
    assert r2.delete_keys(s3, []) == 0


def test_fetch_keeps_a_copy_in_step_with_r2_through_a_part_file(tmp_path, monkeypatch):
    """r2.fetch (an input file R2 holds): downloaded when absent or when R2's sha256 differs, never left half
    written (a .part file, renamed when complete); the local copy when R2 has none; None when neither has it."""
    monkeypatch.setenv("R2_BUCKET", "b")
    s3, dest = FakeS3(), tmp_path / "in" / "x.json"
    assert r2.fetch(s3, "cache/x.json", dest) is None and r2.fetch(None, "cache/x.json", dest) is None
    import hashlib
    sha = lambda b: {"sha256": hashlib.sha256(b).hexdigest()}
    s3.store["cache/x.json"], s3.meta["cache/x.json"] = b"v1", sha(b"v1")
    assert r2.fetch(s3, "cache/x.json", dest) == dest and dest.read_bytes() == b"v1"
    downloads = []
    s3.download_file = lambda b, k, p, f=s3.download_file: (downloads.append(k), f(b, k, p))
    assert r2.fetch(s3, "cache/x.json", dest) == dest and not downloads    # the same content: not downloaded
    s3.store["cache/x.json"], s3.meta["cache/x.json"] = b"v2", sha(b"v2")  # R2 changed: downloaded again
    assert r2.fetch(s3, "cache/x.json", dest).read_bytes() == b"v2"
    assert not list(dest.parent.glob("*.part"))
    del s3.store["cache/x.json"]
    assert r2.fetch(s3, "cache/x.json", dest) == dest                  # R2 has none: the local copy
