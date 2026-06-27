"""Deployment preflight checks for UK WSR Visualizer services."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from .catalog import load_catalog
from .compat import UTC
from .config import Settings
from .object_store_config import load_object_store_config
from .object_store_manifest import load_plan
from .wct_parity import wct_export_script


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    ok: bool
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreflightReport:
    ok: bool
    created_at: str
    checks: list[PreflightCheck]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validation_report_count(validation_dir: Path) -> tuple[int, dict[str, int]]:
    counts: dict[str, int] = {}
    report_count = 0
    if not validation_dir.exists():
        return 0, counts
    for path in sorted(validation_dir.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        results = payload.get("results", [])
        if not isinstance(results, list):
            continue
        report_count += 1
        for result in results:
            if isinstance(result, dict):
                status = str(result.get("parity_status", "unknown"))
                counts[status] = counts.get(status, 0) + 1
    return report_count, counts


def build_preflight_report(
    settings: Settings,
    object_store_config_path: Path | None = None,
    validation_dir: Path | None = None,
    wct_app: Path | None = None,
    base_url: str | None = None,
    require_object_store: bool = False,
    require_wct_validation: bool = False,
    require_wct_app: bool = False,
    http_timeout_s: float = 5.0,
) -> PreflightReport:
    checks: list[PreflightCheck] = []

    aggregate_exists = settings.aggregate_base.exists()
    checks.append(
        PreflightCheck(
            name="aggregate_base_exists",
            ok=aggregate_exists,
            severity="critical",
            message="aggregate base exists" if aggregate_exists else "aggregate base is missing",
            details={"path": str(settings.aggregate_base)},
        )
    )

    catalog_exists = settings.catalog_path.exists()
    catalog_items = []
    catalog_error = ""
    if catalog_exists:
        try:
            catalog_items = load_catalog(settings.catalog_path)
        except Exception as exc:
            catalog_error = f"{type(exc).__name__}: {exc}"
    checks.append(
        PreflightCheck(
            name="catalog_readable",
            ok=catalog_exists and not catalog_error and bool(catalog_items),
            severity="critical",
            message=f"catalog contains {len(catalog_items)} item(s)"
            if catalog_exists and not catalog_error
            else catalog_error or "catalog is missing",
            details={"path": str(settings.catalog_path), "item_count": len(catalog_items)},
        )
    )

    config_required = require_object_store or object_store_config_path is not None
    if object_store_config_path is None:
        checks.append(
            PreflightCheck(
                name="object_store_config",
                ok=not config_required,
                severity="critical" if config_required else "warning",
                message="object-store config not provided",
                details={},
            )
        )
    else:
        try:
            config = load_object_store_config(object_store_config_path)
            checks.append(
                PreflightCheck(
                    name="object_store_config",
                    ok=True,
                    severity="critical",
                    message="object-store config is readable",
                    details={
                        "path": str(object_store_config_path),
                        "tenancy": config.tenancy,
                        "public_bucket": config.public_bucket,
                        "staging_bucket": config.staging_bucket,
                    },
                )
            )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    name="object_store_config",
                    ok=False,
                    severity="critical",
                    message=f"{type(exc).__name__}: {exc}",
                    details={"path": str(object_store_config_path)},
                )
            )

    manifest_exists = settings.object_store_manifest_path.exists()
    if not manifest_exists:
        checks.append(
            PreflightCheck(
                name="object_store_manifest",
                ok=not require_object_store,
                severity="critical" if require_object_store else "warning",
                message="object-store manifest is missing",
                details={"path": str(settings.object_store_manifest_path), "required": require_object_store},
            )
        )
    else:
        try:
            manifest = load_plan(settings.object_store_manifest_path)
            unverified = [obj.key for obj in manifest.objects if obj.status != "verified"]
            checks.append(
                PreflightCheck(
                    name="object_store_manifest",
                    ok=not unverified,
                    severity="critical",
                    message="object-store manifest is verified"
                    if not unverified
                    else f"{len(unverified)} manifest object(s) are not verified",
                    details={
                        "path": str(settings.object_store_manifest_path),
                        "object_count": len(manifest.objects),
                        "unverified": unverified[:10],
                    },
                )
            )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    name="object_store_manifest",
                    ok=False,
                    severity="critical",
                    message=f"{type(exc).__name__}: {exc}",
                    details={"path": str(settings.object_store_manifest_path)},
                )
            )

    validation_dir = validation_dir or (settings.data_dir / "validation" / "wct")
    report_count, parity_counts = _validation_report_count(validation_dir)
    validation_ok = report_count > 0 and parity_counts and set(parity_counts) == {"passed"}
    checks.append(
        PreflightCheck(
            name="wct_validation_reports",
            ok=validation_ok or not require_wct_validation,
            severity="critical" if require_wct_validation else "warning",
            message=f"{report_count} reference validation report(s) found"
            if report_count
            else "no reference validation reports found",
            details={
                "path": str(validation_dir),
                "required": require_wct_validation,
                "report_count": report_count,
                "by_parity_status": parity_counts,
            },
        )
    )

    if wct_app is not None:
        script = wct_export_script(wct_app)
        script_exists = script.exists()
        checks.append(
            PreflightCheck(
                name="wct_app",
                ok=script_exists or not require_wct_app,
                severity="critical" if require_wct_app else "warning",
                message="reference export script exists" if script_exists else "reference export script is missing",
                details={"wct_app": str(wct_app), "export_script": str(script), "required": require_wct_app},
            )
        )

    if base_url:
        try:
            with urlopen(f"{base_url.rstrip('/')}/api/status", timeout=http_timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
            checks.append(
                PreflightCheck(
                    name="api_status",
                    ok=payload.get("ok") is True,
                    severity="critical",
                    message="API status endpoint is healthy" if payload.get("ok") is True else "API status endpoint is unhealthy",
                    details={"base_url": base_url, "payload": payload},
                )
            )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    name="api_status",
                    ok=False,
                    severity="critical",
                    message=f"{type(exc).__name__}: {exc}",
                    details={"base_url": base_url},
                )
            )

    ok = all(check.ok or check.severity == "warning" for check in checks)
    return PreflightReport(ok=ok, created_at=_now(), checks=checks)


def write_preflight_report(path: Path, report: PreflightReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
