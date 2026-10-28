"""Upload snapshots to R2 (S3 API). Keys come from R2_* environment variables, scoped to one bucket."""

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# Snapshot files never change once written; only latest.json moves.
IMMUTABLE = "public, max-age=31536000, immutable"
SHORT = "public, max-age=300"
TYPES = {".json": "application/json", ".parquet": "application/vnd.apache.parquet"}
# sync_files: uploads at once (the client keeps as many connections), tries per file, pause before a retry (doubles).
WORKERS = 16
TRIES = 4
RETRY_PAUSE = 2.0


def client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(max_pool_connections=WORKERS * 2, retries={"max_attempts": 5, "mode": "standard"}),
    )


def bucket():
    return os.environ["R2_BUCKET"]


def exists(s3, key):
    try:
        s3.head_object(Bucket=bucket(), Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def get_json(s3, key):
    try:
        return json.loads(s3.get_object(Bucket=bucket(), Key=key)["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return None
        raise


def restore(s3, key, dest: Path):
    """Download key to dest when dest is absent and R2 holds it. True when it downloaded."""
    if dest.exists() or s3 is None or not exists(s3, key):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(bucket(), key, str(dest))
    return True


def put_json(s3, obj, key):
    s3.put_object(Bucket=bucket(), Key=key, Body=json.dumps(obj, indent=1).encode(),
                  ContentType="application/json", CacheControl=SHORT)


def sha256(path: Path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def remote_sha256(s3, key):
    try:
        return s3.head_object(Bucket=bucket(), Key=key).get("Metadata", {}).get("sha256")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def sync_file(s3, path: Path, key, immutable=True):
    """Upload only if R2 does not already hold the same content. Returns True if it uploaded.
    Safe to repeat: an interrupted upload simply continues on the next run."""
    digest = sha256(path)
    if remote_sha256(s3, key) == digest:
        return False
    s3.upload_file(str(path), bucket(), key, ExtraArgs={
        "ContentType": TYPES.get(path.suffix, "application/octet-stream"),
        "CacheControl": IMMUTABLE if immutable else SHORT,
        "Metadata": {"sha256": digest},
    })
    return True


class UploadFailed(RuntimeError):
    """Some files did not reach R2 after every try. keys: their keys. The others are uploaded; a rerun sends the rest."""

    def __init__(self, keys):
        self.keys = sorted(keys)
        super().__init__(f"{len(self.keys)} files did not upload: {', '.join(self.keys[:10])}")


def sync_files(s3, pairs, immutable=True, workers=WORKERS):
    """sync_file for many (path, key) pairs at once. Each file is tried up to TRIES times; a file that still fails
    does not stop the others, and UploadFailed names it at the end, so the caller writes no pointer to an incomplete
    set. Idempotent: a rerun uploads only what R2 does not hold yet. Returns the number of files uploaded."""
    pairs = list(pairs)

    def one(path, key):
        """True when uploaded, False when R2 held it already, None when every try failed."""
        for attempt in range(TRIES):
            try:
                return sync_file(s3, path, key, immutable)
            except Exception as e:  # noqa: BLE001 - any error: try again, then report the key, not stop the others
                if attempt == TRIES - 1:
                    print(f"{key}: upload failed after {TRIES} tries: {type(e).__name__}", flush=True)
                    return None
                time.sleep(RETRY_PAUSE * 2 ** attempt)

    sent, done, failed = 0, 0, []
    with ThreadPoolExecutor(workers) as pool:
        jobs = {pool.submit(one, p, k): k for p, k in pairs}
        for job in as_completed(jobs):
            done += 1
            uploaded = job.result()
            if uploaded is None:
                failed.append(jobs[job])
            sent += bool(uploaded)
            if done % 100 == 0:
                print(f"R2: {done} of {len(pairs)} files checked, {sent} uploaded", flush=True)
    if failed:
        raise UploadFailed(failed)
    return sent
