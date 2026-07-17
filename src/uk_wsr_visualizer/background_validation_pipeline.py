"""Leakage-controlled validation of learned backgrounds on real UK WSR data."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .background_model import BackgroundModel
from .background_training_pipeline import (
    DEFAULT_ELEVATION_TOLERANCE_DEG,
    BackgroundTrainingTarget,
    SweepDescriptor,
    file_sha256,
)
from .dependencies import require_numpy
from .export_types import FieldSelection
from .geospatial import read_polar_field_with_companions
from .qc_evidence import (
    EVIDENCE_VERSION,
    EvidenceConfig,
    EvidenceContext,
    EvidenceFlag,
    EvidenceResult,
    NuisanceFlag,
    classify_nuisance_echoes,
)

BACKGROUND_VALIDATION_SCHEMA = "uk_wsr_background_validation"
BACKGROUND_VALIDATION_SCHEMA_VERSION = 1
DEFAULT_TEMPORAL_GAP_MINUTES = 20
_REMOVAL_THRESHOLDS_DBZ = (0.0, 5.0, 10.0, 15.0, 20.0, 30.0)


@dataclass(frozen=True)
class BackgroundValidationJob:
    """One validation sweep and independently selected context."""

    target: BackgroundTrainingTarget
    sweep: SweepDescriptor
    split: str
    upper_elevation_expected: bool = False
    upper_sweep: SweepDescriptor | None = None
    previous_sweep: SweepDescriptor | None = None
    next_sweep: SweepDescriptor | None = None

    @property
    def job_id(self) -> str:
        return f"{self.target.target_id}__{self.sweep.source_id}"


@dataclass(frozen=True)
class BackgroundValidationEvaluation:
    """Exact candidate results and the serialisable sweep record."""

    record: dict[str, Any]
    arrays: dict[str, Any]


def build_background_validation_jobs(
    targets: Iterable[BackgroundTrainingTarget],
    *,
    split: str,
    max_temporal_gap_minutes: int = DEFAULT_TEMPORAL_GAP_MINUTES,
) -> tuple[BackgroundValidationJob, ...]:
    """Build validation jobs without borrowing context across data splits."""

    if split not in {"validation", "holdout"}:
        raise ValueError("split must be validation or holdout")
    target_list = list(targets)
    source_index: dict[str, list[tuple[BackgroundTrainingTarget, SweepDescriptor]]] = {}
    for target in target_list:
        for sweep in target.split_sweeps(split):
            source_index.setdefault(sweep.source_id, []).append(
                (target, sweep)
            )

    jobs: list[BackgroundValidationJob] = []
    for target in target_list:
        upper_expected = _has_upper_target(target, target_list)
        split_sweeps = sorted(
            target.split_sweeps(split),
            key=_sweep_datetime,
        )
        for index, sweep in enumerate(split_sweeps):
            previous = (
                split_sweeps[index - 1]
                if index > 0
                and _minutes_between(
                    split_sweeps[index - 1],
                    sweep,
                )
                <= max_temporal_gap_minutes
                else None
            )
            following = (
                split_sweeps[index + 1]
                if index + 1 < len(split_sweeps)
                and _minutes_between(
                    sweep,
                    split_sweeps[index + 1],
                )
                <= max_temporal_gap_minutes
                else None
            )
            upper = _select_upper_sweep(
                target,
                source_index.get(sweep.source_id, []),
            )
            jobs.append(
                BackgroundValidationJob(
                    target=target,
                    sweep=sweep,
                    split=split,
                    upper_elevation_expected=upper_expected,
                    upper_sweep=upper,
                    previous_sweep=previous,
                    next_sweep=following,
                )
            )
    return tuple(
        sorted(
            jobs,
            key=lambda job: (
                job.sweep.source_id,
                job.target.elevation_deg,
                job.target.target_id,
            ),
        )
    )


def validation_configuration_contract(
    config: EvidenceConfig,
    *,
    max_temporal_gap_minutes: int,
) -> tuple[dict[str, Any], str]:
    """Return the frozen decision contract and its deterministic hash."""

    contract = {
        "schema": "uk_wsr_background_validation_configuration",
        "schema_version": 1,
        "evidence_version": EVIDENCE_VERSION,
        "evidence_config": asdict(config),
        "context_policy": {
            "companion_fields": "all_matching_fields_in_selected_dataset",
            "learned_persistence_array": (
                "low_ci_persistent_echo_frequency"
            ),
            "learned_static_velocity_array": (
                "low_ci_near_zero_vrad_frequency"
            ),
            "learned_conditioned_support": (
                "min(low_ci_sample_count,low_ci_vrad_sample_count)"
            ),
            "learned_dbzh_ceiling_array": "dbzh_p90",
            "upper_elevation": (
                "nearest_higher_same-source PPI with exact range geometry"
            ),
            "missing_expected_upper_elevation": (
                "learned clutter and anomalous propagation fail open"
            ),
            "temporal": (
                "same-target same-split neighbours within configured gap"
            ),
            "max_temporal_gap_minutes": int(
                max_temporal_gap_minutes
            ),
            "missing_context": "fail_open",
        },
    }
    encoded = json.dumps(
        contract,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return contract, hashlib.sha256(encoded).hexdigest()


def evaluate_background_validation_job(
    job: BackgroundValidationJob,
    model: BackgroundModel,
    *,
    config: EvidenceConfig,
    configuration_sha256: str,
) -> BackgroundValidationEvaluation:
    """Evaluate baseline and learned candidates and retain exact decisions."""

    np = require_numpy()
    if model.key.get("geometry_id") != job.target.target_id:
        raise ValueError("background model does not match validation target")
    if tuple(model.shape) != job.target.shape:
        raise ValueError("background model shape does not match target")

    values, metadata, companions = _read_sweep(
        job.sweep,
        job.target,
        require_target_elevation=True,
    )
    upper = (
        _read_context_dbzh(job.upper_sweep, job.target)
        if job.upper_sweep is not None
        else None
    )
    previous = (
        _read_context_dbzh(job.previous_sweep, job.target)
        if job.previous_sweep is not None
        else None
    )
    following = (
        _read_context_dbzh(job.next_sweep, job.target)
        if job.next_sweep is not None
        else None
    )
    common_context = {
        "previous_dbzh": previous,
        "next_dbzh": following,
        "upper_elevation_dbzh": upper,
        "upper_elevation_required": job.upper_elevation_expected,
    }
    baseline = classify_nuisance_echoes(
        values,
        companions,
        pulse=job.target.pulse,
        config=config,
        context=EvidenceContext(**common_context),
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
    learned = classify_nuisance_echoes(
        values,
        companions,
        pulse=job.target.pulse,
        config=config,
        context=EvidenceContext(
            **common_context,
            background_persistent_frequency=model.arrays[
                "low_ci_persistent_echo_frequency"
            ],
            background_near_zero_vrad_frequency=model.arrays[
                "low_ci_near_zero_vrad_frequency"
            ],
            background_conditioned_sample_count=conditioned_count,
            background_dbzh_p90=model.arrays["dbzh_p90"],
        ),
    )
    baseline_remove = np.asarray(baseline.remove_mask, dtype=bool)
    learned_remove = np.asarray(learned.remove_mask, dtype=bool)
    learned_increment = learned_remove & ~baseline_remove
    learned_rescue = baseline_remove & ~learned_remove

    record = {
        "schema": BACKGROUND_VALIDATION_SCHEMA,
        "schema_version": BACKGROUND_VALIDATION_SCHEMA_VERSION,
        "job_id": job.job_id,
        "split": job.split,
        "target_id": job.target.target_id,
        "radar": job.target.radar,
        "pulse": job.target.pulse,
        "quantity": job.target.quantity,
        "geometry_class": _geometry_class(job.target),
        "elevation_deg": job.target.elevation_deg,
        "shape": list(job.target.shape),
        "rstart_km": job.target.rstart_km,
        "rscale_m": job.target.rscale_m,
        "dataset_aliases": list(job.target.dataset_aliases),
        "source": {
            "source_id": job.sweep.source_id,
            "sha256": job.sweep.sha256,
            "date": job.sweep.date,
            "time": job.sweep.time,
            "dataset": job.sweep.dataset,
            "field_group": job.sweep.field_group,
        },
        "model": {
            "array_hash": model.array_hash,
            "geometry_id": model.key.get("geometry_id"),
            "source_manifest_sha256": model.metadata.get(
                "source_manifest_sha256"
            ),
            "download_ledger_sha256": model.metadata.get(
                "download_ledger_sha256"
            ),
            "promotion_eligible": False,
        },
        "configuration_sha256": configuration_sha256,
        "companions": sorted(companions),
        "context": {
            "upper_elevation": _context_sweep_record(
                job.upper_sweep
            ),
            "previous": _context_sweep_record(job.previous_sweep),
            "next": _context_sweep_record(job.next_sweep),
            "temporal_available": bool(
                job.previous_sweep is not None
                or job.next_sweep is not None
            ),
            "upper_elevation_available": (
                job.upper_sweep is not None
            ),
            "upper_elevation_expected": (
                job.upper_elevation_expected
            ),
            "learned_background_available": True,
        },
        "baseline": _result_metrics(baseline, values),
        "learned": _result_metrics(learned, values),
        "delta": {
            "learned_increment_count": int(learned_increment.sum()),
            "learned_increment_fraction": _fraction(
                int(learned_increment.sum()),
                int(np.isfinite(values).sum()),
            ),
            "learned_increment_dbzh": _removed_value_metrics(
                values,
                learned_increment,
            ),
            "learned_rescue_count": int(learned_rescue.sum()),
            "mask_disagreement_count": int(
                (baseline_remove ^ learned_remove).sum()
            ),
        },
        "status": "scored_research_artifact",
        "promotion_eligible": False,
    }
    arrays = {
        "dbzh_raw": np.asarray(values, dtype="float32"),
        "dbzh_baseline_cleaned": np.where(
            baseline_remove,
            np.nan,
            values,
        ).astype("float32"),
        "dbzh_learned_cleaned": np.where(
            learned_remove,
            np.nan,
            values,
        ).astype("float32"),
        "baseline_remove_mask": baseline_remove.astype("uint8"),
        "baseline_nuisance_mask": np.asarray(
            baseline.nuisance_mask,
            dtype="uint16",
        ),
        "baseline_evidence_mask": np.asarray(
            baseline.evidence_mask,
            dtype="uint32",
        ),
        "baseline_protected_mask": np.asarray(
            baseline.protected_mask,
            dtype="uint8",
        ),
        "baseline_confidence": np.asarray(
            baseline.confidence,
            dtype="float32",
        ),
        "baseline_noise_profile": np.asarray(
            baseline.noise_profile,
            dtype="float32",
        ),
        "learned_remove_mask": learned_remove.astype("uint8"),
        "learned_nuisance_mask": np.asarray(
            learned.nuisance_mask,
            dtype="uint16",
        ),
        "learned_evidence_mask": np.asarray(
            learned.evidence_mask,
            dtype="uint32",
        ),
        "learned_protected_mask": np.asarray(
            learned.protected_mask,
            dtype="uint8",
        ),
        "learned_confidence": np.asarray(
            learned.confidence,
            dtype="float32",
        ),
        "learned_noise_profile": np.asarray(
            learned.noise_profile,
            dtype="float32",
        ),
        "learned_increment_mask": learned_increment.astype("uint8"),
    }
    return BackgroundValidationEvaluation(record=record, arrays=arrays)


def write_background_validation_artifact(
    evaluation: BackgroundValidationEvaluation,
    output_root: str | Path,
    *,
    configuration_contract: dict[str, Any],
) -> tuple[Path, Path, dict[str, Any]]:
    """Persist exact masks and provenance atomically."""

    np = require_numpy()
    record = dict(evaluation.record)
    artifact_dir = (
        Path(output_root)
        / str(record["split"])
        / str(record["target_id"])
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    source_id = str(record["source"]["source_id"])
    npz_path = artifact_dir / f"{source_id}.npz"
    sidecar_path = artifact_dir / f"{source_id}.npz.json"
    temporary = npz_path.with_suffix(".npz.tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(
            handle,
            **{
                name: np.asarray(values)
                for name, values in sorted(evaluation.arrays.items())
            },
        )
    temporary.replace(npz_path)
    array_hash = hash_validation_arrays(evaluation.arrays)
    artifact_hash = file_sha256(npz_path)
    sidecar = {
        "schema": "uk_wsr_background_validation_artifact",
        "schema_version": 1,
        "record": record,
        "configuration": configuration_contract,
        "array_hash": array_hash,
        "artifact_sha256": artifact_hash,
        "arrays": {
            name: {
                "dtype": str(np.asarray(values).dtype),
                "shape": list(np.asarray(values).shape),
            }
            for name, values in sorted(evaluation.arrays.items())
        },
        "evidence_flags": {
            flag.name: int(flag) for flag in EvidenceFlag
        },
        "nuisance_flags": {
            flag.name: int(flag) for flag in NuisanceFlag
        },
        "npz_path": npz_path.name,
    }
    _write_json_atomic(sidecar_path, sidecar)
    return npz_path, sidecar_path, sidecar


def load_resumable_validation_record(
    sidecar_path: str | Path,
    *,
    source_sha256: str,
    model_array_hash: str | None,
    configuration_sha256: str,
) -> dict[str, Any] | None:
    """Return a verified prior record, or None when it must be recomputed."""

    source = Path(sidecar_path)
    if not source.is_file():
        return None
    try:
        sidecar = json.loads(source.read_text(encoding="utf-8"))
        record = sidecar["record"]
        npz_path = source.parent / str(sidecar["npz_path"])
        if (
            record["source"]["sha256"] != source_sha256
            or record["model"]["array_hash"] != model_array_hash
            or record["configuration_sha256"] != configuration_sha256
            or not npz_path.is_file()
            or file_sha256(npz_path) != sidecar["artifact_sha256"]
        ):
            return None
        with require_numpy().load(npz_path) as loaded:
            arrays = {name: loaded[name] for name in loaded.files}
        if hash_validation_arrays(arrays) != sidecar["array_hash"]:
            return None
        return dict(record) | {
            "artifact_npz": str(npz_path),
            "artifact_sidecar": str(source),
            "artifact_sha256": sidecar["artifact_sha256"],
            "artifact_array_hash": sidecar["array_hash"],
            "resumed": True,
        }
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def summarise_background_validation(
    records: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate descriptive diagnostics without making label claims."""

    np = require_numpy()
    rows = list(records)
    groups: dict[str, dict[str, Any]] = {}
    for group_name, selected in _validation_groups(rows).items():
        finite = sum(
            int(row["learned"]["finite_count"]) for row in selected
        )
        baseline_removed = sum(
            int(row["baseline"]["removed_count"]) for row in selected
        )
        learned_removed = sum(
            int(row["learned"]["removed_count"]) for row in selected
        )
        increment = sum(
            int(row["delta"]["learned_increment_count"])
            for row in selected
        )
        learned_shares = np.asarray(
            [
                float(row["learned"]["removed_fraction"])
                for row in selected
            ],
            dtype="float64",
        )
        increment_shares = np.asarray(
            [
                float(row["delta"]["learned_increment_fraction"])
                for row in selected
            ],
            dtype="float64",
        )
        groups[group_name] = {
            "sweep_count": len(selected),
            "finite_gate_count": finite,
            "baseline_removed_count": baseline_removed,
            "baseline_removed_fraction": _fraction(
                baseline_removed,
                finite,
            ),
            "learned_removed_count": learned_removed,
            "learned_removed_fraction": _fraction(
                learned_removed,
                finite,
            ),
            "learned_increment_count": increment,
            "learned_increment_fraction": _fraction(increment, finite),
            "learned_removed_share_quantiles": _quantiles(
                learned_shares
            ),
            "learned_increment_share_quantiles": _quantiles(
                increment_shares
            ),
            "nuisance_counts": {
                flag.name.lower(): sum(
                    int(
                        row["learned"]["nuisance_counts"].get(
                            flag.name.lower(),
                            0,
                        )
                    )
                    for row in selected
                )
                for flag in NuisanceFlag
            },
            "removed_at_or_above_dbzh": {
                _threshold_label(threshold): sum(
                    int(
                        row["learned"]["removed_dbzh"][
                            "count_at_or_above_dbzh"
                        ][_threshold_label(threshold)]
                    )
                    for row in selected
                )
                for threshold in _REMOVAL_THRESHOLDS_DBZ
            },
        }
    worst_increment = sorted(
        rows,
        key=lambda row: float(
            row["delta"]["learned_increment_fraction"]
        ),
        reverse=True,
    )[:25]
    worst_total = sorted(
        rows,
        key=lambda row: float(row["learned"]["removed_fraction"]),
        reverse=True,
    )[:25]
    return {
        "record_count": len(rows),
        "radar_count": len({row["radar"] for row in rows}),
        "target_count": len({row["target_id"] for row in rows}),
        "source_count": len(
            {row["source"]["source_id"] for row in rows}
        ),
        "context_counts": {
            "upper_elevation": sum(
                bool(row["context"]["upper_elevation_available"])
                for row in rows
            ),
            "temporal": sum(
                bool(row["context"]["temporal_available"])
                for row in rows
            ),
        },
        "groups": groups,
        "worst_learned_increment": [
            _brief_record(row) for row in worst_increment
        ],
        "worst_total_removal": [
            _brief_record(row) for row in worst_total
        ],
        "interpretation": (
            "descriptive real-data diagnostics only; no class labels are "
            "inferred from CI, DBZH, removal share, or spatial appearance"
        ),
        "promotion_eligible": False,
    }


def write_background_validation_report(
    path: str | Path,
    *,
    split: str,
    expected_job_count: int,
    records: list[dict[str, Any]],
    errors: list[dict[str, str]],
    configuration_contract: dict[str, Any],
    configuration_sha256: str,
    artifact_root: str | Path,
    all_jobs_attempted: bool,
    frozen_policy_sha256: str | None = None,
) -> Path:
    """Checkpoint a validation run atomically."""

    report = {
        "schema": "uk_wsr_background_validation_results",
        "schema_version": 1,
        "split": split,
        "expected_job_count": expected_job_count,
        "scored_job_count": len(records),
        "error_count": len(errors),
        "all_jobs_attempted": all_jobs_attempted,
        "complete": (
            all_jobs_attempted
            and not errors
            and len(records) == expected_job_count
        ),
        "configuration": configuration_contract,
        "configuration_sha256": configuration_sha256,
        "frozen_policy_sha256": frozen_policy_sha256,
        "artifact_root": str(artifact_root),
        "summary": summarise_background_validation(records),
        "records": records,
        "errors": errors,
        "promotion_eligible_model_count": 0,
    }
    destination = Path(path)
    _write_json_atomic(destination, report)
    return destination


def hash_validation_arrays(arrays: dict[str, Any]) -> str:
    """Hash named arrays without losing integer mask dtypes."""

    np = require_numpy()
    digest = hashlib.sha256()
    for name in sorted(arrays):
        array = np.ascontiguousarray(np.asarray(arrays[name]))
        digest.update(name.encode("utf-8"))
        digest.update(array.dtype.str.encode("ascii"))
        digest.update(str(array.shape).encode("ascii"))
        digest.update(array.tobytes())
    return digest.hexdigest()


def _select_upper_sweep(
    target: BackgroundTrainingTarget,
    candidates: list[tuple[BackgroundTrainingTarget, SweepDescriptor]],
) -> SweepDescriptor | None:
    if target.elevation_deg >= 80.0:
        return None
    matches = [
        (candidate_target, sweep)
        for candidate_target, sweep in candidates
        if candidate_target.target_id != target.target_id
        and candidate_target.elevation_deg
        > target.elevation_deg + DEFAULT_ELEVATION_TOLERANCE_DEG
        and candidate_target.elevation_deg < 80.0
        and candidate_target.shape == target.shape
        and abs(candidate_target.rstart_km - target.rstart_km) <= 1e-6
        and abs(candidate_target.rscale_m - target.rscale_m) <= 1e-3
    ]
    if not matches:
        return None
    return min(matches, key=lambda item: item[0].elevation_deg)[1]


def _has_upper_target(
    target: BackgroundTrainingTarget,
    targets: list[BackgroundTrainingTarget],
) -> bool:
    if target.elevation_deg >= 80.0:
        return False
    return any(
        candidate.target_id != target.target_id
        and candidate.radar == target.radar
        and candidate.pulse == target.pulse
        and candidate.quantity == target.quantity
        and candidate.elevation_deg
        > target.elevation_deg + DEFAULT_ELEVATION_TOLERANCE_DEG
        and candidate.elevation_deg < 80.0
        and candidate.shape == target.shape
        and abs(candidate.rstart_km - target.rstart_km) <= 1e-6
        and abs(candidate.rscale_m - target.rscale_m) <= 1e-3
        for candidate in targets
    )


def _read_sweep(
    sweep: SweepDescriptor,
    target: BackgroundTrainingTarget,
    *,
    require_target_elevation: bool,
) -> tuple[Any, Any, dict[str, Any]]:
    values, metadata, companions = read_polar_field_with_companions(
        Path(sweep.local_path),
        sweep.radar,
        sweep.date,
        FieldSelection(
            pulse=sweep.pulse,
            time=sweep.time,
            quantity=sweep.quantity,
            dataset=sweep.dataset,
        ),
    )
    _verify_read_geometry(
        values,
        metadata,
        target,
        require_target_elevation=require_target_elevation,
    )
    return values, metadata, companions


def _read_context_dbzh(
    sweep: SweepDescriptor,
    target: BackgroundTrainingTarget,
) -> Any:
    values, _, _ = _read_sweep(
        sweep,
        target,
        require_target_elevation=False,
    )
    return values


def _verify_read_geometry(
    values: Any,
    metadata: Any,
    target: BackgroundTrainingTarget,
    *,
    require_target_elevation: bool,
) -> None:
    if tuple(values.shape) != target.shape:
        raise ValueError("validation sweep shape changed during read")
    if (
        metadata.elevation_deg is None
        or (
            require_target_elevation
            and abs(metadata.elevation_deg - target.elevation_deg)
            > DEFAULT_ELEVATION_TOLERANCE_DEG
        )
        or abs(metadata.rstart_km - target.rstart_km) > 1e-6
        or abs(metadata.rscale_m - target.rscale_m) > 1e-3
    ):
        raise ValueError("validation sweep does not match target geometry")


def _result_metrics(
    result: EvidenceResult,
    values: Any,
) -> dict[str, Any]:
    np = require_numpy()
    finite = np.isfinite(values)
    remove = np.asarray(result.remove_mask, dtype=bool)
    protected = np.asarray(result.protected_mask, dtype=bool)
    evidence = np.asarray(result.evidence_mask, dtype="uint32")
    upper_support = (
        evidence & int(EvidenceFlag.UPPER_ELEVATION_SUPPORT)
    ) != 0
    return {
        "finite_count": int(finite.sum()),
        "removed_count": int(remove.sum()),
        "removed_fraction": _fraction(
            int(remove.sum()),
            int(finite.sum()),
        ),
        "protected_count": int(protected.sum()),
        "removed_protected_count": int((remove & protected).sum()),
        "upper_supported_count": int(upper_support.sum()),
        "removed_upper_supported_count": int(
            (remove & upper_support).sum()
        ),
        "removed_dbzh": _removed_value_metrics(values, remove),
        "nuisance_counts": {
            flag.name.lower(): int(
                (
                    np.asarray(result.nuisance_mask, dtype="uint16")
                    & int(flag)
                    != 0
                ).sum()
            )
            for flag in NuisanceFlag
        },
        "evidence_counts": {
            flag.name.lower(): int(
                ((evidence & int(flag)) != 0).sum()
            )
            for flag in EvidenceFlag
        },
    }


def _removed_value_metrics(values: Any, mask: Any) -> dict[str, Any]:
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    selected = array[np.asarray(mask, dtype=bool) & np.isfinite(array)]
    finite = array[np.isfinite(array)]
    if selected.size:
        minimum = float(selected.min())
        median = float(np.median(selected))
        p90 = float(np.percentile(selected, 90))
        maximum = float(selected.max())
    else:
        minimum = median = p90 = maximum = None
    linear_total = float(
        np.power(10.0, np.clip(finite, -50.0, 100.0) / 10.0).sum(
            dtype="float64"
        )
    )
    linear_removed = float(
        np.power(
            10.0,
            np.clip(selected, -50.0, 100.0) / 10.0,
        ).sum(dtype="float64")
    )
    return {
        "count": int(selected.size),
        "minimum": minimum,
        "median": median,
        "p90": p90,
        "maximum": maximum,
        "linear_reflectivity_fraction": _fraction(
            linear_removed,
            linear_total,
        ),
        "count_at_or_above_dbzh": {
            _threshold_label(threshold): int(
                (selected >= threshold).sum()
            )
            for threshold in _REMOVAL_THRESHOLDS_DBZ
        },
        "input_count_at_or_above_dbzh": {
            _threshold_label(threshold): int(
                (finite >= threshold).sum()
            )
            for threshold in _REMOVAL_THRESHOLDS_DBZ
        },
    }


def _validation_groups(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    groups = {
        "all": records,
        "ppi": [
            row for row in records if row["geometry_class"] == "ppi"
        ],
        "vertical": [
            row
            for row in records
            if row["geometry_class"] == "vertical"
        ],
    }
    for pulse in ("lp", "sp"):
        groups[pulse] = [
            row for row in records if row["pulse"] == pulse
        ]
    return groups


def _brief_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": record["job_id"],
        "target_id": record["target_id"],
        "radar": record["radar"],
        "pulse": record["pulse"],
        "elevation_deg": record["elevation_deg"],
        "source_id": record["source"]["source_id"],
        "date": record["source"]["date"],
        "time": record["source"]["time"],
        "learned_removed_fraction": record["learned"][
            "removed_fraction"
        ],
        "learned_increment_fraction": record["delta"][
            "learned_increment_fraction"
        ],
        "maximum_removed_dbzh": record["learned"]["removed_dbzh"][
            "maximum"
        ],
    }


def _quantiles(values: Any) -> dict[str, float | None]:
    np = require_numpy()
    array = np.asarray(values, dtype="float64")
    if array.size == 0:
        return {
            "minimum": None,
            "p10": None,
            "median": None,
            "p90": None,
            "maximum": None,
        }
    return {
        "minimum": float(array.min()),
        "p10": float(np.percentile(array, 10)),
        "median": float(np.median(array)),
        "p90": float(np.percentile(array, 90)),
        "maximum": float(array.max()),
    }


def _context_sweep_record(
    sweep: SweepDescriptor | None,
) -> dict[str, Any] | None:
    if sweep is None:
        return None
    return {
        "source_id": sweep.source_id,
        "sha256": sweep.sha256,
        "date": sweep.date,
        "time": sweep.time,
        "dataset": sweep.dataset,
        "elevation_deg": sweep.elevation_deg,
    }


def _geometry_class(target: BackgroundTrainingTarget) -> str:
    return "vertical" if target.elevation_deg >= 80.0 else "ppi"


def _sweep_datetime(sweep: SweepDescriptor) -> datetime:
    return datetime.strptime(
        f"{sweep.date}{sweep.time}",
        "%Y%m%d%H%M",
    )


def _minutes_between(
    earlier: SweepDescriptor,
    later: SweepDescriptor,
) -> float:
    return (
        _sweep_datetime(later) - _sweep_datetime(earlier)
    ).total_seconds() / 60.0


def _threshold_label(threshold: float) -> str:
    return f"{threshold:g}"


def _fraction(numerator: float | int, denominator: float | int) -> float:
    return (
        float(numerator) / float(denominator)
        if float(denominator) > 0.0
        else 0.0
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
