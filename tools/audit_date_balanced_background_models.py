#!/usr/bin/env python3
"""Audit qc-v3 date-balanced models before temporal validation."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uk_wsr_visualizer.background_model import load_background_model
from uk_wsr_visualizer.background_model_v3 import (
    BACKGROUND_MODEL_V3_ARRAY_NAMES,
    BACKGROUND_MODEL_V3_STATISTICS_VERSION,
)
from uk_wsr_visualizer.dependencies import require_numpy
from uk_wsr_visualizer.qc_evidence import EvidenceConfig

REQUIRED_ARRAYS = set(BACKGROUND_MODEL_V3_ARRAY_NAMES) | {
    "dbzh_p10",
    "dbzh_median",
    "dbzh_p90",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("/tmp/uk_wsr_background_models_v3_candidate4"),
    )
    parser.add_argument(
        "--archive-manifest",
        type=Path,
        default=Path("validation/background_training_v2/manifest.json"),
    )
    parser.add_argument(
        "--temporal-manifest",
        type=Path,
        default=Path("validation/temporal_context_v1/manifest.json"),
    )
    parser.add_argument("--expected-target-count", type=int, default=187)
    parser.add_argument("--minimum-distinct-dates", type=int, default=8)
    parser.add_argument(
        "--minimum-static-date-frequency",
        type=float,
        default=0.875,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "reports/background_training_v3_candidate4/model_audit.json"
        ),
    )
    args = parser.parse_args()

    source_index = _source_index(
        args.archive_manifest,
        args.temporal_manifest,
    )
    model_paths = sorted(args.model_dir.glob("*.json"))
    errors: list[str] = []
    if len(model_paths) != args.expected_target_count:
        errors.append(
            f"model count {len(model_paths)} != "
            f"{args.expected_target_count}"
        )

    records: list[dict[str, Any]] = []
    contract_hashes: set[str] = set()
    for path in model_paths:
        try:
            record = _audit_model(
                path,
                source_index=source_index,
                minimum_distinct_dates=args.minimum_distinct_dates,
                minimum_static_date_frequency=(
                    args.minimum_static_date_frequency
                ),
            )
            records.append(record)
            contract_hashes.add(record["training_contract_sha256"])
            errors.extend(
                f"{record['target_id']}: {message}"
                for message in record["errors"]
            )
        except Exception as exc:  # noqa: BLE001 - persisted audit failure.
            errors.append(f"{path.name}: {type(exc).__name__}: {exc}")

    radars = sorted({record["radar"] for record in records})
    pulses = sorted({record["pulse"] for record in records})
    target_ids = [record["target_id"] for record in records]
    if len(target_ids) != len(set(target_ids)):
        errors.append("duplicate target IDs")
    if len(radars) != 17:
        errors.append(f"radar count {len(radars)} != 17")
    if pulses != ["lp", "sp"]:
        errors.append(f"pulse coverage is {pulses}, expected lp and sp")
    if len(contract_hashes) != 1:
        errors.append(
            f"training contract count {len(contract_hashes)} != 1"
        )

    count_by_geometry = Counter(
        record["geometry_class"] for record in records
    )
    count_by_pulse = Counter(record["pulse"] for record in records)
    payload = {
        "schema": "uk_wsr_date_balanced_model_audit",
        "schema_version": 1,
        "generated_at": _now_utc(),
        "model_dir": str(args.model_dir),
        "expected_target_count": args.expected_target_count,
        "model_count": len(records),
        "radars": radars,
        "radar_count": len(radars),
        "pulses": pulses,
        "count_by_pulse": dict(sorted(count_by_pulse.items())),
        "count_by_geometry": dict(sorted(count_by_geometry.items())),
        "training_contract_sha256": (
            next(iter(contract_hashes))
            if len(contract_hashes) == 1
            else None
        ),
        "coverage_policy": {
            "minimum_distinct_dates": args.minimum_distinct_dates,
            "minimum_static_date_frequency": (
                args.minimum_static_date_frequency
            ),
            "required_season_count": 4,
            "required_time_bucket_count": 2,
        },
        "eligible_gate_count": sum(
            record["eligible_gate_count"] for record in records
        ),
        "eligible_target_count": sum(
            record["eligible_gate_count"] > 0 for record in records
        ),
        "vertical_application_policy": (
            "trained and audited separately; not enabled until a "
            "vertical-specific validation gate passes"
        ),
        "records": records,
        "errors": errors,
        "audit_passed": not errors,
        "promotion_eligible": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(
        json.dumps(
            {
                "audit_passed": payload["audit_passed"],
                "model_count": payload["model_count"],
                "radar_count": payload["radar_count"],
                "eligible_target_count": payload[
                    "eligible_target_count"
                ],
                "error_count": len(errors),
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if payload["audit_passed"] else 1


def _audit_model(
    path: Path,
    *,
    source_index: dict[str, dict[str, Any]],
    minimum_distinct_dates: int,
    minimum_static_date_frequency: float,
) -> dict[str, Any]:
    np = require_numpy()
    model = load_background_model(path)
    target_id = str(model.key.get("geometry_id") or path.stem)
    model_errors: list[str] = []
    if model.metadata.get(
        "statistics_version"
    ) != BACKGROUND_MODEL_V3_STATISTICS_VERSION:
        model_errors.append("unexpected statistics version")
    missing_arrays = sorted(REQUIRED_ARRAYS - set(model.arrays))
    if missing_arrays:
        model_errors.append(
            "missing arrays: " + ",".join(missing_arrays)
        )
    for name, values in model.arrays.items():
        if tuple(np.asarray(values).shape) != tuple(model.shape):
            model_errors.append(f"{name} shape mismatch")

    source_ids = [
        str(value)
        for value in model.metadata.get("training_source_ids") or ()
    ]
    unknown_sources = sorted(set(source_ids) - set(source_index))
    if unknown_sources:
        model_errors.append(
            f"{len(unknown_sources)} training sources are unknown"
        )
    source_rows = [
        source_index[source_id]
        for source_id in source_ids
        if source_id in source_index
    ]
    nontraining = [
        row
        for row in source_rows
        if str(row.get("split") or "") != "training"
    ]
    if nontraining:
        model_errors.append(
            f"{len(nontraining)} validation/holdout sources leaked"
        )
    dates = sorted(
        {str(row.get("date") or "") for row in source_rows}
    )
    seasons = sorted(
        {str(row.get("season") or "") for row in source_rows}
    )
    time_buckets = sorted(
        {
            str(
                row.get("time_bucket")
                or row.get("utc_slot")
                or ""
            )
            for row in source_rows
        }
    )
    if len(dates) < minimum_distinct_dates:
        model_errors.append(
            f"only {len(dates)} distinct training dates"
        )
    if len(set(seasons) & {"winter", "spring", "summer", "autumn"}) < 4:
        model_errors.append("training does not cover all four seasons")
    if len(set(time_buckets) & {"day", "night"}) < 2:
        model_errors.append("training does not cover day and night")

    eligible = np.zeros(model.shape, dtype=bool)
    if not missing_arrays:
        evidence_config = EvidenceConfig()
        static_p10 = np.asarray(
            model.arrays["low_ci_static_dbzh_p10"],
            dtype="float32",
        )
        static_median = np.asarray(
            model.arrays["low_ci_static_dbzh_median"],
            dtype="float32",
        )
        static_p90 = np.asarray(
            model.arrays["low_ci_static_dbzh_p90"],
            dtype="float32",
        )
        eligible = (
            np.asarray(
                model.arrays[
                    "low_ci_static_echo_date_sample_count"
                ],
                dtype="float32",
            )
            >= float(minimum_distinct_dates)
        )
        eligible &= (
            np.asarray(
                model.arrays[
                    "low_ci_static_echo_date_frequency"
                ],
                dtype="float32",
            )
            >= float(minimum_static_date_frequency)
        )
        eligible &= (
            np.asarray(
                model.arrays[
                    "low_ci_static_echo_season_count"
                ],
                dtype="float32",
            )
            >= 4.0
        )
        eligible &= (
            np.asarray(
                model.arrays[
                    "low_ci_static_echo_time_bucket_count"
                ],
                dtype="float32",
            )
            >= 2.0
        )
        eligible &= (
            np.isfinite(static_p10)
            & np.isfinite(static_median)
            & np.isfinite(static_p90)
            & (static_p10 <= static_median)
            & (static_median <= static_p90)
            & (
                (static_p90 - static_p10)
                <= float(
                    evidence_config
                    .background_static_dbzh_interquantile_range_max_db
                )
            )
        )

    geometry_class = str(
        model.key.get("geometry_class")
        or (
            "vertical"
            if float(model.key.get("elevation_deg") or 0.0) >= 80.0
            else "ppi"
        )
    )
    return {
        "target_id": target_id,
        "radar": str(model.key.get("radar") or ""),
        "pulse": str(model.key.get("pulse") or ""),
        "quantity": str(model.key.get("quantity") or ""),
        "geometry_class": geometry_class,
        "elevation_deg": float(model.key.get("elevation_deg") or 0.0),
        "shape": list(model.shape),
        "training_source_count": len(source_ids),
        "training_date_count": len(dates),
        "training_seasons": seasons,
        "training_time_buckets": time_buckets,
        "statistics_version": model.metadata.get("statistics_version"),
        "training_contract_sha256": str(
            model.metadata.get("training_contract_sha256") or ""
        ),
        "model_array_hash": model.array_hash,
        "eligible_gate_count": int(eligible.sum()),
        "eligible_gate_fraction": float(eligible.mean()),
        "application_eligible": geometry_class == "ppi",
        "errors": model_errors,
    }


def _source_index(*paths: Path) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for path in paths:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for item in manifest.get("files") or ():
            source_id = str(item.get("source_id") or "")
            if not source_id:
                continue
            previous = output.get(source_id)
            if previous is not None and (
                previous.get("object_url") != item.get("object_url")
                or previous.get("split") != item.get("split")
            ):
                raise ValueError(
                    f"source metadata conflict for {source_id}"
                )
            output.setdefault(source_id, item)
    return output


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


if __name__ == "__main__":
    raise SystemExit(main())
