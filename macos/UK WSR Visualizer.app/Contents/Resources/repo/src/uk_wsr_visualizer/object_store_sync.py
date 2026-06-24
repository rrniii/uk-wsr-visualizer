"""Dry-run-first object-store sync, verify, and publish operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from .object_store import latest_manifest_object_key, manifest_object_key, public_status_object_key
from .object_store_config import ObjectStoreConfig
from .object_store_manifest import PublicationPlan, load_plan, utc_now, write_plan


class S3LikeClient(Protocol):
    def upload_file(
        self,
        Filename: str,
        Bucket: str,
        Key: str,
        ExtraArgs: dict[str, Any] | None = None,
        Config: Any | None = None,
    ) -> None: ...

    def put_object(
        self,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str | None = None,
        ACL: str | None = None,
    ) -> None: ...

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]: ...


def create_s3_client(config: ObjectStoreConfig, internal: bool = True) -> Any:
    try:
        import boto3
        from botocore.config import Config
        from boto3.s3.transfer import TransferConfig
    except ImportError as exc:
        raise RuntimeError("boto3 is required for live object-store operations. Install with: pip install -e '.[object-store]'") from exc

    session_kwargs: dict[str, str] = {}
    if config.aws_profile:
        session_kwargs["profile_name"] = config.aws_profile
    session = boto3.Session(**session_kwargs)
    endpoint_url = config.internal_endpoint if internal else config.external_endpoint
    client = session.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=config.region_name,
        config=Config(
            connect_timeout=10,
            read_timeout=60,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )
    client._visualizer_transfer_config = TransferConfig(multipart_chunksize=config.multipart_chunk_mb * 1024 * 1024)
    return client


def sync_plan(
    plan: PublicationPlan,
    execute: bool = False,
    client: S3LikeClient | None = None,
    skip_existing: bool = False,
) -> PublicationPlan:
    if execute and client is None:
        raise ValueError("live sync requires an S3 client")

    for obj in plan.objects:
        if obj.status == "missing_source":
            continue
        source = Path(obj.source_path)
        if not source.exists():
            obj.status = "missing_source"
            obj.message = "source file does not exist"
            continue
        if not execute:
            obj.status = "planned"
            obj.message = "dry run; no upload attempted"
            continue
        if skip_existing:
            assert client is not None
            try:
                head = client.head_object(Bucket=obj.bucket, Key=obj.key)
            except Exception:
                head = None
            if head is not None:
                remote_size = int(head.get("ContentLength", -1))
                remote_sha = str(head.get("Metadata", {}).get("sha256", ""))
                if remote_size == obj.size and remote_sha == obj.sha256:
                    obj.status = "skipped_existing"
                    obj.verified_at = utc_now()
                    obj.message = "remote object already matches size and sha256 metadata"
                    continue
        extra_args = {
            "ACL": "public-read",
            "ContentType": obj.content_type,
            "Metadata": {
                "sha256": obj.sha256,
                "uk-wsr-kind": obj.kind,
                "uk-wsr-run-id": plan.run_id,
            },
        }
        assert client is not None
        transfer_config = getattr(client, "_visualizer_transfer_config", None)
        client.upload_file(str(source), obj.bucket, obj.key, ExtraArgs=extra_args, Config=transfer_config)
        obj.status = "uploaded"
        obj.uploaded_at = utc_now()
        obj.message = ""
    return plan


def verify_plan(
    plan: PublicationPlan,
    execute: bool = False,
    client: S3LikeClient | None = None,
) -> PublicationPlan:
    if execute and client is None:
        raise ValueError("live verify requires an S3 client")

    for obj in plan.objects:
        if obj.status == "missing_source":
            continue
        if not execute:
            obj.status = "verified" if Path(obj.source_path).exists() and obj.sha256 else "missing_source"
            obj.verified_at = utc_now() if obj.status == "verified" else ""
            obj.message = "local dry-run verification only"
            continue

        assert client is not None
        try:
            head = client.head_object(Bucket=obj.bucket, Key=obj.key)
        except Exception as exc:  # pragma: no cover - concrete client errors vary by S3 library.
            obj.status = "missing_remote"
            obj.message = str(exc)
            continue

        remote_size = int(head.get("ContentLength", -1))
        remote_sha = str(head.get("Metadata", {}).get("sha256", ""))
        if remote_size != obj.size:
            obj.status = "remote_mismatch"
            obj.message = f"size mismatch: expected {obj.size}, got {remote_size}"
            continue
        if remote_sha and remote_sha != obj.sha256:
            obj.status = "remote_mismatch"
            obj.message = "sha256 metadata mismatch"
            continue
        obj.status = "verified"
        obj.verified_at = utc_now()
        obj.message = ""
    return plan


def publish_manifest(
    plan: PublicationPlan,
    config: ObjectStoreConfig,
    execute: bool = False,
    client: S3LikeClient | None = None,
) -> dict[str, Any]:
    manifest_payload = json.dumps(plan.to_dict(), indent=2, sort_keys=True).encode("utf-8")
    status_payload = json.dumps(
        {
            "ok": all(obj.status == "verified" for obj in plan.objects),
            "run_id": plan.run_id,
            "published_at": utc_now() if execute else "",
            "object_count": len(plan.objects),
            "byte_count": sum(obj.size for obj in plan.objects),
            "manifest_key": manifest_object_key(plan.run_id, config.object_prefix),
            "latest_manifest_key": latest_manifest_object_key(config.object_prefix),
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")

    result = {
        "execute": execute,
        "run_id": plan.run_id,
        "manifest_key": manifest_object_key(plan.run_id, config.object_prefix),
        "latest_manifest_key": latest_manifest_object_key(config.object_prefix),
        "status_key": public_status_object_key(config.object_prefix),
    }
    if not execute:
        result["message"] = "dry run; no manifest objects uploaded"
        return result
    if client is None:
        raise ValueError("live publish requires an S3 client")

    client.put_object(
        Bucket=config.public_bucket,
        Key=manifest_object_key(plan.run_id, config.object_prefix),
        Body=manifest_payload,
        ContentType="application/json",
        ACL="public-read",
    )
    client.put_object(
        Bucket=config.public_bucket,
        Key=latest_manifest_object_key(config.object_prefix),
        Body=manifest_payload,
        ContentType="application/json",
        ACL="public-read",
    )
    client.put_object(
        Bucket=config.public_bucket,
        Key=public_status_object_key(config.object_prefix),
        Body=status_payload,
        ContentType="application/json",
        ACL="public-read",
    )
    result["message"] = "published manifest and public status objects"
    return result


def sync_plan_file(plan_path: Path, manifest_path: Path, execute: bool, client: S3LikeClient | None = None) -> PublicationPlan:
    plan = sync_plan(load_plan(plan_path), execute=execute, client=client)
    write_plan(manifest_path, plan)
    return plan


def verify_manifest_file(
    manifest_path: Path,
    output_path: Path,
    execute: bool,
    client: S3LikeClient | None = None,
) -> PublicationPlan:
    plan = verify_plan(load_plan(manifest_path), execute=execute, client=client)
    write_plan(output_path, plan)
    return plan
