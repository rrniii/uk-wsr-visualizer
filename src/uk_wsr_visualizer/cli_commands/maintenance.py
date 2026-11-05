"""API, diagnostic and validation commands."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from ..catalog import CatalogItem, filter_catalog, load_catalog
from ..compat import UTC
from ..export import ExportRequest, run_export
from ..freshness import build_freshness_report, write_freshness_report
from ..preflight import build_preflight_report, write_preflight_report
from ..wct_parity import WctParityCase, run_parity_report, shell_command, write_report
from .common import _add_filter_arguments, _filter_args, _settings, _split_csv

WCT_SUITE_FORMATS = {"geotiff", "kmz", "shapefile", "cf_netcdf"}


def cmd_api(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "uvicorn is required to run the API. Install with: pip install -e ."
        ) from exc

    settings = _settings(args)
    from ..api.app import create_app

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
        object_store_config_path=Path(args.object_store_config)
        if args.object_store_config
        else None,
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
    matches = filter_catalog(
        load_catalog(settings.catalog_path),
        radar=args.radar,
        start=args.date,
        end=args.date,
    )
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
    sidecar_path = (
        output_path.with_suffix(output_path.suffix + ".json") if output_path else None
    )
    sidecar = {}
    if sidecar_path is not None and sidecar_path.exists():
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    source_path = Path(item.path)
    real_hdf5 = source_path.exists() and source_path.suffix.lower() in {".h5", ".hdf5"}
    ok = job.status == "complete" and (real_hdf5 or not args.require_real_hdf5)
    report = {
        "version": 1,
        "validation_type": "qc_mask",
        "created_at": datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
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
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ok else 1


def cmd_validate_wct(args: argparse.Namespace) -> int:
    settings = _settings(args)
    matches = filter_catalog(
        load_catalog(settings.catalog_path),
        radar=args.radar,
        start=args.date,
        end=args.date,
    )
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


def _wct_suite_cases_from_payload(
    args: argparse.Namespace, items: list[CatalogItem]
) -> list[WctParityCase]:
    cases: list[WctParityCase] = []
    formats_default = _split_csv(
        args.formats, ["geotiff", "kmz", "shapefile", "cf_netcdf"]
    )
    unknown_defaults = sorted(set(formats_default) - WCT_SUITE_FORMATS)
    if unknown_defaults:
        raise SystemExit(
            f"unsupported WCT suite format(s): {', '.join(unknown_defaults)}"
        )
    if args.cases_json:
        payload = json.loads(Path(args.cases_json).read_text(encoding="utf-8"))
        raw_cases = (
            payload.get("cases", payload) if isinstance(payload, dict) else payload
        )
        if not isinstance(raw_cases, list):
            raise SystemExit("cases JSON must be a list or an object with a cases list")
        case_specs = raw_cases
    else:
        required = ("radar", "date", "pulse", "time", "quantity")
        missing = [name for name in required if not getattr(args, name)]
        if missing:
            raise SystemExit(
                f"missing required suite selector(s): {', '.join(missing)}"
            )
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
        missing_selectors = [
            name for name, value in required_selectors.items() if not value
        ]
        if missing_selectors:
            label = spec.get("case_id") or index
            raise SystemExit(
                f"case {label} missing required selector(s): {', '.join(missing_selectors)}"
            )
        matches = [
            item for item in catalog_items if item.radar == radar and item.date == date
        ]
        if not matches:
            raise SystemExit(
                f"no matching catalog item for case {index}: radar={radar}, date={date}"
            )
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
            base_case_id = str(
                spec.get("case_id")
                or f"{item.radar}-{item.date}-{request.pulse}-{request.time}-{request.quantity}"
            )
            cases.append(
                WctParityCase(
                    case_id=f"{base_case_id}-{export_format}",
                    item=item,
                    request=request,
                    wct_input_path=str(
                        spec.get("wct_input_path") or args.wct_input_path or ""
                    )
                    or None,
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


def register_maintenance_commands(subparsers):
    api_parser = subparsers.add_parser("api")
    api_parser.add_argument("--host", default="127.0.0.1")
    api_parser.add_argument("--port", type=int, default=8000)
    api_parser.set_defaults(func=cmd_api)

    freshness_parser = subparsers.add_parser("freshness")
    freshness_sub = freshness_parser.add_subparsers(required=True)
    freshness_check = freshness_sub.add_parser("check")
    freshness_check.add_argument("--catalog")
    freshness_check.add_argument(
        "--object-store-manifest", dest="object_store_manifest", type=Path
    )
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
    deployment_preflight.add_argument(
        "--object-store-manifest", dest="object_store_manifest", type=Path
    )
    deployment_preflight.add_argument("--validation-dir")
    deployment_preflight.add_argument(
        "--wct-app", default="/Applications/WCT-4.9.1.app"
    )
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
    validate_wct.add_argument(
        "--format", required=True, choices=["geotiff", "kmz", "shapefile", "cf_netcdf"]
    )
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
    validate_suite.add_argument(
        "--cases-json", help="JSON list of representative reference validation cases."
    )
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
