"""Operational freshness checks for catalog, products, and object-store state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .catalog import CatalogItem, load_catalog
from .compat import UTC
from .object_store_manifest import load_plan


@dataclass(frozen=True)
class FreshnessCheck:
    name: str
    ok: bool
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FreshnessReport:
    ok: bool
    created_at: str
    catalog_path: str
    object_store_manifest_path: str
    checks: list[FreshnessCheck]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _catalog_latest_date(items: list[CatalogItem]) -> str | None:
    dates = sorted(item.date for item in items if item.date)
    return dates[-1] if dates else None


def _contains_private_path(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    private_markers = ("/gws/", "/badc/", "/work/", "/home/", "raw_h5_data_final")
    return any(marker in text for marker in private_markers)


def _validation_report_details(manifest) -> dict[str, Any]:
    reports = [obj for obj in manifest.objects if obj.kind == "validation_report"]
    details: dict[str, Any] = {
        "report_count": len(reports),
        "unverified": [obj.key for obj in reports if obj.status != "verified"],
        "failed": [],
        "unreadable": [],
        "by_parity_status": {},
    }
    for obj in reports:
        path = Path(obj.source_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            details["unreadable"].append({"key": obj.key, "error": f"{type(exc).__name__}: {exc}"})
            continue
        results = payload.get("results", [])
        if not isinstance(results, list) or not results:
            details["failed"].append({"key": obj.key, "reason": "report has no validation results"})
            continue
        for result in results:
            if not isinstance(result, dict):
                details["failed"].append({"key": obj.key, "reason": "report contains a non-object result"})
                continue
            status = str(result.get("parity_status", "unknown"))
            details["by_parity_status"][status] = details["by_parity_status"].get(status, 0) + 1
            if status != "passed":
                details["failed"].append(
                    {
                        "key": obj.key,
                        "case_id": result.get("case_id", ""),
                        "parity_status": status,
                    }
                )
    return details


def build_freshness_report(
    catalog_path: Path,
    object_store_manifest_path: Path,
    max_catalog_age_hours: float = 24.0,
    max_data_latency_days: float = 3.0,
    max_manifest_age_hours: float = 30.0,
    require_object_store: bool = False,
    require_wct_validation: bool = False,
    now: datetime | None = None,
) -> FreshnessReport:
    now = now or utc_now()
    checks: list[FreshnessCheck] = []

    catalog_exists = catalog_path.exists()
    checks.append(
        FreshnessCheck(
            name="catalog_exists",
            ok=catalog_exists,
            severity="critical",
            message="catalog exists" if catalog_exists else "catalog is missing",
            details={"catalog_path": str(catalog_path)},
        )
    )

    items: list[CatalogItem] = load_catalog(catalog_path) if catalog_exists else []
    checks.append(
        FreshnessCheck(
            name="catalog_not_empty",
            ok=bool(items),
            severity="critical",
            message=f"catalog contains {len(items)} item(s)" if items else "catalog contains no items",
            details={"item_count": len(items)},
        )
    )

    if catalog_exists:
        age_hours = (now.timestamp() - catalog_path.stat().st_mtime) / 3600.0
        checks.append(
            FreshnessCheck(
                name="catalog_file_age",
                ok=age_hours <= max_catalog_age_hours,
                severity="warning",
                message=f"catalog file age is {age_hours:.2f} hours",
                details={"age_hours": age_hours, "max_age_hours": max_catalog_age_hours},
            )
        )

    latest = _catalog_latest_date(items)
    latest_dt = _parse_date(latest) if latest else None
    if latest_dt is not None:
        latency_days = (now.date() - latest_dt.date()).days
        checks.append(
            FreshnessCheck(
                name="catalog_data_latency",
                ok=latency_days <= max_data_latency_days,
                severity="warning",
                message=f"latest catalog date is {latest}",
                details={"latest_date": latest, "latency_days": latency_days, "max_latency_days": max_data_latency_days},
            )
        )

    manifest_exists = object_store_manifest_path.exists()
    checks.append(
        FreshnessCheck(
            name="object_store_manifest_exists",
            ok=manifest_exists or not require_object_store,
            severity="critical" if require_object_store else "warning",
            message="object-store manifest exists" if manifest_exists else "object-store manifest is missing",
            details={"manifest_path": str(object_store_manifest_path), "required": require_object_store},
        )
    )

    if manifest_exists:
        manifest_age_hours = (now.timestamp() - object_store_manifest_path.stat().st_mtime) / 3600.0
        checks.append(
            FreshnessCheck(
                name="object_store_manifest_age",
                ok=manifest_age_hours <= max_manifest_age_hours,
                severity="warning",
                message=f"object-store manifest age is {manifest_age_hours:.2f} hours",
                details={"age_hours": manifest_age_hours, "max_age_hours": max_manifest_age_hours},
            )
        )
        try:
            manifest = load_plan(object_store_manifest_path)
            unverified = [obj.key for obj in manifest.objects if obj.status != "verified"]
            checks.append(
                FreshnessCheck(
                    name="object_store_manifest_verified",
                    ok=not unverified,
                    severity="critical",
                    message="all manifest objects are verified" if not unverified else f"{len(unverified)} object(s) are unverified",
                    details={"unverified_count": len(unverified), "examples": unverified[:10]},
                )
            )
            inventory_objects = [obj for obj in manifest.objects if obj.kind == "catalog_inventory"]
            private_inventory = [obj.key for obj in inventory_objects if _contains_private_path(Path(obj.source_path))]
            checks.append(
                FreshnessCheck(
                    name="public_inventory_sanitized",
                    ok=not private_inventory,
                    severity="critical",
                    message="public catalog inventory has no private path markers"
                    if not private_inventory
                    else "public catalog inventory contains private path markers",
                    details={"private_inventory": private_inventory},
                )
            )
            validation = _validation_report_details(manifest)
            validation_required = require_wct_validation
            checks.append(
                FreshnessCheck(
                    name="wct_validation_reports_present",
                    ok=validation["report_count"] > 0 or not validation_required,
                    severity="critical" if validation_required else "warning",
                    message=f"{validation['report_count']} WCT validation report(s) found"
                    if validation["report_count"]
                    else "no WCT validation reports found",
                    details={"required": validation_required, "report_count": validation["report_count"]},
                )
            )
            if validation["report_count"]:
                checks.append(
                    FreshnessCheck(
                        name="wct_validation_reports_verified",
                        ok=not validation["unverified"],
                        severity="critical" if validation_required else "warning",
                        message="all WCT validation reports are verified"
                        if not validation["unverified"]
                        else f"{len(validation['unverified'])} WCT validation report(s) are unverified",
                        details={"unverified": validation["unverified"][:10]},
                    )
                )
                checks.append(
                    FreshnessCheck(
                        name="wct_validation_parity_passed",
                        ok=not validation["failed"] and not validation["unreadable"],
                        severity="critical" if validation_required else "warning",
                        message="all WCT validation cases passed"
                        if not validation["failed"] and not validation["unreadable"]
                        else "one or more WCT validation reports failed or could not be read",
                        details=validation,
                    )
                )
        except Exception as exc:
            checks.append(
                FreshnessCheck(
                    name="object_store_manifest_readable",
                    ok=False,
                    severity="critical",
                    message=f"{type(exc).__name__}: {exc}",
                    details={},
                )
            )

    ok = all(check.ok or check.severity == "warning" for check in checks)
    return FreshnessReport(
        ok=ok,
        created_at=now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        catalog_path=str(catalog_path),
        object_store_manifest_path=str(object_store_manifest_path),
        checks=checks,
    )


def write_freshness_report(path: Path, report: FreshnessReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
