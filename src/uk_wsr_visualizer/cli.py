"""Command-line interface for UK WSR Visualizer."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .animation import AnimationRequest, run_animation
from .background_model import (
    BackgroundModelBuildConfig,
    BackgroundScan,
    background_key_from_metadata,
    build_background_model,
    save_background_model,
)
from .catalog import CatalogItem, build_catalog, build_raw_volume_catalog, filter_catalog, load_catalog
from .citations import citation_payload, format_citation_text
from .compat import UTC
from .config import Settings
from .export import ExportRequest, run_export
from .export_types import FieldSelection
from .freshness import build_freshness_report, write_freshness_report
from .geospatial import read_polar_field_with_companions
from .math_ops import MathOperand, MathRequest, run_math
from .object_store import DEFAULT_OBJECT_PREFIX
from .object_store_config import cors_xml, load_object_store_config
from .object_store_manifest import build_publication_plan, load_plan, reconcile_plan_with_manifest, write_plan
from .object_store_sync import create_s3_client, publish_manifest, sync_plan, verify_plan
from .preflight import build_preflight_report, write_preflight_report
from .preview import PreviewRequest, generate_preview
from .session import import_project, list_sessions, load_session, read_project_file, save_session, write_project_file
from .stac import AGGREGATE_COLLECTION_ID, collection_to_stac, item_to_stac, root_catalog_to_stac
from .tiles import TileRequest, generate_tile_pyramid, tile_manifest
from .wct_parity import WctParityCase, run_parity_report, shell_command, write_report

WCT_SUITE_FORMATS = {"geotiff", "kmz", "shapefile", "cf_netcdf"}


def _settings(args: argparse.Namespace) -> Settings:
    base = Settings.from_env()
    catalog_path = Path(args.catalog) if getattr(args, "catalog", None) else base.catalog_path
    data_dir = catalog_path.parent

    def arg_path(name: str, default: Path) -> Path:
        value = getattr(args, name, None)
        return Path(value) if value is not None else default

    def arg_value(name: str, default: str) -> str:
        value = getattr(args, name, None)
        return str(value) if value is not None else default

    return Settings(
        aggregate_base=arg_path("aggregate_base", base.aggregate_base),
        data_dir=data_dir,
        catalog_path=catalog_path,
        preview_dir=arg_path("preview_dir", base.preview_dir),
        tile_dir=arg_path("tile_dir", base.tile_dir),
        export_dir=arg_path("export_dir", base.export_dir),
        session_dir=arg_path("session_dir", base.session_dir),
        object_store_manifest_path=arg_path("object_store_manifest", base.object_store_manifest_path),
        object_store_external_base=arg_value("object_store_base", base.object_store_external_base),
        object_store_internal_base=base.object_store_internal_base,
    )


def _filter_args(args: argparse.Namespace) -> dict[str, object]:
    names = (
        "min_range_km",
        "max_range_km",
        "min_azimuth_deg",
        "max_azimuth_deg",
        "min_value",
        "max_value",
        "cappi_height_m",
        "qc_mode",
        "noise_floor_enabled",
        "noise_floor_method",
        "noise_floor_margin_db",
        "noise_floor_operation",
        "noise_floor_percentile",
        "noise_floor_window_bins",
        "noise_floor_texture_enabled",
        "noise_floor_texture_db",
        "noise_floor_texture_near_margin_db",
        "noise_floor_texture_support_db",
        "noise_floor_texture_max_db",
        "noise_floor_texture_min_similar_neighbors",
        "qc_companion_enabled",
        "qc_static_clutter_enabled",
        "qc_background_model_enabled",
        "qc_background_model_path",
        "qc_background_persistent_frequency_min",
        "qc_background_min_samples",
        "qc_background_static_vrad_frequency_min",
        "qc_background_low_sqi_frequency_min",
        "qc_background_dbzh_excess_max_db",
        "qc_background_evidence_score_threshold",
    )
    filters = {name: getattr(args, name) for name in names if getattr(args, name, None) is not None}
    if getattr(args, "palette_stops", None):
        filters["palette_stops"] = args.palette_stops
    return filters


def cmd_citation(args: argparse.Namespace) -> int:
    """Print citation guidance for research users."""

    payload = citation_payload()
    print(json.dumps(payload, indent=2, sort_keys=True) if args.json else format_citation_text())
    return 0


def cmd_catalog_build(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = build_catalog(
        aggregate_base=settings.aggregate_base,
        output=settings.catalog_path,
        radar=args.radar,
        year=args.year,
        date=args.date,
        max_files=args.max_files,
        object_store_base=settings.object_store_external_base,
        metadata_mode=args.metadata_mode,
    )
    print(f"wrote {len(items)} catalog items to {settings.catalog_path}")
    return 0


def cmd_catalog_build_raw_volume(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = build_raw_volume_catalog(
        raw_volume_base=Path(args.raw_volume_base),
        output=settings.catalog_path,
        radar=args.radar,
        year=args.year,
        date=args.date,
        max_files=args.max_files,
        object_store_base=settings.object_store_external_base,
        metadata_mode=args.metadata_mode,
    )
    volume_count = sum(len(item.raw_volumes) for item in items)
    print(f"wrote {len(items)} raw-volume catalog item(s), {volume_count} volume file(s), to {settings.catalog_path}")
    return 0


def cmd_catalog_stac(args: argparse.Namespace) -> int:
    settings = _settings(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    items = load_catalog(settings.catalog_path)
    (output_dir / "catalog.json").write_text(
        json.dumps(
            root_catalog_to_stac(items, public_base_url=settings.object_store_external_base, object_prefix=args.object_prefix),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    collection_dir = output_dir / AGGREGATE_COLLECTION_ID
    collection_dir.mkdir(parents=True, exist_ok=True)
    (collection_dir / "collection.json").write_text(
        json.dumps(
            collection_to_stac(items, public_base_url=settings.object_store_external_base, object_prefix=args.object_prefix),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    count = 0
    for item in items:
        path = collection_dir / f"{item.item_id}.json"
        path.write_text(
            json.dumps(
                item_to_stac(item, public_base_url=settings.object_store_external_base, object_prefix=args.object_prefix),
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        count += 1
    print(f"wrote STAC catalog, collection, and {count} item files to {output_dir}")
    return 0


def cmd_preview_build(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(load_catalog(settings.catalog_path), radar=args.radar, start=args.date, end=args.date)
    if not items:
        raise SystemExit("no matching catalog item")
    item = items[0]
    request = PreviewRequest(
        aggregate_path=Path(item.path),
        radar=item.radar,
        date=item.date,
        pulse=args.pulse,
        time=args.time,
        quantity=args.quantity,
        dataset=args.dataset,
        palette=args.palette,
        filters=_filter_args(args),
        output_dir=settings.preview_dir / item.radar / item.date,
    )
    output = generate_preview(request)
    print(output)
    return 0


def cmd_preview_batch(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(
        load_catalog(settings.catalog_path),
        radar=args.radar,
        start=args.start,
        end=args.end,
        pulse=args.pulse,
        quantity=args.quantity,
    )
    if args.max_items is not None:
        items = items[: args.max_items]

    built: list[str] = []
    errors: list[dict[str, str]] = []
    for item in items:
        combinations = [
            (record.pulse, record.time, record.quantity, f"dataset{record.dataset}")
            for record in item.quantity_records
            if (args.pulse is None or record.pulse == args.pulse)
            and (args.quantity is None or record.quantity == args.quantity)
        ]
        seen: set[tuple[str, str, str, str]] = set()
        unique = [combo for combo in combinations if not (combo in seen or seen.add(combo))]
        if args.max_frames_per_item is not None:
            unique = unique[: args.max_frames_per_item]
        for pulse, time, quantity, dataset in unique:
            try:
                output = generate_preview(
                    PreviewRequest(
                        aggregate_path=Path(item.path),
                        radar=item.radar,
                        date=item.date,
                        pulse=pulse,
                        time=time,
                        quantity=quantity,
                        dataset=dataset,
                        palette=args.palette,
                        filters=_filter_args(args),
                        output_dir=settings.preview_dir / item.radar / item.date,
                    )
                )
                built.append(str(output))
            except Exception as exc:
                errors.append(
                    {
                        "radar": item.radar,
                        "date": item.date,
                        "pulse": pulse,
                        "time": time,
                        "quantity": quantity,
                        "dataset": dataset,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    print(json.dumps({"built": built, "built_count": len(built), "errors": errors}, indent=2, sort_keys=True))
    return 1 if errors and not args.keep_going else 0


def cmd_animation_build(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(load_catalog(settings.catalog_path), radar=args.radar, start=args.date, end=args.date)
    if not items:
        raise SystemExit("no matching catalog item")
    times = [value.strip() for value in (args.times or "").split(",") if value.strip()]
    product = run_animation(
        AnimationRequest(
            radar=args.radar,
            date=args.date,
            pulse=args.pulse,
            quantity=args.quantity,
            times=times,
            dataset=args.dataset,
            palette=args.palette,
            filters=_filter_args(args),
            frame_delay_ms=args.frame_delay_ms,
        ),
        items[0],
        Path(args.output_dir),
        settings.preview_dir,
    )
    print(json.dumps(product, default=lambda value: value.__dict__, indent=2, sort_keys=True))
    return 0


def cmd_tile_build(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(load_catalog(settings.catalog_path), radar=args.radar, start=args.date, end=args.date)
    if not items:
        raise SystemExit("no matching catalog item")
    product = generate_tile_pyramid(
        TileRequest(
            aggregate_path=Path(items[0].path),
            radar=args.radar,
            date=args.date,
            pulse=args.pulse,
            time=args.time,
            quantity=args.quantity,
            dataset=args.dataset,
            palette=args.palette,
            filters=_filter_args(args),
            tile_size=args.tile_size,
            min_zoom=args.min_zoom,
            max_zoom=args.max_zoom,
            output_dir=settings.tile_dir,
        )
    )
    print(json.dumps(tile_manifest(product), indent=2, sort_keys=True))
    return 0


def cmd_tile_batch(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(
        load_catalog(settings.catalog_path),
        radar=args.radar,
        start=args.start,
        end=args.end,
        pulse=args.pulse,
        quantity=args.quantity,
    )
    if args.max_items is not None:
        items = items[: args.max_items]
    built: list[str] = []
    errors: list[dict[str, str]] = []
    for item in items:
        combinations = [
            (record.pulse, record.time, record.quantity, f"dataset{record.dataset}")
            for record in item.quantity_records
            if (args.pulse is None or record.pulse == args.pulse)
            and (args.quantity is None or record.quantity == args.quantity)
        ]
        seen: set[tuple[str, str, str, str]] = set()
        unique = [combo for combo in combinations if not (combo in seen or seen.add(combo))]
        if args.max_fields_per_item is not None:
            unique = unique[: args.max_fields_per_item]
        for pulse, time, quantity, dataset in unique:
            try:
                product = generate_tile_pyramid(
                    TileRequest(
                        aggregate_path=Path(item.path),
                        radar=item.radar,
                        date=item.date,
                        pulse=pulse,
                        time=time,
                        quantity=quantity,
                        dataset=dataset,
                        palette=args.palette,
                        filters=_filter_args(args),
                        tile_size=args.tile_size,
                        min_zoom=args.min_zoom,
                        max_zoom=args.max_zoom,
                        output_dir=settings.tile_dir,
                    )
                )
                built.append(product.manifest_path)
            except Exception as exc:
                errors.append(
                    {
                        "radar": item.radar,
                        "date": item.date,
                        "pulse": pulse,
                        "time": time,
                        "quantity": quantity,
                        "dataset": dataset,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    print(json.dumps({"built": built, "built_count": len(built), "errors": errors}, indent=2, sort_keys=True))
    return 1 if errors and not args.keep_going else 0


def cmd_build_background_model(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(
        load_catalog(settings.catalog_path),
        radar=args.radar,
        start=args.start,
        end=args.end,
        pulse=args.pulse,
        quantity=args.quantity,
    )
    scans: list[BackgroundScan] = []
    errors: list[dict[str, str]] = []
    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    requested_dataset = _dataset_name(args.dataset) if args.dataset else None

    for item in items:
        records = [
            record
            for record in item.quantity_records
            if record.pulse == args.pulse
            and record.quantity == args.quantity
            and (args.time is None or record.time == args.time)
            and (requested_dataset is None or f"dataset{record.dataset}" == requested_dataset)
        ]
        for record in records:
            dataset = f"dataset{record.dataset}"
            combo = (item.path, record.pulse, record.time, record.quantity, dataset)
            if combo in seen:
                continue
            seen.add(combo)
            try:
                data, metadata, companion_fields = read_polar_field_with_companions(
                    Path(item.path),
                    item.radar,
                    item.date,
                    FieldSelection(pulse=record.pulse, time=record.time, quantity=record.quantity, dataset=dataset),
                )
                scans.append(BackgroundScan(values=data, metadata=metadata, companion_fields=companion_fields))
                sources.append(
                    {
                        "radar": item.radar,
                        "date": item.date,
                        "pulse": record.pulse,
                        "time": record.time,
                        "quantity": record.quantity,
                        "dataset": dataset,
                    }
                )
            except Exception as exc:
                if not args.keep_going:
                    raise
                errors.append(
                    {
                        "path": item.path,
                        "date": item.date,
                        "time": record.time,
                        "quantity": record.quantity,
                        "dataset": dataset,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            if args.max_scans is not None and len(scans) >= args.max_scans:
                break
        if args.max_scans is not None and len(scans) >= args.max_scans:
            break

    if not scans:
        raise SystemExit("no matching scans were readable for background model building")

    key = background_key_from_metadata(scans[0].metadata, quantity=args.quantity)
    key["season_bucket"] = args.season_bucket
    key["time_of_day_bucket"] = args.time_of_day_bucket
    model = build_background_model(
        scans,
        key=key,
        config=BackgroundModelBuildConfig(
            echo_threshold_dbz=args.echo_threshold_dbz,
            vrad_abs_max_ms=args.vrad_abs_max_ms,
            sqi_low=args.sqi_low,
            rhohv_low=args.rhohv_low,
            rhohv_texture_threshold=args.rhohv_texture_threshold,
            zdr_min_db=args.zdr_min_db,
            zdr_max_db=args.zdr_max_db,
            zdr_texture_threshold_db=args.zdr_texture_threshold_db,
        ),
    )
    npz_path, json_path = save_background_model(model, args.output)
    print(
        json.dumps(
            model.summary()
            | {
                "npz_path": str(npz_path),
                "json_path": str(json_path),
                "source_count": len(scans),
                "sources": sources[: args.source_preview_count],
                "errors": errors,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if errors and not args.keep_going else 0


def cmd_export(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(load_catalog(settings.catalog_path), radar=args.radar, start=args.date, end=args.date)
    if not items:
        raise SystemExit("no matching catalog item")
    job = run_export(
        ExportRequest(
            radar=args.radar,
            date=args.date,
            format=args.format,
            pulse=args.pulse,
            time=args.time,
            quantity=args.quantity,
            dataset=args.dataset,
            times=_split_csv(args.times, []),
            frame_delay_ms=args.frame_delay_ms,
            palette=args.palette,
            filters=_filter_args(args),
        ),
        items[0],
        settings.export_dir,
    )
    print(json.dumps(job.__dict__, default=lambda value: value.__dict__, indent=2, sort_keys=True))
    return 0


def cmd_math(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(load_catalog(settings.catalog_path), radar=args.radar, start=args.date, end=args.date)
    if not items:
        raise SystemExit("no matching catalog item")
    product = run_math(
        MathRequest(
            radar=args.radar,
            date=args.date,
            operation=args.operation,
            left=MathOperand(
                pulse=args.left_pulse,
                time=args.left_time,
                quantity=args.left_quantity,
                dataset=args.left_dataset,
            ),
            right=MathOperand(
                pulse=args.right_pulse,
                time=args.right_time,
                quantity=args.right_quantity,
                dataset=args.right_dataset,
            ),
            format=args.format,
            filters=_filter_args(args),
            palette=args.palette,
        ),
        items[0],
        Path(args.output_dir),
    )
    print(json.dumps(product, default=lambda value: value.__dict__, indent=2, sort_keys=True))
    return 0


def cmd_api(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("uvicorn is required to run the API. Install with: pip install -e .") from exc

    settings = _settings(args)
    from .api.app import create_app

    uvicorn.run(create_app(settings), host=args.host, port=args.port)
    return 0


def cmd_freshness_check(args: argparse.Namespace) -> int:
    settings = _settings(args)
    report = build_freshness_report(
        catalog_path=settings.catalog_path,
        object_store_manifest_path=settings.object_store_manifest_path,
        max_catalog_age_hours=args.max_catalog_age_hours,
        max_data_latency_days=args.max_data_latency_days,
        max_manifest_age_hours=args.max_manifest_age_hours,
        require_object_store=args.require_object_store,
        require_wct_validation=args.require_wct_validation,
    )
    if args.output:
        write_freshness_report(Path(args.output), report)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.ok else 1


def cmd_deployment_preflight(args: argparse.Namespace) -> int:
    settings = _settings(args)
    report = build_preflight_report(
        settings=settings,
        object_store_config_path=Path(args.object_store_config) if args.object_store_config else None,
        validation_dir=Path(args.validation_dir) if args.validation_dir else None,
        wct_app=Path(args.wct_app) if args.wct_app else None,
        base_url=args.base_url,
        require_object_store=args.require_object_store,
        require_wct_validation=args.require_wct_validation,
        require_wct_app=args.require_wct_app,
        http_timeout_s=args.http_timeout,
    )
    if args.output:
        write_preflight_report(Path(args.output), report)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.ok else 1


def cmd_validate_qc(args: argparse.Namespace) -> int:
    settings = _settings(args)
    matches = filter_catalog(load_catalog(settings.catalog_path), radar=args.radar, start=args.date, end=args.date)
    if not matches:
        raise SystemExit("no matching catalog item")
    item = matches[0]
    request = ExportRequest(
        radar=item.radar,
        date=item.date,
        format="qc_mask",
        pulse=args.pulse,
        time=args.time,
        quantity=args.quantity,
        dataset=args.dataset,
        filters=_filter_args(args),
    )
    output_dir = Path(args.output_dir)
    job = run_export(request, item, output_dir)
    output_path = Path(job.output_path) if job.output_path else None
    sidecar_path = output_path.with_suffix(output_path.suffix + ".json") if output_path else None
    sidecar = {}
    if sidecar_path is not None and sidecar_path.exists():
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    source_path = Path(item.path)
    real_hdf5 = source_path.exists() and source_path.suffix.lower() in {".h5", ".hdf5"}
    ok = job.status == "complete" and (real_hdf5 or not args.require_real_hdf5)
    report = {
        "version": 1,
        "validation_type": "qc_mask",
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "ok": ok,
        "real_hdf5": real_hdf5,
        "require_real_hdf5": bool(args.require_real_hdf5),
        "source": {
            "radar": item.radar,
            "date": item.date,
            "path": item.path,
            "object_key": item.object_key,
            "object_url": item.object_url,
            "source_type": item.source_type,
        },
        "selection": {
            "pulse": args.pulse,
            "time": args.time,
            "quantity": args.quantity,
            "dataset": args.dataset,
            "filters": _filter_args(args),
        },
        "job": {
            "job_id": job.job_id,
            "status": job.status,
            "output_path": job.output_path,
            "artifact_manifest_path": job.artifact_manifest_path,
            "error": job.error,
        },
        "mask_path": str(output_path) if output_path else None,
        "sidecar_path": str(sidecar_path) if sidecar_path else None,
        "qc": sidecar.get("qc", {}),
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ok else 1


def cmd_validate_wct(args: argparse.Namespace) -> int:
    settings = _settings(args)
    matches = filter_catalog(load_catalog(settings.catalog_path), radar=args.radar, start=args.date, end=args.date)
    if not matches:
        raise SystemExit("no matching catalog item")
    item = matches[0]
    request = ExportRequest(
        radar=item.radar,
        date=item.date,
        format=args.format,
        pulse=args.pulse,
        time=args.time,
        quantity=args.quantity,
        dataset=args.dataset,
        filters=_filter_args(args),
    )
    case = WctParityCase(
        case_id=args.case_id or f"{item.radar}-{item.date}-{args.format}",
        item=item,
        request=request,
        wct_input_path=args.wct_input_path,
    )
    report = run_parity_report(
        [case],
        Path(args.output_dir),
        wct_app=Path(args.wct_app),
        execute_wct=args.execute_wct,
        timeout_s=args.timeout,
        require_comparison=args.require_comparison,
        max_mean_abs_error=args.max_mean_abs_error,
        max_rmse=args.max_rmse,
    )
    write_report(Path(args.report), report)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    for result in report.results:
        print(f"WCT command: {shell_command(result.wct_command)}")
    return 0 if report.ok else 1


def _split_csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return list(default)
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return parts or list(default)


def _dataset_name(value: str) -> str:
    return value if value.startswith("dataset") else f"dataset{value}"


def _formats_from_spec(spec: dict[str, object], default: list[str]) -> list[str]:
    raw_formats = spec.get("formats")
    if isinstance(raw_formats, list):
        formats = _split_csv(",".join(str(value) for value in raw_formats), default)
    elif raw_formats is None:
        formats = list(default)
    else:
        formats = _split_csv(str(raw_formats), default)
    unknown = sorted(set(formats) - WCT_SUITE_FORMATS)
    if unknown:
        raise SystemExit(f"unsupported WCT suite format(s): {', '.join(unknown)}")
    return formats


def _wct_suite_cases_from_payload(args: argparse.Namespace, items: list[CatalogItem]) -> list[WctParityCase]:
    cases: list[WctParityCase] = []
    formats_default = _split_csv(args.formats, ["geotiff", "kmz", "shapefile", "cf_netcdf"])
    unknown_defaults = sorted(set(formats_default) - WCT_SUITE_FORMATS)
    if unknown_defaults:
        raise SystemExit(f"unsupported WCT suite format(s): {', '.join(unknown_defaults)}")
    if args.cases_json:
        payload = json.loads(Path(args.cases_json).read_text(encoding="utf-8"))
        raw_cases = payload.get("cases", payload) if isinstance(payload, dict) else payload
        if not isinstance(raw_cases, list):
            raise SystemExit("cases JSON must be a list or an object with a cases list")
        case_specs = raw_cases
    else:
        required = ("radar", "date", "pulse", "time", "quantity")
        missing = [name for name in required if not getattr(args, name)]
        if missing:
            raise SystemExit(f"missing required suite selector(s): {', '.join(missing)}")
        case_specs = [
            {
                "case_id": args.case_id,
                "radar": args.radar,
                "date": args.date,
                "pulse": args.pulse,
                "time": args.time,
                "quantity": args.quantity,
                "dataset": args.dataset,
                "formats": formats_default,
                "wct_input_path": args.wct_input_path,
                "filters": _filter_args(args),
            }
        ]

    catalog_items = list(items)
    for index, spec in enumerate(case_specs):
        if not isinstance(spec, dict):
            raise SystemExit(f"case {index} is not an object")
        radar = str(spec.get("radar", "") or "")
        date = str(spec.get("date", "") or "")
        required_selectors = {
            "radar": radar,
            "date": date,
            "pulse": str(spec.get("pulse", "") or args.pulse or ""),
            "time": str(spec.get("time", "") or args.time or ""),
            "quantity": str(spec.get("quantity", "") or args.quantity or ""),
        }
        missing_selectors = [name for name, value in required_selectors.items() if not value]
        if missing_selectors:
            label = spec.get("case_id") or index
            raise SystemExit(f"case {label} missing required selector(s): {', '.join(missing_selectors)}")
        matches = [item for item in catalog_items if item.radar == radar and item.date == date]
        if not matches:
            raise SystemExit(f"no matching catalog item for case {index}: radar={radar}, date={date}")
        item = matches[0]
        formats = _formats_from_spec(spec, formats_default)
        filters = dict(spec.get("filters") or {})
        if not filters and not args.cases_json:
            filters = _filter_args(args)
        for export_format in formats:
            request = ExportRequest(
                radar=item.radar,
                date=item.date,
                format=export_format,
                pulse=required_selectors["pulse"],
                time=required_selectors["time"],
                quantity=required_selectors["quantity"],
                dataset=str(spec["dataset"]) if spec.get("dataset") else args.dataset,
                filters=filters,
            )
            base_case_id = str(spec.get("case_id") or f"{item.radar}-{item.date}-{request.pulse}-{request.time}-{request.quantity}")
            cases.append(
                WctParityCase(
                    case_id=f"{base_case_id}-{export_format}",
                    item=item,
                    request=request,
                    wct_input_path=str(spec.get("wct_input_path") or args.wct_input_path or "") or None,
                )
            )
    return cases


def cmd_validate_wct_suite(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = load_catalog(settings.catalog_path)
    cases = _wct_suite_cases_from_payload(args, items)
    report = run_parity_report(
        cases,
        Path(args.output_dir),
        wct_app=Path(args.wct_app),
        execute_wct=args.execute_wct,
        timeout_s=args.timeout,
        require_comparison=args.require_comparison,
        max_mean_abs_error=args.max_mean_abs_error,
        max_rmse=args.max_rmse,
    )
    write_report(Path(args.report), report)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    for result in report.results:
        print(f"WCT command: {shell_command(result.wct_command)}")
    return 0 if report.ok else 1


def cmd_object_store_plan(args: argparse.Namespace) -> int:
    settings = _settings(args)
    config = load_object_store_config(Path(args.config) if args.config else None)
    items = load_catalog(settings.catalog_path)
    plan = build_publication_plan(
        items=items,
        catalog_path=settings.catalog_path,
        config=config,
        staging_dir=Path(args.staging_dir),
        preview_dir=Path(args.preview_dir) if args.preview_dir else settings.preview_dir,
        tile_dir=Path(args.tile_dir) if args.tile_dir else settings.tile_dir,
        export_dir=Path(args.export_dir) if args.export_dir else settings.export_dir,
        validation_dir=Path(args.validation_dir) if args.validation_dir else None,
        run_id=args.run_id,
        sha256_cache_path=Path(args.sha256_cache) if args.sha256_cache else None,
    )
    write_plan(Path(args.output), plan)
    print(json.dumps({"wrote": str(args.output), **plan.summary()}, indent=2, sort_keys=True))
    return 0


def cmd_object_store_sync(args: argparse.Namespace) -> int:
    config = load_object_store_config(Path(args.config) if args.config else None)
    plan = load_plan(Path(args.plan))
    client = create_s3_client(config, internal=True) if args.execute else None
    manifest = sync_plan(plan, execute=args.execute, client=client, skip_existing=args.skip_existing)
    write_plan(Path(args.manifest), manifest)
    print(json.dumps({"wrote": str(args.manifest), "execute": args.execute, **manifest.summary()}, indent=2, sort_keys=True))
    return 0


def cmd_object_store_verify(args: argparse.Namespace) -> int:
    config = load_object_store_config(Path(args.config) if args.config else None)
    manifest = load_plan(Path(args.manifest))
    client = create_s3_client(config, internal=True) if args.execute else None
    verified = verify_plan(manifest, execute=args.execute, client=client)
    write_plan(Path(args.output), verified)
    print(json.dumps({"wrote": str(args.output), "execute": args.execute, **verified.summary()}, indent=2, sort_keys=True))
    return 0


def cmd_object_store_publish(args: argparse.Namespace) -> int:
    config = load_object_store_config(Path(args.config) if args.config else None)
    manifest = load_plan(Path(args.manifest))
    client = create_s3_client(config, internal=True) if args.execute else None
    result = publish_manifest(manifest, config, execute=args.execute, client=client)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _manifest_byte_count(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return sum(int(obj.get("size", 0)) for obj in payload.get("objects", []) if obj.get("status") == "verified")


def _catalog_batch_summary(path: Path) -> tuple[int, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, 0
    items = payload.get("items", [])
    if not isinstance(items, list):
        return 0, 0
    return len(items), sum(int(item.get("file_size", 0)) for item in items if isinstance(item, dict))


def cmd_object_store_backfill_status(args: argparse.Namespace) -> int:
    backfill_dir = Path(args.backfill_dir)
    catalogs = sorted(backfill_dir.glob("catalog-????????.json"))
    synced = sorted(backfill_dir.glob("synced-????????.json"))
    verified = sorted(backfill_dir.glob("verified-????????.json"))
    cache_path = Path(args.sha256_cache) if args.sha256_cache else backfill_dir / "sha256-cache.json"

    catalog_item_count = 0
    catalog_byte_count = 0
    for catalog in catalogs:
        item_count, byte_count = _catalog_batch_summary(catalog)
        catalog_item_count += item_count
        catalog_byte_count += byte_count

    cache_entries: dict[str, object] = {}
    if cache_path.exists():
        try:
            cache_entries = json.loads(cache_path.read_text(encoding="utf-8")).get("entries", {})
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
        "sha256_cache_byte_count": sum(int(value.get("size", 0)) for value in cache_entries.values() if isinstance(value, dict)),
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
        preview_dir=Path(args.preview_dir) if args.preview_dir else settings.preview_dir,
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
        preview_dir=Path(args.preview_dir) if args.preview_dir else settings.preview_dir,
        tile_dir=Path(args.tile_dir) if args.tile_dir else settings.tile_dir,
        export_dir=Path(args.export_dir) if args.export_dir else settings.export_dir,
        validation_dir=Path(args.validation_dir) if args.validation_dir else None,
        run_id=args.run_id,
    )
    plan_output = Path(args.plan_output)
    write_plan(plan_output, plan)

    missing_sources = [obj.key for obj in plan.objects if obj.status == "missing_source"]
    manifest_path = Path(args.manifest) if args.manifest else settings.object_store_manifest_path
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
    print(json.dumps({"wrote": str(output), "ok": summary["ok"], **plan.summary()}, indent=2, sort_keys=True))
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
    except Exception as exc:  # pragma: no cover - concrete client errors vary by S3 library.
        code = _client_error_code(exc)
        if code in {"404", "NoSuchBucket", "NotFound"}:
            return False
        raise


def _bucket_object_probe(client: object, bucket: str) -> dict[str, object]:
    try:
        response = client.list_objects_v2(Bucket=bucket, MaxKeys=1)
    except Exception as exc:  # pragma: no cover - concrete client errors vary by S3 library.
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
            actions.append({"bucket": bucket, "action": "delete_bucket", "status": "planned_empty_only"})
        for bucket in create_buckets:
            actions.append({"bucket": bucket, "action": "create_bucket", "status": "planned"})
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    client = create_s3_client(config, internal=True)
    ok = True
    for bucket in delete_buckets:
        try:
            probe = _bucket_object_probe(client, bucket)
            if not probe["exists"]:
                actions.append({"bucket": bucket, "action": "delete_bucket", "status": "already_absent", **probe})
                continue
            if not probe["empty"]:
                ok = False
                actions.append({"bucket": bucket, "action": "delete_bucket", "status": "not_empty", **probe})
                continue
            client.delete_bucket(Bucket=bucket)
            actions.append({"bucket": bucket, "action": "delete_bucket", "status": "deleted", **probe})
        except Exception as exc:  # pragma: no cover - concrete client errors vary by S3 library.
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
                actions.append({"bucket": bucket, "action": "create_bucket", "status": "already_exists"})
                continue
            client.create_bucket(Bucket=bucket)
            actions.append({"bucket": bucket, "action": "create_bucket", "status": "created"})
        except Exception as exc:  # pragma: no cover - concrete client errors vary by S3 library.
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


def cmd_session_list(args: argparse.Namespace) -> int:
    settings = _settings(args)
    payload = [session.__dict__ for session in list_sessions(settings.session_dir)]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_session_get(args: argparse.Namespace) -> int:
    settings = _settings(args)
    session = load_session(settings.session_dir, args.session_id)
    if session is None:
        raise SystemExit("session not found")
    print(json.dumps(session.__dict__, indent=2, sort_keys=True))
    return 0


def cmd_session_save(args: argparse.Namespace) -> int:
    settings = _settings(args)
    state = json.loads(Path(args.state_json).read_text(encoding="utf-8"))
    session = save_session(settings.session_dir, args.session_id, state, title=args.title or "")
    print(json.dumps(session.__dict__, indent=2, sort_keys=True))
    return 0


def cmd_session_export(args: argparse.Namespace) -> int:
    settings = _settings(args)
    session = load_session(settings.session_dir, args.session_id)
    if session is None:
        raise SystemExit("session not found")
    project = write_project_file(Path(args.output), session)
    print(json.dumps({"wrote": str(args.output), "session_id": project.session.session_id}, indent=2, sort_keys=True))
    return 0


def cmd_session_import(args: argparse.Namespace) -> int:
    settings = _settings(args)
    project = read_project_file(Path(args.project_json))
    session = import_project(settings.session_dir, project, session_id=args.session_id)
    print(json.dumps(session.__dict__, indent=2, sort_keys=True))
    return 0


def _add_filter_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--min-range-km", dest="min_range_km", type=float)
    parser.add_argument("--max-range-km", dest="max_range_km", type=float)
    parser.add_argument("--min-azimuth-deg", dest="min_azimuth_deg", type=float)
    parser.add_argument("--max-azimuth-deg", dest="max_azimuth_deg", type=float)
    parser.add_argument("--min-value", dest="min_value", type=float)
    parser.add_argument("--max-value", dest="max_value", type=float)
    parser.add_argument("--cappi-height-m", dest="cappi_height_m", type=float)
    parser.add_argument("--palette-stops", dest="palette_stops")
    parser.add_argument(
        "--qc-mode",
        dest="qc_mode",
        choices=("off", "display_standard", "signal_preserving", "vp_standard", "vp_strict"),
    )
    parser.add_argument("--noise-floor-enabled", dest="noise_floor_enabled", action="store_true", default=None)
    parser.add_argument("--noise-floor-method", dest="noise_floor_method", default=None)
    parser.add_argument("--noise-floor-margin-db", dest="noise_floor_margin_db", type=float)
    parser.add_argument("--noise-floor-operation", dest="noise_floor_operation", choices=("mask",), default=None)
    parser.add_argument("--noise-floor-percentile", dest="noise_floor_percentile", type=float)
    parser.add_argument("--noise-floor-window-bins", dest="noise_floor_window_bins", type=int)
    parser.add_argument("--noise-floor-texture-enabled", dest="noise_floor_texture_enabled", action="store_true", default=None)
    parser.add_argument("--noise-floor-texture-db", dest="noise_floor_texture_db", type=float)
    parser.add_argument("--noise-floor-texture-near-margin-db", dest="noise_floor_texture_near_margin_db", type=float)
    parser.add_argument("--noise-floor-texture-support-db", dest="noise_floor_texture_support_db", type=float)
    parser.add_argument("--noise-floor-texture-max-db", dest="noise_floor_texture_max_db", type=float)
    parser.add_argument(
        "--noise-floor-texture-min-similar-neighbors",
        dest="noise_floor_texture_min_similar_neighbors",
        type=int,
    )
    parser.add_argument("--qc-companion-enabled", dest="qc_companion_enabled", action="store_true", default=None)
    parser.add_argument("--qc-static-clutter-enabled", dest="qc_static_clutter_enabled", action="store_true", default=None)
    parser.add_argument("--qc-background-model-enabled", dest="qc_background_model_enabled", action="store_true", default=None)
    parser.add_argument("--qc-background-model", dest="qc_background_model_path")
    parser.add_argument(
        "--qc-background-persistent-frequency-min",
        dest="qc_background_persistent_frequency_min",
        type=float,
    )
    parser.add_argument("--qc-background-min-samples", dest="qc_background_min_samples", type=int)
    parser.add_argument(
        "--qc-background-static-vrad-frequency-min",
        dest="qc_background_static_vrad_frequency_min",
        type=float,
    )
    parser.add_argument(
        "--qc-background-low-sqi-frequency-min",
        dest="qc_background_low_sqi_frequency_min",
        type=float,
    )
    parser.add_argument("--qc-background-dbzh-excess-max-db", dest="qc_background_dbzh_excess_max_db", type=float)
    parser.add_argument(
        "--qc-background-evidence-score-threshold",
        dest="qc_background_evidence_score_threshold",
        type=int,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uk-wsr-visualizer")
    parser.add_argument("--catalog", help="Catalog JSON path.")
    subparsers = parser.add_subparsers(required=True)

    citation_parser = subparsers.add_parser("citation", help="Print citation and provenance guidance.")
    citation_parser.add_argument("--json", action="store_true", help="Emit machine-readable citation metadata.")
    citation_parser.set_defaults(func=cmd_citation)

    catalog_parser = subparsers.add_parser("catalog")
    catalog_sub = catalog_parser.add_subparsers(required=True)
    catalog_build = catalog_sub.add_parser("build")
    catalog_build.add_argument("--aggregate-base", type=Path, required=True)
    catalog_build.add_argument("--output", "--catalog", dest="catalog", required=True)
    catalog_build.add_argument("--radar")
    catalog_build.add_argument("--year")
    catalog_build.add_argument("--date")
    catalog_build.add_argument("--max-files", type=int)
    catalog_build.add_argument("--object-store-base", default="")
    catalog_build.add_argument("--metadata-mode", choices=["deep", "fast"], default="deep")
    catalog_build.set_defaults(func=cmd_catalog_build)

    catalog_build_raw = catalog_sub.add_parser("build-raw-volume")
    catalog_build_raw.add_argument("--raw-volume-base", type=Path, required=True)
    catalog_build_raw.add_argument("--output", "--catalog", dest="catalog", required=True)
    catalog_build_raw.add_argument("--radar")
    catalog_build_raw.add_argument("--year")
    catalog_build_raw.add_argument("--date")
    catalog_build_raw.add_argument("--max-files", type=int)
    catalog_build_raw.add_argument("--object-store-base", default="")
    catalog_build_raw.add_argument("--metadata-mode", choices=["deep", "fast"], default="deep")
    catalog_build_raw.set_defaults(func=cmd_catalog_build_raw_volume)

    catalog_stac = catalog_sub.add_parser("stac")
    catalog_stac.add_argument("--output-dir", required=True)
    catalog_stac.add_argument("--object-store-base", default="")
    catalog_stac.add_argument("--object-prefix", default=DEFAULT_OBJECT_PREFIX)
    catalog_stac.set_defaults(func=cmd_catalog_stac)

    preview_parser = subparsers.add_parser("preview")
    preview_sub = preview_parser.add_subparsers(required=True)
    preview_build = preview_sub.add_parser("build")
    preview_build.add_argument("--catalog")
    preview_build.add_argument("--radar", required=True)
    preview_build.add_argument("--date", required=True)
    preview_build.add_argument("--pulse", required=True)
    preview_build.add_argument("--time", required=True)
    preview_build.add_argument("--quantity", required=True)
    preview_build.add_argument("--dataset")
    preview_build.add_argument("--palette", default="gray")
    _add_filter_arguments(preview_build)
    preview_build.add_argument("--preview-dir", type=Path, default=Settings.from_env().preview_dir)
    preview_build.set_defaults(func=cmd_preview_build)

    preview_batch = preview_sub.add_parser("batch")
    preview_batch.add_argument("--catalog")
    preview_batch.add_argument("--radar")
    preview_batch.add_argument("--start")
    preview_batch.add_argument("--end")
    preview_batch.add_argument("--pulse")
    preview_batch.add_argument("--quantity")
    preview_batch.add_argument("--palette", default="gray")
    _add_filter_arguments(preview_batch)
    preview_batch.add_argument("--max-items", type=int)
    preview_batch.add_argument("--max-frames-per-item", type=int)
    preview_batch.add_argument("--keep-going", action="store_true")
    preview_batch.add_argument("--preview-dir", type=Path, default=Settings.from_env().preview_dir)
    preview_batch.set_defaults(func=cmd_preview_batch)

    animation_parser = subparsers.add_parser("animation")
    animation_sub = animation_parser.add_subparsers(required=True)
    animation_build = animation_sub.add_parser("build")
    animation_build.add_argument("--catalog")
    animation_build.add_argument("--radar", required=True)
    animation_build.add_argument("--date", required=True)
    animation_build.add_argument("--pulse", required=True)
    animation_build.add_argument("--quantity", required=True)
    animation_build.add_argument("--times", help="Comma-separated frame times. Defaults to every catalog time.")
    animation_build.add_argument("--dataset")
    animation_build.add_argument("--palette", default="gray")
    animation_build.add_argument("--frame-delay-ms", type=int, default=600)
    _add_filter_arguments(animation_build)
    animation_build.add_argument("--preview-dir", type=Path, default=Settings.from_env().preview_dir)
    animation_build.add_argument("--output-dir", required=True)
    animation_build.set_defaults(func=cmd_animation_build)

    tile_parser = subparsers.add_parser("tile")
    tile_sub = tile_parser.add_subparsers(required=True)
    tile_build = tile_sub.add_parser("build")
    tile_build.add_argument("--catalog")
    tile_build.add_argument("--radar", required=True)
    tile_build.add_argument("--date", required=True)
    tile_build.add_argument("--pulse", required=True)
    tile_build.add_argument("--time", required=True)
    tile_build.add_argument("--quantity", required=True)
    tile_build.add_argument("--dataset")
    tile_build.add_argument("--palette", default="gray")
    tile_build.add_argument("--tile-size", type=int, default=256)
    tile_build.add_argument("--min-zoom", type=int, default=0)
    tile_build.add_argument("--max-zoom", type=int, default=2)
    _add_filter_arguments(tile_build)
    tile_build.add_argument("--tile-dir", required=True)
    tile_build.set_defaults(func=cmd_tile_build)

    tile_batch = tile_sub.add_parser("batch")
    tile_batch.add_argument("--catalog")
    tile_batch.add_argument("--radar")
    tile_batch.add_argument("--start")
    tile_batch.add_argument("--end")
    tile_batch.add_argument("--pulse")
    tile_batch.add_argument("--quantity")
    tile_batch.add_argument("--palette", default="gray")
    tile_batch.add_argument("--tile-size", type=int, default=256)
    tile_batch.add_argument("--min-zoom", type=int, default=0)
    tile_batch.add_argument("--max-zoom", type=int, default=2)
    _add_filter_arguments(tile_batch)
    tile_batch.add_argument("--max-items", type=int)
    tile_batch.add_argument("--max-fields-per-item", type=int)
    tile_batch.add_argument("--keep-going", action="store_true")
    tile_batch.add_argument("--tile-dir", required=True)
    tile_batch.set_defaults(func=cmd_tile_batch)

    background_model_parser = subparsers.add_parser("build-background-model")
    background_model_parser.add_argument("--catalog")
    background_model_parser.add_argument("--radar", required=True)
    background_model_parser.add_argument("--start")
    background_model_parser.add_argument("--end")
    background_model_parser.add_argument("--pulse", required=True)
    background_model_parser.add_argument("--time")
    background_model_parser.add_argument("--quantity", required=True)
    background_model_parser.add_argument("--dataset")
    background_model_parser.add_argument("--output", required=True)
    background_model_parser.add_argument("--max-scans", type=int)
    background_model_parser.add_argument("--keep-going", action="store_true")
    background_model_parser.add_argument("--season-bucket", default="all")
    background_model_parser.add_argument("--time-of-day-bucket", default="all")
    background_model_parser.add_argument("--source-preview-count", type=int, default=25)
    background_model_parser.add_argument("--echo-threshold-dbz", type=float, default=0.0)
    background_model_parser.add_argument("--vrad-abs-max-ms", type=float, default=1.0)
    background_model_parser.add_argument("--sqi-low", type=float, default=0.45)
    background_model_parser.add_argument("--rhohv-low", type=float, default=0.75)
    background_model_parser.add_argument("--rhohv-texture-threshold", type=float, default=0.15)
    background_model_parser.add_argument("--zdr-min-db", type=float, default=-3.0)
    background_model_parser.add_argument("--zdr-max-db", type=float, default=8.0)
    background_model_parser.add_argument("--zdr-texture-threshold-db", type=float, default=2.0)
    background_model_parser.set_defaults(func=cmd_build_background_model)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--radar", required=True)
    export_parser.add_argument("--date", required=True)
    export_parser.add_argument("--format", required=True)
    export_parser.add_argument("--pulse")
    export_parser.add_argument("--time")
    export_parser.add_argument("--times", help="Comma-separated frame times for MP4 export.")
    export_parser.add_argument("--quantity")
    export_parser.add_argument("--dataset")
    export_parser.add_argument("--palette", default="gray")
    export_parser.add_argument("--frame-delay-ms", type=int, default=600)
    _add_filter_arguments(export_parser)
    export_parser.add_argument("--export-dir", type=Path, default=Settings.from_env().export_dir)
    export_parser.set_defaults(func=cmd_export)

    math_parser = subparsers.add_parser("math")
    math_parser.add_argument("--catalog")
    math_parser.add_argument("--radar", required=True)
    math_parser.add_argument("--date", required=True)
    math_parser.add_argument("--operation", required=True)
    math_parser.add_argument("--format", default="png")
    math_parser.add_argument("--palette", default="thermal")
    math_parser.add_argument("--left-pulse", required=True)
    math_parser.add_argument("--left-time", required=True)
    math_parser.add_argument("--left-quantity", required=True)
    math_parser.add_argument("--left-dataset")
    math_parser.add_argument("--right-pulse", required=True)
    math_parser.add_argument("--right-time", required=True)
    math_parser.add_argument("--right-quantity", required=True)
    math_parser.add_argument("--right-dataset")
    _add_filter_arguments(math_parser)
    math_parser.add_argument("--output-dir", required=True)
    math_parser.set_defaults(func=cmd_math)

    object_store = subparsers.add_parser("object-store")
    object_store_sub = object_store.add_subparsers(required=True)

    object_store_plan = object_store_sub.add_parser("plan")
    object_store_plan.add_argument("--config", required=True)
    object_store_plan.add_argument("--catalog")
    object_store_plan.add_argument("--output", required=True)
    object_store_plan.add_argument("--staging-dir", required=True)
    object_store_plan.add_argument("--preview-dir")
    object_store_plan.add_argument("--tile-dir")
    object_store_plan.add_argument("--export-dir")
    object_store_plan.add_argument("--validation-dir")
    object_store_plan.add_argument("--run-id")
    object_store_plan.add_argument("--sha256-cache")
    object_store_plan.set_defaults(func=cmd_object_store_plan)

    object_store_sync = object_store_sub.add_parser("sync")
    object_store_sync.add_argument("--config", required=True)
    object_store_sync.add_argument("--plan", required=True)
    object_store_sync.add_argument("--manifest", required=True)
    object_store_sync.add_argument("--execute", action="store_true")
    object_store_sync.add_argument("--skip-existing", action="store_true")
    object_store_sync.set_defaults(func=cmd_object_store_sync)

    object_store_verify = object_store_sub.add_parser("verify")
    object_store_verify.add_argument("--config", required=True)
    object_store_verify.add_argument("--manifest", required=True)
    object_store_verify.add_argument("--output", required=True)
    object_store_verify.add_argument("--execute", action="store_true")
    object_store_verify.set_defaults(func=cmd_object_store_verify)

    object_store_publish = object_store_sub.add_parser("publish")
    object_store_publish.add_argument("--config", required=True)
    object_store_publish.add_argument("--manifest", required=True)
    object_store_publish.add_argument("--output")
    object_store_publish.add_argument("--execute", action="store_true")
    object_store_publish.set_defaults(func=cmd_object_store_publish)

    object_store_backfill_status = object_store_sub.add_parser("backfill-status")
    object_store_backfill_status.add_argument("--backfill-dir", required=True)
    object_store_backfill_status.add_argument("--sha256-cache")
    object_store_backfill_status.set_defaults(func=cmd_object_store_backfill_status)

    object_store_reconcile = object_store_sub.add_parser("reconcile")
    object_store_reconcile.add_argument("--config", required=True)
    object_store_reconcile.add_argument("--catalog")
    object_store_reconcile.add_argument("--manifest", required=True)
    object_store_reconcile.add_argument("--output", required=True)
    object_store_reconcile.add_argument("--staging-dir", required=True)
    object_store_reconcile.add_argument("--preview-dir")
    object_store_reconcile.add_argument("--tile-dir")
    object_store_reconcile.add_argument("--export-dir")
    object_store_reconcile.add_argument("--validation-dir")
    object_store_reconcile.add_argument("--run-id")
    object_store_reconcile.set_defaults(func=cmd_object_store_reconcile)

    object_store_release = object_store_sub.add_parser("release-candidate")
    object_store_release.add_argument("--config", required=True)
    object_store_release.add_argument("--catalog")
    object_store_release.add_argument("--manifest")
    object_store_release.add_argument("--output", required=True)
    object_store_release.add_argument("--plan-output", required=True)
    object_store_release.add_argument("--staging-dir", required=True)
    object_store_release.add_argument("--preview-dir")
    object_store_release.add_argument("--tile-dir")
    object_store_release.add_argument("--export-dir")
    object_store_release.add_argument("--validation-dir")
    object_store_release.add_argument("--run-id")
    object_store_release.add_argument("--max-catalog-age-hours", type=float, default=24.0)
    object_store_release.add_argument("--max-data-latency-days", type=float, default=3.0)
    object_store_release.add_argument("--max-manifest-age-hours", type=float, default=30.0)
    object_store_release.add_argument("--skip-wct-validation", action="store_true")
    object_store_release.set_defaults(func=cmd_object_store_release_candidate)

    object_store_cors = object_store_sub.add_parser("cors-template")
    object_store_cors.add_argument("--config", required=True)
    object_store_cors.add_argument("--output", required=True)
    object_store_cors.set_defaults(func=cmd_object_store_cors_template)

    object_store_buckets = object_store_sub.add_parser("buckets")
    object_store_buckets.add_argument("--config", required=True)
    object_store_buckets.add_argument("--delete-empty-bucket", action="append", default=[])
    object_store_buckets.add_argument("--create-bucket", action="append", default=[])
    object_store_buckets.add_argument("--execute", action="store_true")
    object_store_buckets.set_defaults(func=cmd_object_store_buckets)

    session_parser = subparsers.add_parser("session")
    session_parser.add_argument("--session-dir", type=Path, default=Settings.from_env().session_dir)
    session_sub = session_parser.add_subparsers(required=True)
    session_list = session_sub.add_parser("list")
    session_list.set_defaults(func=cmd_session_list)
    session_get = session_sub.add_parser("get")
    session_get.add_argument("session_id")
    session_get.set_defaults(func=cmd_session_get)
    session_save = session_sub.add_parser("save")
    session_save.add_argument("session_id")
    session_save.add_argument("--state-json", required=True)
    session_save.add_argument("--title")
    session_save.set_defaults(func=cmd_session_save)
    session_export = session_sub.add_parser("export")
    session_export.add_argument("session_id")
    session_export.add_argument("--output", required=True)
    session_export.set_defaults(func=cmd_session_export)
    session_import = session_sub.add_parser("import")
    session_import.add_argument("--project-json", required=True)
    session_import.add_argument("--session-id")
    session_import.set_defaults(func=cmd_session_import)

    api_parser = subparsers.add_parser("api")
    api_parser.add_argument("--host", default="127.0.0.1")
    api_parser.add_argument("--port", type=int, default=8000)
    api_parser.set_defaults(func=cmd_api)

    freshness_parser = subparsers.add_parser("freshness")
    freshness_sub = freshness_parser.add_subparsers(required=True)
    freshness_check = freshness_sub.add_parser("check")
    freshness_check.add_argument("--catalog")
    freshness_check.add_argument("--object-store-manifest", dest="object_store_manifest", type=Path)
    freshness_check.add_argument("--max-catalog-age-hours", type=float, default=24.0)
    freshness_check.add_argument("--max-data-latency-days", type=float, default=3.0)
    freshness_check.add_argument("--max-manifest-age-hours", type=float, default=30.0)
    freshness_check.add_argument("--require-object-store", action="store_true")
    freshness_check.add_argument("--require-wct-validation", action="store_true")
    freshness_check.add_argument("--output")
    freshness_check.set_defaults(func=cmd_freshness_check)

    deployment_parser = subparsers.add_parser("deployment")
    deployment_sub = deployment_parser.add_subparsers(required=True)
    deployment_preflight = deployment_sub.add_parser("preflight")
    deployment_preflight.add_argument("--catalog")
    deployment_preflight.add_argument("--aggregate-base", type=Path)
    deployment_preflight.add_argument("--object-store-config")
    deployment_preflight.add_argument("--object-store-manifest", dest="object_store_manifest", type=Path)
    deployment_preflight.add_argument("--validation-dir")
    deployment_preflight.add_argument("--wct-app", default="/Applications/WCT-4.9.1.app")
    deployment_preflight.add_argument("--base-url")
    deployment_preflight.add_argument("--http-timeout", type=float, default=5.0)
    deployment_preflight.add_argument("--require-object-store", action="store_true")
    deployment_preflight.add_argument("--require-wct-validation", action="store_true")
    deployment_preflight.add_argument("--require-wct-app", action="store_true")
    deployment_preflight.add_argument("--output")
    deployment_preflight.set_defaults(func=cmd_deployment_preflight)

    validate_parser = subparsers.add_parser("validate")
    validate_sub = validate_parser.add_subparsers(required=True)
    validate_qc = validate_sub.add_parser("qc")
    validate_qc.add_argument("--catalog")
    validate_qc.add_argument("--radar", required=True)
    validate_qc.add_argument("--date", required=True)
    validate_qc.add_argument("--pulse", required=True)
    validate_qc.add_argument("--time", required=True)
    validate_qc.add_argument("--quantity", required=True)
    validate_qc.add_argument("--dataset")
    _add_filter_arguments(validate_qc)
    validate_qc.add_argument("--output-dir", required=True)
    validate_qc.add_argument("--report", required=True)
    validate_qc.add_argument("--require-real-hdf5", action="store_true")
    validate_qc.set_defaults(func=cmd_validate_qc)

    validate_wct = validate_sub.add_parser("wct")
    validate_wct.add_argument("--catalog")
    validate_wct.add_argument("--radar", required=True)
    validate_wct.add_argument("--date", required=True)
    validate_wct.add_argument("--format", required=True, choices=["geotiff", "kmz", "shapefile", "cf_netcdf"])
    validate_wct.add_argument("--pulse", required=True)
    validate_wct.add_argument("--time", required=True)
    validate_wct.add_argument("--quantity", required=True)
    validate_wct.add_argument("--dataset")
    _add_filter_arguments(validate_wct)
    validate_wct.add_argument("--wct-input-path")
    validate_wct.add_argument("--wct-app", default="/Applications/WCT-4.9.1.app")
    validate_wct.add_argument("--output-dir", required=True)
    validate_wct.add_argument("--report", required=True)
    validate_wct.add_argument("--case-id")
    validate_wct.add_argument("--execute-wct", action="store_true")
    validate_wct.add_argument("--timeout", type=int, default=1800)
    validate_wct.add_argument("--require-comparison", action="store_true")
    validate_wct.add_argument("--max-mean-abs-error", type=float, default=0.0)
    validate_wct.add_argument("--max-rmse", type=float, default=0.0)
    validate_wct.set_defaults(func=cmd_validate_wct)

    validate_suite = validate_sub.add_parser("wct-suite")
    validate_suite.add_argument("--catalog")
    validate_suite.add_argument("--cases-json", help="JSON list of representative reference validation cases.")
    validate_suite.add_argument("--radar")
    validate_suite.add_argument("--date")
    validate_suite.add_argument("--pulse")
    validate_suite.add_argument("--time")
    validate_suite.add_argument("--quantity")
    validate_suite.add_argument("--dataset")
    validate_suite.add_argument("--formats", default="geotiff,kmz,shapefile,cf_netcdf")
    _add_filter_arguments(validate_suite)
    validate_suite.add_argument("--wct-input-path")
    validate_suite.add_argument("--wct-app", default="/Applications/WCT-4.9.1.app")
    validate_suite.add_argument("--output-dir", required=True)
    validate_suite.add_argument("--report", required=True)
    validate_suite.add_argument("--case-id")
    validate_suite.add_argument("--execute-wct", action="store_true")
    validate_suite.add_argument("--timeout", type=int, default=1800)
    validate_suite.add_argument("--require-comparison", action="store_true")
    validate_suite.add_argument("--max-mean-abs-error", type=float, default=0.0)
    validate_suite.add_argument("--max-rmse", type=float, default=0.0)
    validate_suite.set_defaults(func=cmd_validate_wct_suite)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "output") and not getattr(args, "catalog", None) and args.__dict__.get("func") == cmd_catalog_build:
        args.catalog = args.output
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
