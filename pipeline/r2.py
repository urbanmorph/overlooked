"""Upload snapshots to R2 (S3 API). Keys come from R2_* environment variables, scoped to one bucket."""

import json
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

CACHE = {
    ".json": "public, max-age=300",
    ".parquet": "public, max-age=31536000, immutable",
}
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


def put_file(s3, path: Path, key):
    s3.upload_file(str(path), bucket(), key, ExtraArgs={
        "ContentType": TYPES.get(path.suffix, "application/octet-stream"),
        "CacheControl": CACHE.get(path.suffix, "public, max-age=300"),
    })


def put_json(s3, obj, key):
    s3.put_object(Bucket=bucket(), Key=key, Body=json.dumps(obj, indent=1).encode(),
                  ContentType="application/json", CacheControl=CACHE[".json"])
