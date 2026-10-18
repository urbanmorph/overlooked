"""Upload snapshots to R2 (S3 API). Keys come from R2_* environment variables, scoped to one bucket."""

import hashlib
import json
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# Snapshot files never change once written; only latest.json moves.
IMMUTABLE = "public, max-age=31536000, immutable"
SHORT = "public, max-age=300"
TYPES = {".json": "application/json", ".parquet": "application/vnd.apache.parquet"}


def client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
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
