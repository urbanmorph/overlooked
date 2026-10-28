"""R2 uploads: sync_files sends many files at once, skips what R2 holds, retries, and reports what failed."""

import threading

import pytest
from botocore.exceptions import ClientError

from pipeline import r2


class FakeS3:
    """head_object and upload_file over a dict; fail: {key: times to fail before it works (-1: always)}."""

    def __init__(self, fail=None, pause=0.0):
        self.store, self.uploads, self.fail = {}, [], dict(fail or {})
        self.lock, self.now, self.most, self.pause = threading.Lock(), 0, 0, pause

    def head_object(self, Bucket, Key):
        if Key not in self.store:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"Metadata": {"sha256": self.store[Key]}}

    def upload_file(self, path, bucket, key, ExtraArgs):
        with self.lock:
            self.now += 1
            self.most = max(self.most, self.now)
            left = self.fail.get(key, 0)
            if left:
                self.fail[key] = left - 1 if left > 0 else -1
        try:
            threading.Event().wait(self.pause)
            if left:
                raise ClientError({"Error": {"Code": "500"}}, "PutObject")
            with self.lock:
                self.store[key] = ExtraArgs["Metadata"]["sha256"]
                self.uploads.append(key)
        finally:
            with self.lock:
                self.now -= 1


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
