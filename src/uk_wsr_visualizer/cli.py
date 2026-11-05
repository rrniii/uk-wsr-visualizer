"""Command-line interface for UK WSR Visualizer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .catalog import load_catalog
from .freshness import build_freshness_report
from .object_store_config import cors_xml, load_object_store_config
from .object_store_manifest import (
    build_publication_plan,
    load_plan,
    reconcile_plan_with_manifest,
    write_plan,
)
from .object_store_sync import (
    create_s3_client,
    publish_manifest,
    sync_plan,
    verify_plan,
)


from .cli_commands.common import (
    _settings as _settings,
    _filter_args as _filter_args,
    _split_csv as _split_csv,
    _add_filter_arguments as _add_filter_arguments,
)
from .cli_commands.data import (
    cmd_citation as cmd_citation,
    cmd_catalog_build as cmd_catalog_build,
    cmd_catalog_build_raw_volume as cmd_catalog_build_raw_volume,
    cmd_catalog_stac as cmd_catalog_stac,
    cmd_preview_build as cmd_preview_build,
    cmd_preview_batch as cmd_preview_batch,
    cmd_animation_build as cmd_animation_build,
    cmd_tile_build as cmd_tile_build,
    cmd_tile_batch as cmd_tile_batch,
    cmd_export as cmd_export,
    cmd_math as cmd_math,
)
from .cli_commands.maintenance import (
    cmd_api as cmd_api,
    cmd_freshness_check as cmd_freshness_check,
    cmd_deployment_preflight as cmd_deployment_preflight,
    cmd_validate_qc as cmd_validate_qc,
    cmd_validate_wct as cmd_validate_wct,
    _dataset_name as _dataset_name,
    _formats_from_spec as _formats_from_spec,
    _wct_suite_cases_from_payload as _wct_suite_cases_from_payload,
    cmd_validate_wct_suite as cmd_validate_wct_suite,
)
from .cli_commands.session import (
    cmd_session_list as cmd_session_list,
    cmd_session_get as cmd_session_get,
    cmd_session_save as cmd_session_save,
    cmd_session_export as cmd_session_export,
    cmd_session_import as cmd_session_import,
)
from .cli_commands.data import (
    register_catalog_commands,
    register_visualization_commands,
)
from .cli_commands.maintenance import (
    WCT_SUITE_FORMATS as WCT_SUITE_FORMATS,
    register_maintenance_commands,
)
from .cli_commands.object_store import register_object_store_commands
from .cli_commands.session import register_session_commands


def cmd_vpts_summarize(args: argparse.Namespace) -> int:
    # VPTS analysis tooling is optional. Import it only when requested so the
    # desktop server can start without analysis-only dependencies.
    from .vpts import summarize_vpts_csv, write_vpts_summary

    report = summarize_vpts_csv(
        Path(args.input),
        metric=args.metric,
        day_threshold_deg=args.day_threshold_deg,
        night_threshold_deg=args.night_threshold_deg,
    )
    if args.output:
        write_vpts_summary(Path(args.output), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def cmd_object_store_plan(args: argparse.Namespace) -> int:
    settings = _settings(args)
    config = load_object_store_config(Path(args.config) if args.config else None)
    items = load_catalog(settings.catalog_path)
    plan = build_publication_plan(
        items=items,
        catalog_path=settings.catalog_path,
        config=config,
        staging_dir=Path(args.staging_dir),
        preview_dir=Path(args.preview_dir)
        if args.preview_dir
        else settings.preview_dir,
        tile_dir=Path(args.tile_dir) if args.tile_dir else settings.tile_dir,
        export_dir=Path(args.export_dir) if args.export_dir else settings.export_dir,
        validation_dir=Path(args.validation_dir) if args.validation_dir else None,
        run_id=args.run_id,
        sha256_cache_path=Path(args.sha256_cache) if args.sha256_cache else None,
    )
    write_plan(Path(args.output), plan)
    print(
        json.dumps(
            {"wrote": str(args.output), **plan.summary()}, indent=2, sort_keys=True
        )
    )
    return 0


def cmd_object_store_sync(args: argparse.Namespace) -> int:
    config = load_object_store_config(Path(args.config) if args.config else None)
    plan = load_plan(Path(args.plan))
    client = create_s3_client(config, internal=True) if args.execute else None
    manifest = sync_plan(
        plan, execute=args.execute, client=client, skip_existing=args.skip_existing
    )
    write_plan(Path(args.manifest), manifest)
    print(
        json.dumps(
            {
                "wrote": str(args.manifest),
                "execute": args.execute,
                **manifest.summary(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_object_store_verify(args: argparse.Namespace) -> int:
    config = load_object_store_config(Path(args.config) if args.config else None)
    manifest = load_plan(Path(args.manifest))
    client = create_s3_client(config, internal=True) if args.execute else None
    verified = verify_plan(manifest, execute=args.execute, client=client)
    write_plan(Path(args.output), verified)
    print(
        json.dumps(
            {"wrote": str(args.output), "execute": args.execute, **verified.summary()},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_object_store_publish(args: argparse.Namespace) -> int:
    config = load_object_store_config(Path(args.config) if args.config else None)
    manifest = load_plan(Path(args.manifest))
    client = create_s3_client(config, internal=True) if args.execute else None
    result = publish_manifest(manifest, config, execute=args.execute, client=client)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _manifest_byte_count(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return sum(
        int(obj.get("size", 0))
        for obj in payload.get("objects", [])
        if obj.get("status") == "verified"
    )


def _catalog_batch_summary(path: Path) -> tuple[int, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, 0
    items = payload.get("items", [])
    if not isinstance(items, list):
        return 0, 0
    return len(items), sum(
        int(item.get("file_size", 0)) for item in items if isinstance(item, dict)
    )


def cmd_object_store_backfill_status(args: argparse.Namespace) -> int:
    backfill_dir = Path(args.backfill_dir)
    catalogs = sorted(backfill_dir.glob("catalog-????????.json"))
    synced = sorted(backfill_dir.glob("synced-????????.json"))
    verified = sorted(backfill_dir.glob("verified-????????.json"))
    cache_path = (
        Path(args.sha256_cache)
        if args.sha256_cache
        else backfill_dir / "sha256-cache.json"
    )

    catalog_item_count = 0
    catalog_byte_count = 0
    for catalog in catalogs:
        item_count, byte_count = _catalog_batch_summary(catalog)
        catalog_item_count += item_count
        catalog_byte_count += byte_count

    cache_entries: dict[str, object] = {}
    if cache_path.exists():
        try:
            cache_entries = json.loads(cache_path.read_text(encoding="utf-8")).get(
                "entries", {}
            )
        except json.JSONDecodeError:
            cache_entries = {}
        if not isinstance(cache_entries, dict):
            cache_entries = {}

    verified_dates = [path.stem.removeprefix("verified-") for path in verified]
    synced_dates = [path.stem.removeprefix("synced-") for path in synced]
    summary = {
        "backfill_dir": str(backfill_dir),
        "catalog_batches": len(catalogs),
        "catalog_items": catalog_item_count,
        "catalog_byte_count": catalog_byte_count,
        "synced_batches": len(synced),
        "verified_batches": len(verified),
        "verified_byte_count": sum(_manifest_byte_count(path) for path in verified),
        "sha256_cache": str(cache_path),
        "sha256_cache_entries": len(cache_entries),
        "sha256_cache_byte_count": sum(
            int(value.get("size", 0))
            for value in cache_entries.values()
            if isinstance(value, dict)
        ),
        "first_verified": verified_dates[0] if verified_dates else None,
        "last_verified": verified_dates[-1] if verified_dates else None,
        "latest_synced": synced_dates[-1] if synced_dates else None,
        "remaining_batches": max(len(catalogs) - len(verified), 0),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def cmd_object_store_reconcile(args: argparse.Namespace) -> int:
    settings = _settings(args)
    config = load_object_store_config(Path(args.config) if args.config else None)
    expected = build_publication_plan(
        items=load_catalog(settings.catalog_path),
        catalog_path=settings.catalog_path,
        config=config,
        staging_dir=Path(args.staging_dir),
        preview_dir=Path(args.preview_dir)
        if args.preview_dir
        else settings.preview_dir,
        tile_dir=Path(args.tile_dir) if args.tile_dir else settings.tile_dir,
        export_dir=Path(args.export_dir) if args.export_dir else settings.export_dir,
        validation_dir=Path(args.validation_dir) if args.validation_dir else None,
        run_id=args.run_id,
    )
    actual = load_plan(Path(args.manifest))
    result = reconcile_plan_with_manifest(expected, actual)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"wrote": str(output), **result}, indent=2, sort_keys=True))
    return 0


def cmd_object_store_release_candidate(args: argparse.Namespace) -> int:
    settings = _settings(args)
    config = load_object_store_config(Path(args.config) if args.config else None)
    items = load_catalog(settings.catalog_path)
    plan = build_publication_plan(
        items=items,
        catalog_path=settings.catalog_path,
        config=config,
        staging_dir=Path(args.staging_dir),
        preview_dir=Path(args.preview_dir)
        if args.preview_dir
        else settings.preview_dir,
        tile_dir=Path(args.tile_dir) if args.tile_dir else settings.tile_dir,
        export_dir=Path(args.export_dir) if args.export_dir else settings.export_dir,
        validation_dir=Path(args.validation_dir) if args.validation_dir else None,
        run_id=args.run_id,
    )
    plan_output = Path(args.plan_output)
    write_plan(plan_output, plan)

    missing_sources = [
        obj.key for obj in plan.objects if obj.status == "missing_source"
    ]
    manifest_path = (
        Path(args.manifest) if args.manifest else settings.object_store_manifest_path
    )
    reconcile_result: dict[str, object] = {
        "ok": False,
        "skipped": True,
        "message": f"manifest not found at {manifest_path}",
    }
    if manifest_path.exists():
        reconcile_result = reconcile_plan_with_manifest(plan, load_plan(manifest_path))
        reconcile_result["skipped"] = False

    freshness = build_freshness_report(
        catalog_path=settings.catalog_path,
        object_store_manifest_path=manifest_path,
        max_catalog_age_hours=args.max_catalog_age_hours,
        max_data_latency_days=args.max_data_latency_days,
        max_manifest_age_hours=args.max_manifest_age_hours,
        require_object_store=True,
        require_wct_validation=not args.skip_wct_validation,
    )
    summary = {
        "ok": not missing_sources and bool(reconcile_result.get("ok")) and freshness.ok,
        "created_plan": str(plan_output),
        "manifest": str(manifest_path),
        "catalog": str(settings.catalog_path),
        "missing_source_count": len(missing_sources),
        "missing_source_examples": missing_sources[:10],
        "plan_summary": plan.summary(),
        "reconcile": reconcile_result,
        "freshness": freshness.to_dict(),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {"wrote": str(output), "ok": summary["ok"], **plan.summary()},
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if summary["ok"] else 1


def cmd_object_store_cors_template(args: argparse.Namespace) -> int:
    config = load_object_store_config(Path(args.config) if args.config else None)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(cors_xml(config), encoding="utf-8")
    print(f"wrote CORS template for {config.public_bucket} to {output}")
    return 0


def _client_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            return str(error.get("Code", ""))
    return ""


def _bucket_exists(client: object, bucket: str) -> bool:
    try:
        client.head_bucket(Bucket=bucket)
        return True
    except (
        Exception
    ) as exc:  # pragma: no cover - concrete client errors vary by S3 library.
        code = _client_error_code(exc)
        if code in {"404", "NoSuchBucket", "NotFound"}:
            return False
        raise


def _bucket_object_probe(client: object, bucket: str) -> dict[str, object]:
    try:
        response = client.list_objects_v2(Bucket=bucket, MaxKeys=1)
    except (
        Exception
    ) as exc:  # pragma: no cover - concrete client errors vary by S3 library.
        code = _client_error_code(exc)
        if code in {"404", "NoSuchBucket", "NotFound"}:
            return {"exists": False, "object_count_probe": 0, "empty": True}
        raise
    key_count = int(response.get("KeyCount", 0))
    contents = response.get("Contents") or []
    first_key = ""
    if contents and isinstance(contents, list) and isinstance(contents[0], dict):
        first_key = str(contents[0].get("Key", ""))
    return {
        "exists": True,
        "object_count_probe": key_count,
        "empty": key_count == 0,
        "first_key": first_key,
    }


def cmd_object_store_buckets(args: argparse.Namespace) -> int:
    config = load_object_store_config(Path(args.config) if args.config else None)
    delete_buckets = list(args.delete_empty_bucket or [])
    create_buckets = list(args.create_bucket or [])
    if not delete_buckets and not create_buckets:
        create_buckets = [config.staging_bucket, config.public_bucket]

    result: dict[str, object] = {
        "execute": args.execute,
        "endpoint": config.internal_endpoint,
        "delete_empty_bucket": delete_buckets,
        "create_bucket": create_buckets,
        "actions": [],
    }
    actions: list[dict[str, object]] = []
    result["actions"] = actions
    if not args.execute:
        for bucket in delete_buckets:
            actions.append(
                {
                    "bucket": bucket,
                    "action": "delete_bucket",
                    "status": "planned_empty_only",
                }
            )
        for bucket in create_buckets:
            actions.append(
                {"bucket": bucket, "action": "create_bucket", "status": "planned"}
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    client = create_s3_client(config, internal=True)
    ok = True
    for bucket in delete_buckets:
        try:
            probe = _bucket_object_probe(client, bucket)
            if not probe["exists"]:
                actions.append(
                    {
                        "bucket": bucket,
                        "action": "delete_bucket",
                        "status": "already_absent",
                        **probe,
                    }
                )
                continue
            if not probe["empty"]:
                ok = False
                actions.append(
                    {
                        "bucket": bucket,
                        "action": "delete_bucket",
                        "status": "not_empty",
                        **probe,
                    }
                )
                continue
            client.delete_bucket(Bucket=bucket)
            actions.append(
                {
                    "bucket": bucket,
                    "action": "delete_bucket",
                    "status": "deleted",
                    **probe,
                }
            )
        except (
            Exception
        ) as exc:  # pragma: no cover - concrete client errors vary by S3 library.
            ok = False
            actions.append(
                {
                    "bucket": bucket,
                    "action": "delete_bucket",
                    "status": "failed",
                    "message": str(exc),
                }
            )
    for bucket in create_buckets:
        try:
            if _bucket_exists(client, bucket):
                actions.append(
                    {
                        "bucket": bucket,
                        "action": "create_bucket",
                        "status": "already_exists",
                    }
                )
                continue
            client.create_bucket(Bucket=bucket)
            actions.append(
                {"bucket": bucket, "action": "create_bucket", "status": "created"}
            )
        except (
            Exception
        ) as exc:  # pragma: no cover - concrete client errors vary by S3 library.
            ok = False
            actions.append(
                {
                    "bucket": bucket,
                    "action": "create_bucket",
                    "status": "failed",
                    "message": str(exc),
                }
            )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uk-wsr-visualizer")
    parser.add_argument("--catalog", help="Catalog JSON path.")
    subparsers = parser.add_subparsers(required=True)

    register_catalog_commands(subparsers)
    register_visualization_commands(subparsers)

    vpts_parser = subparsers.add_parser("vpts")
    vpts_sub = vpts_parser.add_subparsers(required=True)
    vpts_summarize = vpts_sub.add_parser("summarize")
    vpts_summarize.add_argument(
        "--input", required=True, help="Aloft-style VPTS or integrated VPI CSV input."
    )
    vpts_summarize.add_argument("--output", help="Optional JSON report path.")
    vpts_summarize.add_argument(
        "--metric",
        help="Metric column to aggregate. Defaults to the first available of mtr, mt, vid, dens, eta.",
    )
    vpts_summarize.add_argument("--day-threshold-deg", type=float, default=0.0)
    vpts_summarize.add_argument("--night-threshold-deg", type=float, default=-6.0)
    vpts_summarize.set_defaults(func=cmd_vpts_summarize)

    register_object_store_commands(subparsers, handlers=globals())
    register_session_commands(subparsers)
    register_maintenance_commands(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if (
        hasattr(args, "output")
        and not getattr(args, "catalog", None)
        and args.__dict__.get("func") == cmd_catalog_build
    ):
        args.catalog = args.output
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
