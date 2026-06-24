#!/usr/bin/env python3
"""Purge and optionally delete an S3-compatible bucket in bounded batches."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bucket")
    parser.add_argument("--profile", default="")
    parser.add_argument("--endpoint-url", default="")
    parser.add_argument("--region-name", default="us-east-1")
    parser.add_argument("--prefix", default="")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--log-every", type=int, default=10000)
    parser.add_argument("--delete-bucket", action="store_true")
    return parser.parse_args()


def client_from_args(args: argparse.Namespace) -> Any:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise SystemExit(f"boto3 is required: {exc}") from exc
    session_kwargs = {"profile_name": args.profile} if args.profile else {}
    session = boto3.Session(**session_kwargs)
    return session.client(
        "s3",
        endpoint_url=args.endpoint_url or None,
        region_name=args.region_name,
        config=Config(connect_timeout=10, read_timeout=60, retries={"max_attempts": 5, "mode": "standard"}),
    )


def log(payload: dict[str, Any]) -> None:
    print(json.dumps({"time": utc_now(), **payload}, sort_keys=True), flush=True)


def purge_bucket(client: Any, bucket: str, prefix: str, batch_size: int, log_every: int) -> int:
    deleted = 0
    while True:
        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=batch_size)
        contents = response.get("Contents", [])
        if not contents:
            return deleted
        objects = [{"Key": item["Key"]} for item in contents]
        result = client.delete_objects(Bucket=bucket, Delete={"Objects": objects, "Quiet": True})
        errors = result.get("Errors", [])
        deleted += len(objects) - len(errors)
        if errors:
            log({"bucket": bucket, "deleted": deleted, "errors": errors[:5], "prefix": prefix, "status": "delete_errors"})
            raise SystemExit(1)
        if deleted % log_every < len(objects):
            log({"bucket": bucket, "deleted": deleted, "prefix": prefix, "status": "purging"})


def main() -> int:
    args = parse_args()
    if args.batch_size < 1 or args.batch_size > 1000:
        raise SystemExit("--batch-size must be between 1 and 1000")
    client = client_from_args(args)
    log({"bucket": args.bucket, "prefix": args.prefix, "status": "started"})
    deleted = purge_bucket(client, args.bucket, args.prefix, args.batch_size, args.log_every)
    log({"bucket": args.bucket, "deleted": deleted, "prefix": args.prefix, "status": "empty"})
    if args.delete_bucket:
        if args.prefix:
            raise SystemExit("--delete-bucket cannot be used with --prefix")
        client.delete_bucket(Bucket=args.bucket)
        log({"bucket": args.bucket, "deleted": deleted, "prefix": args.prefix, "status": "bucket_deleted"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
