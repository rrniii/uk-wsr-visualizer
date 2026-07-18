"""Integrity and invariant audit for real-data background validation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .background_training_pipeline import file_sha256
from .background_validation_pipeline import (
    hash_validation_arrays,
    summarise_background_validation,
)
from .dependencies import require_numpy
from .qc_evidence import EvidenceFlag

BACKGROUND_VALIDATION_AUDIT_SCHEMA = "uk_wsr_background_validation_audit"
BACKGROUND_VALIDATION_AUDIT_SCHEMA_VERSION = 1

_FULL_SHAPE_ARRAYS = (
    "dbzh_raw",
    "dbzh_baseline_cleaned",
    "dbzh_learned_cleaned",
    "baseline_remove_mask",
    "baseline_nuisance_mask",
    "baseline_evidence_mask",
    "baseline_protected_mask",
    "baseline_confidence",
    "learned_remove_mask",
    "learned_nuisance_mask",
    "learned_evidence_mask",
    "learned_protected_mask",
    "learned_confidence",
    "learned_increment_mask",
)
_PROFILE_ARRAYS = (
    "baseline_noise_profile",
    "learned_noise_profile",
)
_BINARY_ARRAYS = (
    "baseline_remove_mask",
    "baseline_protected_mask",
    "learned_remove_mask",
    "learned_protected_mask",
    "learned_increment_mask",
)


def audit_background_validation_run(
    results_path: str | Path,
) -> dict[str, Any]:
    """Verify validation completion, provenance, arrays, and mask invariants."""

    source = Path(results_path)
    report = json.loads(source.read_text(encoding="utf-8"))
    records = list(report.get("records") or [])
    errors: list[dict[str, str]] = []

    expected_count = int(report.get("expected_job_count", -1))
    if report.get("split") not in {"validation", "holdout"}:
        _error(errors, "run", "split is not validation or holdout")
    if report.get("complete") is not True:
        _error(errors, "run", "validation report is not complete")
    if int(report.get("error_count", -1)) != 0 or report.get("errors"):
        _error(errors, "run", "validation report contains errors")
    if expected_count != len(records):
        _error(errors, "run", "validation record count is incomplete")
    if int(report.get("scored_job_count", -1)) != len(records):
        _error(errors, "run", "scored_job_count is inconsistent")
    if report.get("all_jobs_attempted") is not True:
        _error(errors, "run", "not all validation jobs were attempted")
    if int(report.get("promotion_eligible_model_count", -1)) != 0:
        _error(errors, "run", "unreviewed models are promotion eligible")

    configuration = report.get("configuration")
    configuration_hash = str(report.get("configuration_sha256") or "")
    if not isinstance(configuration, dict):
        _error(errors, "run", "validation configuration is missing")
    elif _hash_json(configuration) != configuration_hash:
        _error(errors, "run", "validation configuration hash does not verify")

    job_ids = [str(record.get("job_id") or "") for record in records]
    if not all(job_ids) or len(job_ids) != len(set(job_ids)):
        _error(errors, "run", "validation job ids are missing or duplicated")
    artifact_root = Path(str(report.get("artifact_root") or "")).resolve()

    audited_records: list[dict[str, Any]] = []
    artifact_size_bytes = 0
    for record in records:
        job_id = str(record.get("job_id") or "unknown")
        record_errors: list[str] = []
        if record.get("configuration_sha256") != configuration_hash:
            record_errors.append("record configuration hash mismatch")
        if record.get("promotion_eligible") is not False:
            record_errors.append("record is promotion eligible")
        if record.get("model", {}).get("promotion_eligible") is not False:
            record_errors.append("model is promotion eligible")

        npz_path = Path(str(record.get("artifact_npz") or "")).resolve()
        sidecar_path = Path(
            str(record.get("artifact_sidecar") or "")
        ).resolve()
        if not _is_within(npz_path, artifact_root):
            record_errors.append("artifact is outside declared root")
        if not _is_within(sidecar_path, artifact_root):
            record_errors.append("sidecar is outside declared root")

        sidecar: dict[str, Any] | None = None
        if not sidecar_path.is_file():
            record_errors.append("artifact sidecar is missing")
        else:
            try:
                sidecar = json.loads(
                    sidecar_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                record_errors.append(
                    f"artifact sidecar is unreadable: {type(exc).__name__}"
                )
        if not npz_path.is_file():
            record_errors.append("artifact NPZ is missing")

        arrays: dict[str, Any] | None = None
        if sidecar is not None and npz_path.is_file():
            _audit_sidecar(
                record,
                report,
                sidecar,
                npz_path,
                record_errors,
            )
            try:
                np = require_numpy()
                with np.load(npz_path, allow_pickle=False) as loaded:
                    arrays = {
                        name: loaded[name]
                        for name in loaded.files
                    }
            except (OSError, ValueError) as exc:
                record_errors.append(
                    f"artifact NPZ is unreadable: {type(exc).__name__}"
                )
            if arrays is not None:
                _audit_arrays(record, arrays, sidecar, record_errors)
            artifact_size_bytes += (
                npz_path.stat().st_size + sidecar_path.stat().st_size
            )

        for message in record_errors:
            _error(errors, job_id, message)
        audited_records.append(
            {
                "job_id": job_id,
                "target_id": record.get("target_id"),
                "radar": record.get("radar"),
                "pulse": record.get("pulse"),
                "elevation_deg": record.get("elevation_deg"),
                "status": "passed" if not record_errors else "failed",
                "errors": record_errors,
            }
        )

    if not errors:
        recomputed_summary = summarise_background_validation(records)
        if report.get("summary") != recomputed_summary:
            _error(errors, "run", "validation summary does not recompute")

    passed = sum(row["status"] == "passed" for row in audited_records)
    return {
        "schema": BACKGROUND_VALIDATION_AUDIT_SCHEMA,
        "schema_version": BACKGROUND_VALIDATION_AUDIT_SCHEMA_VERSION,
        "generated_at": _now_utc(),
        "status": "passed" if not errors else "failed",
        "results": str(source),
        "results_sha256": file_sha256(source),
        "split": report.get("split"),
        "configuration_sha256": configuration_hash,
        "expected_record_count": expected_count,
        "audited_record_count": len(audited_records),
        "passed_record_count": passed,
        "failed_record_count": len(audited_records) - passed,
        "target_count": len(
            {record.get("target_id") for record in records}
        ),
        "radar_count": len({record.get("radar") for record in records}),
        "pulse_record_counts": dict(
            sorted(
                Counter(str(record.get("pulse")) for record in records).items()
            )
        ),
        "artifact_size_bytes": artifact_size_bytes,
        "error_count": len(errors),
        "promotion_eligible_model_count": 0,
        "record_audits": audited_records,
        "errors": errors,
    }


def write_background_validation_audit(
    audit: dict[str, Any],
    path: str | Path,
) -> Path:
    """Write an audit atomically."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(audit, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def _audit_sidecar(
    record: dict[str, Any],
    report: dict[str, Any],
    sidecar: dict[str, Any],
    npz_path: Path,
    errors: list[str],
) -> None:
    if sidecar.get("schema") != "uk_wsr_background_validation_artifact":
        errors.append("artifact sidecar schema is invalid")
    if sidecar.get("configuration") != report.get("configuration"):
        errors.append("artifact configuration does not match report")
    sidecar_record = sidecar.get("record")
    if not isinstance(sidecar_record, dict):
        errors.append("artifact sidecar record is missing")
    else:
        for key, value in sidecar_record.items():
            if record.get(key) != value:
                errors.append(f"sidecar record mismatch at {key}")
                break
    if str(sidecar.get("npz_path") or "") != npz_path.name:
        errors.append("sidecar NPZ filename does not match artifact")
    actual_hash = file_sha256(npz_path)
    expected_hashes = {
        str(sidecar.get("artifact_sha256") or ""),
        str(record.get("artifact_sha256") or ""),
    }
    if "" in expected_hashes or expected_hashes != {actual_hash}:
        errors.append("artifact file hash does not verify")


def _audit_arrays(
    record: dict[str, Any],
    arrays: dict[str, Any],
    sidecar: dict[str, Any],
    errors: list[str],
) -> None:
    np = require_numpy()
    required = set(_FULL_SHAPE_ARRAYS) | set(_PROFILE_ARRAYS)
    if set(arrays) != required:
        missing = sorted(required - set(arrays))
        unexpected = sorted(set(arrays) - required)
        if missing:
            errors.append("missing arrays: " + ",".join(missing))
        if unexpected:
            errors.append("unexpected arrays: " + ",".join(unexpected))
    expected_shape = tuple(int(value) for value in record.get("shape") or ())
    for name in _FULL_SHAPE_ARRAYS:
        if name in arrays and tuple(np.asarray(arrays[name]).shape) != expected_shape:
            errors.append(f"{name} shape does not match record")
    for name in _PROFILE_ARRAYS:
        if name in arrays and tuple(np.asarray(arrays[name]).shape) != (
            expected_shape[1:2]
        ):
            errors.append(f"{name} shape does not match gate count")
    for name in _BINARY_ARRAYS:
        if name in arrays and not np.isin(arrays[name], (0, 1)).all():
            errors.append(f"{name} is not binary")

    if hash_validation_arrays(arrays) != sidecar.get("array_hash"):
        errors.append("artifact array hash does not verify")
    if sidecar.get("array_hash") != record.get("artifact_array_hash"):
        errors.append("record array hash does not match sidecar")

    descriptors = sidecar.get("arrays") or {}
    for name, values in arrays.items():
        descriptor = descriptors.get(name) or {}
        if descriptor.get("dtype") != str(np.asarray(values).dtype):
            errors.append(f"{name} dtype descriptor does not verify")
        if descriptor.get("shape") != list(np.asarray(values).shape):
            errors.append(f"{name} shape descriptor does not verify")

    baseline = np.asarray(
        arrays.get("baseline_remove_mask", []),
        dtype=bool,
    )
    learned = np.asarray(
        arrays.get("learned_remove_mask", []),
        dtype=bool,
    )
    increment = np.asarray(
        arrays.get("learned_increment_mask", []),
        dtype=bool,
    )
    if (
        baseline.shape == expected_shape
        and learned.shape == expected_shape
        and increment.shape == expected_shape
    ):
        if not np.array_equal(increment, learned & ~baseline):
            errors.append("learned increment mask does not recompute")
        _audit_candidate(
            "baseline",
            arrays,
            expected_shape,
            errors,
        )
        _audit_candidate(
            "learned",
            arrays,
            expected_shape,
            errors,
        )
        rescue = int((baseline & ~learned).sum())
        disagreement = int((baseline ^ learned).sum())
        delta = record.get("delta") or {}
        if rescue != int(delta.get("learned_rescue_count", -1)):
            errors.append("learned rescue count does not verify")
        if disagreement != int(delta.get("mask_disagreement_count", -1)):
            errors.append("mask disagreement count does not verify")
        if int(increment.sum()) != int(
            delta.get("learned_increment_count", -1)
        ):
            errors.append("learned increment count does not verify")
        context = record.get("context") or {}
        if (
            context.get("upper_elevation_expected") is True
            and context.get("upper_elevation_available") is False
            and increment.any()
        ):
            errors.append(
                "learned clutter did not fail open without expected upper "
                "context"
            )


def _audit_candidate(
    prefix: str,
    arrays: dict[str, Any],
    expected_shape: tuple[int, ...],
    errors: list[str],
) -> None:
    np = require_numpy()
    remove = np.asarray(arrays[f"{prefix}_remove_mask"], dtype=bool)
    protected = np.asarray(
        arrays[f"{prefix}_protected_mask"],
        dtype=bool,
    )
    nuisance = np.asarray(arrays[f"{prefix}_nuisance_mask"])
    raw = np.asarray(arrays["dbzh_raw"], dtype="float32")
    cleaned = np.asarray(
        arrays[f"dbzh_{prefix}_cleaned"],
        dtype="float32",
    )
    if (
        remove.shape != expected_shape
        or protected.shape != expected_shape
        or nuisance.shape != expected_shape
    ):
        return
    if (remove & protected).any():
        errors.append(f"{prefix} removed protected gates")
    if not np.array_equal(remove, nuisance != 0):
        errors.append(f"{prefix} nuisance mask does not match removals")
    expected_cleaned = np.where(remove, np.nan, raw)
    if not np.array_equal(cleaned, expected_cleaned, equal_nan=True):
        errors.append(f"{prefix} cleaned DBZH does not match mask")
    evidence = np.asarray(
        arrays[f"{prefix}_evidence_mask"],
        dtype="uint32",
    )
    upper = (evidence & int(EvidenceFlag.UPPER_ELEVATION_SUPPORT)) != 0
    if (remove & upper).any():
        errors.append(f"{prefix} removed upper-supported gates")


def _hash_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _error(errors: list[dict[str, str]], item: str, message: str) -> None:
    errors.append({"item": item, "error": message})


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
