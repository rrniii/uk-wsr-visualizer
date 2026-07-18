"""Audit candidate receiver-noise removals against a physical range law."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dependencies import require_numpy
from .qc_evidence import EvidenceFlag, NuisanceFlag
from .receiver_noise_model import (
    ReceiverNoiseModelConfig,
    fit_range_corrected_receiver_noise,
)


def audit_receiver_noise_physics(
    validation_results: str | Path,
    *,
    config: ReceiverNoiseModelConfig | None = None,
) -> dict[str, Any]:
    """Measure physical support without treating the range law as truth."""

    source = Path(validation_results)
    report = json.loads(source.read_text(encoding="utf-8"))
    if report.get("schema") != "uk_wsr_background_validation_results":
        raise ValueError("unexpected background validation schema")
    if not report.get("complete"):
        raise ValueError("background validation report is incomplete")

    active = config or ReceiverNoiseModelConfig()
    rows = []
    for record in report.get("records", ()):
        rows.append(_audit_record(record, config=active))

    groups = {
        name: _summarise_rows(selected)
        for name, selected in _audit_groups(rows).items()
    }
    return {
        "schema": "uk_wsr_receiver_noise_physics_audit",
        "schema_version": 1,
        "generated_at": _now_utc(),
        "validation_results": str(source),
        "validation_results_sha256": _file_sha256(source),
        "configuration_sha256": report["configuration_sha256"],
        "fit_config": asdict(active),
        "interpretation": (
            "descriptive physical-support audit; a qualified range law is "
            "independent evidence of a receiver pedestal, not a class label"
        ),
        "record_count": len(rows),
        "status_counts": dict(
            sorted(Counter(row["fit_status"] for row in rows).items())
        ),
        "groups": groups,
        "records": rows,
    }


def write_receiver_noise_physics_audit(
    audit: dict[str, Any],
    *,
    output_json: str | Path,
    output_csv: str | Path | None = None,
) -> tuple[Path, Path | None]:
    destination = Path(output_json)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    csv_destination = None
    if output_csv is not None:
        csv_destination = Path(output_csv)
        csv_destination.parent.mkdir(parents=True, exist_ok=True)
        fields = (
            "job_id",
            "radar",
            "pulse",
            "elevation_deg",
            "geometry_class",
            "fit_status",
            "fit_qualified",
            "range_slope_db_per_decade",
            "range_intercept_db",
            "residual_scale_db",
            "supported_bin_count",
            "supported_span_km",
            "receiver_noise_count",
            "physically_supported_receiver_noise_count",
            "unsupported_receiver_noise_count",
            "physically_supported_receiver_noise_fraction",
            "receiver_noise_linear_reflectivity_fraction",
            "supported_receiver_noise_linear_reflectivity_fraction",
        )
        with csv_destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in audit["records"]:
                writer.writerow({field: row.get(field) for field in fields})
    return destination, csv_destination


def _audit_record(
    record: dict[str, Any],
    *,
    config: ReceiverNoiseModelConfig,
) -> dict[str, Any]:
    np = require_numpy()
    artifact = Path(record["artifact_npz"])
    with np.load(artifact) as loaded:
        dbzh = np.asarray(loaded["dbzh_raw"], dtype="float32")
        evidence = np.asarray(
            loaded["baseline_evidence_mask"],
            dtype="uint32",
        )
        nuisance = np.asarray(
            loaded["baseline_nuisance_mask"],
            dtype="uint16",
        )
    seeds = (
        ((evidence & int(EvidenceFlag.HIGH_CI)) != 0)
        & ((evidence & int(EvidenceFlag.LOW_SQI)) != 0)
    )
    model = fit_range_corrected_receiver_noise(
        dbzh,
        seeds,
        rstart_km=float(record["rstart_km"]),
        rscale_m=float(record["rscale_m"]),
        config=config,
    )
    receiver = (
        nuisance & int(NuisanceFlag.RECEIVER_NOISE)
    ) != 0
    supported = receiver & model.compatible_mask
    unsupported = receiver & ~model.compatible_mask
    receiver_count = int(receiver.sum())
    supported_count = int(supported.sum())
    finite = np.isfinite(dbzh)
    total_power = _linear_power_sum(dbzh[finite])
    receiver_power = _linear_power_sum(dbzh[receiver])
    supported_power = _linear_power_sum(dbzh[supported])
    return {
        "job_id": record["job_id"],
        "target_id": record["target_id"],
        "radar": record["radar"],
        "pulse": record["pulse"],
        "elevation_deg": float(record["elevation_deg"]),
        "geometry_class": record["geometry_class"],
        "fit_status": model.status,
        "fit_qualified": model.qualified,
        "range_slope_db_per_decade": (
            model.range_slope_db_per_decade
        ),
        "range_intercept_db": model.range_intercept_db,
        "residual_location_db": model.residual_location_db,
        "residual_scale_db": model.residual_scale_db,
        "supported_bin_count": model.supported_bin_count,
        "supported_span_km": model.supported_span_km,
        "consistent_bin_fraction": model.consistent_bin_fraction,
        "fit_median_error_db": model.fit_median_error_db,
        "receiver_noise_count": receiver_count,
        "physically_supported_receiver_noise_count": supported_count,
        "unsupported_receiver_noise_count": int(unsupported.sum()),
        "physically_supported_receiver_noise_fraction": _fraction(
            supported_count,
            receiver_count,
        ),
        "receiver_noise_linear_reflectivity_fraction": _fraction(
            receiver_power,
            total_power,
        ),
        "supported_receiver_noise_linear_reflectivity_fraction": _fraction(
            supported_power,
            receiver_power,
        ),
    }


def _audit_groups(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    groups = {
        "all": rows,
        "lp": [row for row in rows if row["pulse"] == "lp"],
        "sp": [row for row in rows if row["pulse"] == "sp"],
        "ppi": [
            row for row in rows if row["geometry_class"] == "ppi"
        ],
        "vertical": [
            row for row in rows if row["geometry_class"] == "vertical"
        ],
        "sp_9_degree": [
            row
            for row in rows
            if row["pulse"] == "sp"
            and row["geometry_class"] == "ppi"
            and 8.5 <= row["elevation_deg"] <= 9.5
        ],
    }
    return {name: selected for name, selected in groups.items() if selected}


def _summarise_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    receiver_count = sum(row["receiver_noise_count"] for row in rows)
    supported_count = sum(
        row["physically_supported_receiver_noise_count"]
        for row in rows
    )
    return {
        "sweep_count": len(rows),
        "qualified_sweep_count": sum(
            bool(row["fit_qualified"]) for row in rows
        ),
        "qualified_sweep_fraction": _fraction(
            sum(bool(row["fit_qualified"]) for row in rows),
            len(rows),
        ),
        "receiver_noise_count": receiver_count,
        "physically_supported_receiver_noise_count": supported_count,
        "unsupported_receiver_noise_count": (
            receiver_count - supported_count
        ),
        "physically_supported_receiver_noise_fraction": _fraction(
            supported_count,
            receiver_count,
        ),
        "status_counts": dict(
            sorted(Counter(row["fit_status"] for row in rows).items())
        ),
    }


def _linear_power_sum(values: Any) -> float:
    np = require_numpy()
    array = np.asarray(values, dtype="float64")
    if array.size == 0:
        return 0.0
    return float(np.power(10.0, array / 10.0).sum())


def _fraction(numerator: float | int, denominator: float | int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
