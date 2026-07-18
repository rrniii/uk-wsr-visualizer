"""Blinded review-target selection for the independent UK WSR QC benchmark."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from .dependencies import require_h5py
from .qc import normalized_quantity
from .qc_benchmark import (
    BENCHMARK_ID,
    benchmark_local_path,
    canonical_json_sha256,
    validate_benchmark_manifest,
)

REVIEW_SCHEMA_VERSION = 1
TARGETS_PER_VOLUME = 2
MINIMUM_DOUBLE_REVIEW_FRACTION = 0.20
PRIMARY_VISIBLE_FIELDS = ("DBZH", "VRADH", "SQIH", "RHOHV", "ZDR", "PHIDP", "WRADH")
PRIMARY_HIDDEN_FIELDS = ("CI", "QC_MASK", "QC_SCORE", "BACKGROUND_PROBABILITY")


def discover_review_sweeps(path: str | Path) -> list[dict[str, Any]]:
    """Inspect every DBZH sweep without loading gate arrays."""

    h5py = require_h5py()
    sweeps: list[dict[str, Any]] = []
    with h5py.File(path, "r") as h5:
        for dataset_name in sorted(
            (name for name in h5 if str(name).startswith("dataset")),
            key=_dataset_sort_key,
        ):
            dataset = h5[dataset_name]
            dbzh_shape: list[int] | None = None
            quantities: set[str] = set()
            for name, group in dataset.items():
                if not isinstance(group, h5py.Group) or not str(name).startswith(("data", "quality")):
                    continue
                quantity = normalized_quantity(_group_quantity(group))
                if not quantity:
                    continue
                quantities.add(quantity)
                if quantity == "DBZH" and str(name).startswith("data"):
                    data = group.get("data")
                    if data is not None:
                        dbzh_shape = [int(value) for value in data.shape]
            if dbzh_shape is None:
                continue
            where = dataset.get("where")
            elevation = (
                float(where.attrs["elangle"])
                if where is not None and "elangle" in where.attrs
                else None
            )
            sweeps.append(
                {
                    "dataset": str(dataset_name),
                    "elevation_deg": elevation,
                    "shape": dbzh_shape,
                    "quantities": sorted(quantities),
                }
            )
    return sweeps


def build_review_target_manifest(
    benchmark: dict[str, Any],
    *,
    source_root: str | Path,
    download_ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select two blinded review sweeps per benchmark PVOL."""

    benchmark_errors = validate_benchmark_manifest(benchmark)
    if benchmark_errors:
        raise ValueError("invalid benchmark: " + "; ".join(benchmark_errors))
    ledger_files = (download_ledger or {}).get("files", {})
    targets: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in benchmark.get("files", []):
        grouped[(str(item["radar"]), str(item["pulse"]))].append(item)

    for group in sorted(grouped):
        files = sorted(
            grouped[group],
            key=lambda item: (
                str(item["split"]),
                str(item["date"]),
                str(item["time"]),
                str(item["case_id"]),
            ),
        )
        for file_index, item in enumerate(files):
            source = benchmark_local_path(source_root, item)
            if not source.exists():
                errors.append(
                    {
                        "case_id": item["case_id"],
                        "error": "source_missing",
                        "local_path": str(source),
                    }
                )
                continue
            try:
                sweeps = discover_review_sweeps(source)
            except Exception as exc:  # noqa: BLE001 - record source failures and continue.
                errors.append(
                    {
                        "case_id": item["case_id"],
                        "error": f"{type(exc).__name__}: {exc}",
                        "local_path": str(source),
                    }
                )
                continue
            if len(sweeps) < TARGETS_PER_VOLUME:
                errors.append(
                    {
                        "case_id": item["case_id"],
                        "error": f"insufficient_dbzh_sweeps:{len(sweeps)}",
                        "local_path": str(source),
                    }
                )
                continue
            selected = [
                ("lowest", sweeps[0]),
                ("elevation_coverage", sweeps[1 + file_index % (len(sweeps) - 1)]),
            ]
            ledger_entry = ledger_files.get(str(item["case_id"]), {})
            for priority, sweep in selected:
                target_id = _target_id(str(item["case_id"]), str(sweep["dataset"]))
                targets.append(
                    {
                        "target_id": target_id,
                        "case_id": item["case_id"],
                        "anchor_id": item["anchor_id"],
                        "split": item["split"],
                        "season": item["season"],
                        "utc_slot": item["utc_slot"],
                        "radar": item["radar"],
                        "pulse": item["pulse"],
                        "date": item["date"],
                        "time": item["time"],
                        "quantity": "DBZH",
                        "dataset": sweep["dataset"],
                        "elevation_deg": sweep["elevation_deg"],
                        "shape": sweep["shape"],
                        "available_quantities": sweep["quantities"],
                        "selection_role": priority,
                        "primary_visible_fields": [
                            field
                            for field in PRIMARY_VISIBLE_FIELDS
                            if field in sweep["quantities"]
                        ],
                        "primary_hidden_fields": list(PRIMARY_HIDDEN_FIELDS),
                        "primary_qc_outputs_visible": False,
                        "double_review_required": False,
                        "review_status": "unreviewed",
                        "source_url": item["object_url"],
                        "source_catalog_size_bytes": item["size_bytes"],
                        "source_size_bytes": int(
                            ledger_entry.get("size_bytes") or item["size_bytes"]
                        ),
                        "source_catalog_size_match": ledger_entry.get(
                            "catalog_size_match"
                        ),
                        "source_sha256": ledger_entry.get("sha256"),
                    }
                )

    _assign_double_review(targets)
    targets.sort(
        key=lambda item: (
            item["radar"],
            item["split"],
            item["pulse"],
            item["date"],
            item["time"],
            item["selection_role"],
        )
    )
    return {
        "schema": "uk_wsr_qc_review_targets",
        "schema_version": REVIEW_SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "benchmark_manifest_sha256": canonical_json_sha256(benchmark),
        "generated_at": _now_utc(),
        "source_storage": "external benchmark cache; local paths are not persisted",
        "selection": {
            "targets_per_volume": TARGETS_PER_VOLUME,
            "lowest_sweep_per_volume": True,
            "coverage_sweep": (
                "round-robin over every remaining DBZH elevation within each radar/pulse"
            ),
            "primary_blind_to_qc": True,
            "primary_hidden_fields": list(PRIMARY_HIDDEN_FIELDS),
            "minimum_double_review_fraction": MINIMUM_DOUBLE_REVIEW_FRACTION,
            "double_review_strata": ["radar", "pulse", "split"],
        },
        "expected_target_count": len(benchmark.get("files", [])) * TARGETS_PER_VOLUME,
        "target_count": len(targets),
        "error_count": len(errors),
        "errors": errors,
        "counts": review_target_counts(targets),
        "targets": targets,
    }


def review_target_counts(targets: Iterable[dict[str, Any]]) -> dict[str, Any]:
    entries = list(targets)
    return {
        "by_split": dict(sorted(Counter(str(item["split"]) for item in entries).items())),
        "by_pulse": dict(sorted(Counter(str(item["pulse"]) for item in entries).items())),
        "by_selection_role": dict(
            sorted(Counter(str(item["selection_role"]) for item in entries).items())
        ),
        "by_elevation": dict(
            sorted(
                Counter(
                    f"{float(item['elevation_deg']):.2f}"
                    if item.get("elevation_deg") is not None
                    else "unknown"
                    for item in entries
                ).items()
            )
        ),
        "double_review_count": sum(
            1 for item in entries if item.get("double_review_required")
        ),
    }


def validate_review_target_manifest(
    review: dict[str, Any],
    benchmark: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    targets = list(review.get("targets", []))
    expected = len(benchmark.get("files", [])) * TARGETS_PER_VOLUME
    if review.get("schema") != "uk_wsr_qc_review_targets":
        errors.append("invalid review-target schema")
    if review.get("benchmark_manifest_sha256") != canonical_json_sha256(benchmark):
        errors.append("benchmark manifest hash mismatch")
    if review.get("errors"):
        errors.append(f"review selection contains {len(review['errors'])} errors")
    if len(targets) != expected:
        errors.append(f"target count {len(targets)} != expected {expected}")
    target_ids = [str(item.get("target_id") or "") for item in targets]
    if len(target_ids) != len(set(target_ids)):
        errors.append("target ids are not unique")

    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_stratum: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        by_case[str(target.get("case_id"))].append(target)
        by_stratum[
            (
                str(target.get("radar")),
                str(target.get("pulse")),
                str(target.get("split")),
            )
        ].append(target)
        if target.get("primary_qc_outputs_visible") is not False:
            errors.append(f"{target.get('target_id')}: primary review is not QC-blind")
        if target.get("selection_role") not in {"lowest", "elevation_coverage"}:
            errors.append(f"{target.get('target_id')}: invalid selection role")
        source_sha256 = target.get("source_sha256")
        if source_sha256 is not None and (
            not isinstance(source_sha256, str) or len(source_sha256) != 64
        ):
            errors.append(f"{target.get('target_id')}: invalid source SHA-256")
        if int(target.get("source_size_bytes") or 0) <= 0:
            errors.append(f"{target.get('target_id')}: invalid source size")
        shape = target.get("shape")
        if (
            not isinstance(shape, list)
            or len(shape) != 2
            or any(not isinstance(value, int) or value <= 0 for value in shape)
        ):
            errors.append(f"{target.get('target_id')}: invalid shape")

    benchmark_cases = {str(item["case_id"]) for item in benchmark.get("files", [])}
    if set(by_case) != benchmark_cases:
        errors.append("review targets do not cover every benchmark case")
    for case_id, case_targets in by_case.items():
        roles = {str(item["selection_role"]) for item in case_targets}
        if len(case_targets) != TARGETS_PER_VOLUME or roles != {"lowest", "elevation_coverage"}:
            errors.append(f"{case_id}: expected one lowest and one coverage target")
    for stratum, stratum_targets in by_stratum.items():
        reviewed = sum(
            1 for item in stratum_targets if item.get("double_review_required")
        )
        required = math.ceil(len(stratum_targets) * MINIMUM_DOUBLE_REVIEW_FRACTION)
        if reviewed < required:
            errors.append(f"{stratum}: double-review allocation {reviewed} < {required}")
    return errors


def review_progress_template(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "uk_wsr_qc_review_progress",
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "review_targets_sha256": canonical_json_sha256(review),
        "generated_at": _now_utc(),
        "assignments": [],
        "completed_primary_target_ids": [],
        "completed_secondary_target_ids": [],
        "adjudicated_target_ids": [],
    }


def review_markdown(review: dict[str, Any], validation_errors: list[str]) -> str:
    counts = review.get("counts", {})
    target_count = int(review.get("target_count") or 0)
    double_count = int(counts.get("double_review_count") or 0)
    return f"""# UK WSR QC Blinded Review Targets

Status: **{"ready for review" if not validation_errors else "incomplete"}**

The review workload contains {target_count:,} DBZH sweeps selected from
{target_count // TARGETS_PER_VOLUME:,} independent PVOL files. Every volume
contributes its lowest elevation and one round-robin coverage elevation.

- LP targets: {counts.get('by_pulse', {}).get('lp', 0):,}
- SP targets: {counts.get('by_pulse', {}).get('sp', 0):,}
- Lowest-elevation targets: {counts.get('by_selection_role', {}).get('lowest', 0):,}
- Rotating all-elevation targets: {counts.get('by_selection_role', {}).get('elevation_coverage', 0):,}
- Independently double-reviewed targets: {double_count:,}

Primary reviewers see raw DBZH and available VRADH, SQIH, RHOHV, ZDR, PHIDP,
and WRADH panels. CI and every current/community/learned QC prediction are
hidden during primary review. Ambiguous areas must be labelled `uncertain`
rather than forced into remove or retain.

Validation errors: {len(validation_errors)}.
"""


def write_review_artifacts(
    review: dict[str, Any],
    benchmark: dict[str, Any],
    output_dir: str | Path,
) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    validation_errors = validate_review_target_manifest(review, benchmark)
    (output / "review_targets.json").write_text(
        json.dumps(review, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "review_targets.sha256").write_text(
        f"{canonical_json_sha256(review)}  review_targets.json\n",
        encoding="utf-8",
    )
    (output / "review_progress.template.json").write_text(
        json.dumps(review_progress_template(review), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "REVIEW.md").write_text(
        review_markdown(review, validation_errors),
        encoding="utf-8",
    )
    if validation_errors:
        raise ValueError("; ".join(validation_errors))


def _assign_double_review(targets: list[dict[str, Any]]) -> None:
    strata: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        strata[
            (
                str(target["radar"]),
                str(target["pulse"]),
                str(target["split"]),
            )
        ].append(target)
    for entries in strata.values():
        ordered = sorted(
            entries,
            key=lambda item: sha256(str(item["target_id"]).encode("utf-8")).hexdigest(),
        )
        required = math.ceil(len(ordered) * MINIMUM_DOUBLE_REVIEW_FRACTION)
        for target in ordered[:required]:
            target["double_review_required"] = True


def _target_id(case_id: str, dataset: str) -> str:
    digest = sha256(f"{case_id}|{dataset}".encode("utf-8")).hexdigest()[:16]
    return f"{case_id}-{dataset}-{digest}"


def _dataset_sort_key(name: str) -> tuple[int, str]:
    suffix = str(name).removeprefix("dataset")
    return (int(suffix) if suffix.isdigit() else 10_000, str(name))


def _group_quantity(group: Any) -> str:
    what = group.get("what")
    if what is None or "quantity" not in what.attrs:
        return ""
    value = what.attrs["quantity"]
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value)


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
