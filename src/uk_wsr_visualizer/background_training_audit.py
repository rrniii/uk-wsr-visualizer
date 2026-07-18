"""Integrity audit for learned-background research artifacts."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .background_model import (
    BACKGROUND_MODEL_ARRAY_NAMES,
    hash_arrays,
    load_background_model,
)
from .dependencies import require_numpy

BACKGROUND_TRAINING_AUDIT_SCHEMA = "uk_wsr_background_training_audit"
BACKGROUND_TRAINING_AUDIT_SCHEMA_VERSION = 1
DEFAULT_CONDITIONED_SUPPORT_COUNT = 12

_COUNT_ARRAY_NAMES = tuple(
    name
    for name in BACKGROUND_MODEL_ARRAY_NAMES
    if name.endswith("_count")
)
_FREQUENCY_ARRAY_NAMES = tuple(
    name
    for name in BACKGROUND_MODEL_ARRAY_NAMES
    if name.endswith("_frequency")
)
_PERCENTILE_ARRAY_NAMES = ("dbzh_p10", "dbzh_median", "dbzh_p90")


def audit_background_training_run(
    inventory_path: str | Path,
    training_results_path: str | Path,
    *,
    model_dir: str | Path | None = None,
    conditioned_support_count: int = DEFAULT_CONDITIONED_SUPPORT_COUNT,
) -> dict[str, Any]:
    """Verify every trained model against its corpus and geometry contract."""

    np = require_numpy()
    inventory_source = Path(inventory_path)
    results_source = Path(training_results_path)
    inventory = json.loads(inventory_source.read_text(encoding="utf-8"))
    results = json.loads(results_source.read_text(encoding="utf-8"))
    resolved_model_dir = Path(
        model_dir if model_dir is not None else results.get("model_dir", "")
    )

    errors: list[dict[str, str]] = []
    inventory_targets = _unique_by_target_id(
        inventory.get("targets", []),
        source="inventory",
        errors=errors,
    )
    result_models = _unique_by_target_id(
        results.get("models", []),
        source="training results",
        errors=errors,
    )
    expected_ids = set(inventory_targets)
    result_ids = set(result_models)
    for target_id in sorted(expected_ids - result_ids):
        _error(errors, target_id, "missing from training results")
    for target_id in sorted(result_ids - expected_ids):
        _error(errors, target_id, "not present in training inventory")

    if inventory.get("source_manifest_sha256") != results.get(
        "source_manifest_sha256"
    ):
        _error(errors, "run", "source manifest hashes do not match")
    if inventory.get("download_ledger_sha256") != results.get(
        "download_ledger_sha256"
    ):
        _error(errors, "run", "download ledger hashes do not match")
    if int(inventory.get("target_count", -1)) != len(inventory_targets):
        _error(errors, "run", "inventory target_count is inconsistent")
    if int(results.get("target_count", -1)) != len(result_models):
        _error(errors, "run", "training target_count is inconsistent")
    if int(results.get("error_count", -1)) != 0 or results.get("errors"):
        _error(errors, "run", "training report contains errors")
    if results.get("complete") is not True:
        _error(errors, "run", "training report is not complete")

    model_audits: list[dict[str, Any]] = []
    companion_target_counts: Counter[str] = Counter()
    artifact_size_bytes = 0
    for target_id in sorted(expected_ids & result_ids):
        target = inventory_targets[target_id]
        summary = result_models[target_id]
        target_errors: list[str] = []
        json_path = resolved_model_dir / f"{target_id}.json"
        npz_path = resolved_model_dir / f"{target_id}.npz"
        if not json_path.is_file():
            target_errors.append(f"missing model JSON: {json_path}")
        if not npz_path.is_file():
            target_errors.append(f"missing model NPZ: {npz_path}")

        model = None
        manifest: dict[str, Any] = {}
        if not target_errors:
            try:
                manifest = json.loads(json_path.read_text(encoding="utf-8"))
                model = load_background_model(json_path)
            except Exception as exc:  # noqa: BLE001 - audit records all failures.
                target_errors.append(
                    f"model load failed: {type(exc).__name__}: {exc}"
                )

        support_fraction = None
        if model is not None:
            expected_shape = tuple(int(value) for value in target["shape"])
            if tuple(model.shape) != expected_shape:
                target_errors.append(
                    f"shape {model.shape} != inventory {expected_shape}"
                )
            manifest_arrays = set((manifest.get("arrays") or {}).keys())
            missing_arrays = sorted(
                set(BACKGROUND_MODEL_ARRAY_NAMES) - set(model.arrays)
            )
            missing_descriptors = sorted(
                set(BACKGROUND_MODEL_ARRAY_NAMES) - manifest_arrays
            )
            if missing_arrays:
                target_errors.append(
                    "missing model arrays: " + ",".join(missing_arrays)
                )
            if missing_descriptors:
                target_errors.append(
                    "missing array descriptors: "
                    + ",".join(missing_descriptors)
                )

            for name, values in model.arrays.items():
                if tuple(np.asarray(values).shape) != expected_shape:
                    target_errors.append(
                        f"{name} shape does not match {expected_shape}"
                    )

            computed_hash = hash_arrays(model.arrays)
            if manifest.get("array_hash") != computed_hash:
                target_errors.append("manifest array hash does not verify")
            if summary.get("model_array_hash") != computed_hash:
                target_errors.append(
                    "training summary array hash does not verify"
                )

            metadata = model.metadata
            key = model.key
            _check_equal(
                target_errors,
                "source manifest hash",
                metadata.get("source_manifest_sha256"),
                results.get("source_manifest_sha256"),
            )
            _check_equal(
                target_errors,
                "download ledger hash",
                metadata.get("download_ledger_sha256"),
                results.get("download_ledger_sha256"),
            )
            _check_equal(
                target_errors,
                "geometry id",
                key.get("geometry_id"),
                target_id,
            )
            for name in ("radar", "pulse", "quantity"):
                _check_equal(
                    target_errors,
                    name,
                    key.get(name),
                    target.get(name),
                )
            for name in ("nrays", "nbins"):
                expected = expected_shape[0 if name == "nrays" else 1]
                _check_equal(target_errors, name, key.get(name), expected)
            _check_close(
                target_errors,
                "elevation",
                key.get("elevation_deg"),
                target.get("elevation_deg"),
                tolerance=0.075,
            )
            _check_close(
                target_errors,
                "range start",
                key.get("rstart_km"),
                target.get("rstart_km"),
                tolerance=1e-6,
            )
            _check_close(
                target_errors,
                "range scale",
                key.get("rscale_m"),
                target.get("rscale_m"),
                tolerance=1e-3,
            )
            if sorted(key.get("dataset_aliases") or []) != sorted(
                target.get("dataset_aliases") or []
            ):
                target_errors.append("dataset aliases do not match inventory")

            source_counts = target.get("source_counts") or {}
            date_counts = target.get("date_counts") or {}
            training_count = int(source_counts.get("training", 0))
            training_dates = list(metadata.get("source_dates") or [])
            _check_equal(
                target_errors,
                "training source count",
                metadata.get("source_count"),
                training_count,
            )
            _check_equal(
                target_errors,
                "training date count",
                metadata.get("source_date_count"),
                int(date_counts.get("training", 0)),
            )
            if len(set(training_dates)) != len(training_dates):
                target_errors.append("training dates are not unique")
            if len(training_dates) != int(date_counts.get("training", 0)):
                target_errors.append(
                    "training date list does not match inventory"
                )
            if metadata.get("split_source_counts") != source_counts:
                target_errors.append("split source counts do not match")
            source_ids = list(metadata.get("training_source_ids") or [])
            source_hashes = list(
                metadata.get("training_source_sha256") or []
            )
            if len(source_ids) != training_count:
                target_errors.append("training source id count does not match")
            if len(set(source_ids)) != len(source_ids):
                target_errors.append("training source ids are not unique")
            if len(source_hashes) != training_count:
                target_errors.append(
                    "training source hash count does not match"
                )
            if metadata.get("promotion_eligible") is not False:
                target_errors.append(
                    "unvalidated research model is promotion eligible"
                )
            if summary.get("promotion_eligible") is not False:
                target_errors.append(
                    "training summary marks model promotion eligible"
                )

            if not missing_arrays:
                _audit_array_values(
                    model.arrays,
                    training_count=training_count,
                    errors=target_errors,
                )
                conditioned_count = np.minimum(
                    np.asarray(
                        model.arrays["low_ci_sample_count"],
                        dtype="float32",
                    ),
                    np.asarray(
                        model.arrays["low_ci_vrad_sample_count"],
                        dtype="float32",
                    ),
                )
                support_fraction = float(
                    (conditioned_count >= conditioned_support_count).mean()
                )
                reported_fraction = summary.get(
                    "conditioned_support_gate_fraction"
                )
                if (
                    reported_fraction is None
                    or abs(float(reported_fraction) - support_fraction) > 1e-9
                ):
                    target_errors.append(
                        "conditioned support fraction does not verify"
                    )

            for quantity, count in (
                metadata.get("companion_coverage") or {}
            ).items():
                if int(count) > 0:
                    companion_target_counts[str(quantity)] += 1

        if json_path.is_file():
            artifact_size_bytes += json_path.stat().st_size
        if npz_path.is_file():
            artifact_size_bytes += npz_path.stat().st_size
        for message in target_errors:
            _error(errors, target_id, message)
        model_audits.append(
            {
                "target_id": target_id,
                "radar": target.get("radar"),
                "pulse": target.get("pulse"),
                "elevation_deg": target.get("elevation_deg"),
                "geometry_class": _geometry_class(target),
                "conditioned_support_gate_fraction": support_fraction,
                "status": "passed" if not target_errors else "failed",
                "errors": target_errors,
            }
        )

    geometry_summaries = {
        geometry: _support_summary(
            [
                item["conditioned_support_gate_fraction"]
                for item in model_audits
                if item["geometry_class"] == geometry
                and item["conditioned_support_gate_fraction"] is not None
            ]
        )
        for geometry in ("ppi", "vertical")
    }
    radar_counts = Counter(
        str(item.get("radar")) for item in model_audits
    )
    pulse_counts = Counter(
        str(item.get("pulse")) for item in model_audits
    )
    passed_count = sum(item["status"] == "passed" for item in model_audits)
    return {
        "schema": BACKGROUND_TRAINING_AUDIT_SCHEMA,
        "schema_version": BACKGROUND_TRAINING_AUDIT_SCHEMA_VERSION,
        "generated_at": _now_utc(),
        "status": "passed" if not errors else "failed",
        "inventory": str(inventory_source),
        "training_results": str(results_source),
        "model_dir": str(resolved_model_dir),
        "source_manifest_sha256": results.get("source_manifest_sha256"),
        "download_ledger_sha256": results.get(
            "download_ledger_sha256"
        ),
        "expected_model_count": len(inventory_targets),
        "audited_model_count": len(model_audits),
        "passed_model_count": passed_count,
        "failed_model_count": len(model_audits) - passed_count,
        "error_count": len(errors),
        "promotion_eligible_model_count": 0,
        "artifact_file_count": sum(
            1
            for suffix in ("json", "npz")
            for _ in resolved_model_dir.glob(f"*.{suffix}")
        ),
        "artifact_size_bytes": artifact_size_bytes,
        "radar_count": len(radar_counts),
        "radar_target_counts": dict(sorted(radar_counts.items())),
        "pulse_target_counts": dict(sorted(pulse_counts.items())),
        "conditioned_support_count": conditioned_support_count,
        "conditioned_support_by_geometry": geometry_summaries,
        "companion_target_counts": dict(
            sorted(companion_target_counts.items())
        ),
        "model_audits": model_audits,
        "errors": errors,
    }


def write_background_training_audit(
    audit: dict[str, Any],
    path: str | Path,
) -> Path:
    """Write an audit atomically so interrupted runs cannot appear complete."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def _audit_array_values(
    arrays: dict[str, Any],
    *,
    training_count: int,
    errors: list[str],
) -> None:
    np = require_numpy()
    for name in _COUNT_ARRAY_NAMES:
        values = np.asarray(arrays[name], dtype="float32")
        if not np.isfinite(values).all():
            errors.append(f"{name} contains non-finite counts")
        if (values < 0).any() or (values > training_count).any():
            errors.append(f"{name} is outside [0, {training_count}]")
        if not np.allclose(values, np.rint(values), atol=1e-6):
            errors.append(f"{name} contains non-integral counts")

    for name in _FREQUENCY_ARRAY_NAMES:
        values = np.asarray(arrays[name], dtype="float32")
        if not np.isfinite(values).all():
            errors.append(f"{name} contains non-finite frequencies")
        if (values < 0).any() or (values > 1).any():
            errors.append(f"{name} is outside [0, 1]")

    sample_count = np.asarray(arrays["sample_count"], dtype="float32")
    for name in (
        "vrad_sample_count",
        "sqi_sample_count",
        "rhohv_sample_count",
        "zdr_sample_count",
        "ci_sample_count",
        "low_ci_sample_count",
        "low_ci_vrad_sample_count",
    ):
        if (np.asarray(arrays[name], dtype="float32") > sample_count).any():
            errors.append(f"{name} exceeds sample_count")
    if (
        np.asarray(arrays["low_ci_sample_count"], dtype="float32")
        > np.asarray(arrays["ci_sample_count"], dtype="float32")
    ).any():
        errors.append("low_ci_sample_count exceeds ci_sample_count")
    low_ci_vrad = np.asarray(
        arrays["low_ci_vrad_sample_count"],
        dtype="float32",
    )
    if (
        low_ci_vrad
        > np.asarray(arrays["low_ci_sample_count"], dtype="float32")
    ).any():
        errors.append(
            "low_ci_vrad_sample_count exceeds low_ci_sample_count"
        )
    if (
        low_ci_vrad
        > np.asarray(arrays["vrad_sample_count"], dtype="float32")
    ).any():
        errors.append("low_ci_vrad_sample_count exceeds vrad_sample_count")

    p10, median, p90 = (
        np.asarray(arrays[name], dtype="float32")
        for name in _PERCENTILE_ARRAY_NAMES
    )
    finite = np.isfinite(p10) & np.isfinite(median) & np.isfinite(p90)
    if ((p10 > median) & finite).any() or ((median > p90) & finite).any():
        errors.append("DBZH percentiles are not monotonic")
    populated = sample_count > 0
    if (
        (~np.isfinite(p10) | ~np.isfinite(median) | ~np.isfinite(p90))
        & populated
    ).any():
        errors.append("populated gates have non-finite DBZH percentiles")


def _unique_by_target_id(
    items: Any,
    *,
    source: str,
    errors: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        _error(errors, "run", f"{source} target list is missing")
        return indexed
    for item in items:
        if not isinstance(item, dict) or not item.get("target_id"):
            _error(errors, "run", f"{source} contains an invalid target")
            continue
        target_id = str(item["target_id"])
        if target_id in indexed:
            _error(errors, target_id, f"duplicate in {source}")
            continue
        indexed[target_id] = item
    return indexed


def _geometry_class(target: dict[str, Any]) -> str:
    return (
        "vertical"
        if float(target.get("elevation_deg") or 0.0) >= 80.0
        else "ppi"
    )


def _support_summary(values: list[float]) -> dict[str, Any]:
    np = require_numpy()
    if not values:
        return {
            "target_count": 0,
            "minimum": None,
            "p10": None,
            "median": None,
            "p90": None,
            "maximum": None,
        }
    array = np.asarray(values, dtype="float64")
    return {
        "target_count": len(values),
        "minimum": float(array.min()),
        "p10": float(np.percentile(array, 10)),
        "median": float(np.median(array)),
        "p90": float(np.percentile(array, 90)),
        "maximum": float(array.max()),
    }


def _check_equal(
    errors: list[str],
    name: str,
    actual: Any,
    expected: Any,
) -> None:
    if actual != expected:
        errors.append(f"{name} {actual!r} != {expected!r}")


def _check_close(
    errors: list[str],
    name: str,
    actual: Any,
    expected: Any,
    *,
    tolerance: float,
) -> None:
    try:
        close = abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        close = False
    if not close:
        errors.append(f"{name} {actual!r} != {expected!r}")


def _error(
    errors: list[dict[str, str]],
    target_id: str,
    message: str,
) -> None:
    errors.append({"target_id": target_id, "error": message})


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
