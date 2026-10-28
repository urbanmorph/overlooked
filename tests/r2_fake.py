"""An in-memory R2 (the S3 calls pipeline.r2 makes), for tests. Records the order of writes."""

import threading

from botocore.exceptions import ClientError


def missing(op):
    return ClientError({"Error": {"Code": "404"}}, op)


class FakeS3:
    """fail: {key: times an upload of it fails before it works (-1: always)}. pause: seconds each upload takes."""

    def __init__(self, fail=None, pause=0.0):
        self.store, self.meta, self.writes, self.fail = {}, {}, [], dict(fail or {})
        self.uploads = []
        self.lock, self.now, self.most, self.pause = threading.Lock(), 0, 0, pause

    def head_object(self, Bucket, Key):
        if Key not in self.store:
            raise missing("HeadObject")
        return {"Metadata": self.meta.get(Key, {})}

    def get_object(self, Bucket, Key):
        if Key not in self.store:
            raise missing("GetObject")
        body = self.store[Key]
        return {"Body": type("B", (), {"read": lambda self: body})()}

    def put_object(self, Bucket, Key, Body, **kw):
        with self.lock:
            self.store[Key], self.meta[Key] = Body, {}
            self.writes.append(Key)

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
            with open(path, "rb") as f:
                body = f.read()
            with self.lock:
                self.store[key], self.meta[key] = body, dict(ExtraArgs.get("Metadata", {}))
                self.uploads.append(key)
                self.writes.append(key)
        finally:
            with self.lock:
                self.now -= 1

    def download_file(self, bucket, key, path):
        if key not in self.store:
            raise missing("GetObject")
        with open(path, "wb") as f:
            f.write(self.store[key])

    def get_paginator(self, name):
        store = self.store

        class P:
            def paginate(self, Bucket, Prefix):
                keys = sorted(k for k in store if k.startswith(Prefix))
                for i in range(0, max(len(keys), 1), 2):            # small pages, so paging is tested
                    yield {"Contents": [{"Key": k} for k in keys[i:i + 2]]} if keys else {}
        return P()

    def delete_objects(self, Bucket, Delete):
        with self.lock:
            for o in Delete["Objects"]:
                self.store.pop(o["Key"], None)
        return {}
