"""Leakage-controlled validation of learned backgrounds on real UK WSR data."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import zipfile
from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .background_model import BackgroundModel
from .background_model_v3 import BACKGROUND_MODEL_V3_STATISTICS_VERSION
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
from .qc import VRAD_CANDIDATES, normalized_quantity

BACKGROUND_VALIDATION_SCHEMA = "uk_wsr_background_validation"
BACKGROUND_VALIDATION_SCHEMA_VERSION = 1
DEFAULT_TEMPORAL_GAP_MINUTES = 20
VALIDATION_ARTIFACT_COMPRESSION_LEVEL = 1
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
    receiver_noise_cross_scan_required: bool = False

    @property
    def job_id(self) -> str:
        return f"{self.target.target_id}__{self.sweep.source_id}"


@dataclass(frozen=True)
class BackgroundValidationEvaluation:
    """Exact candidate results and the serialisable sweep record."""

    record: dict[str, Any]
    arrays: dict[str, Any]


class BackgroundValidationModelResolver:
    """Resolve one unique audited model for a validation target."""

    def __init__(self, model_dir: str | Path) -> None:
        self.model_dir = Path(model_dir)
        self._manifest_index: tuple[tuple[Path, dict[str, Any]], ...] | None = (
            None
        )

    def resolve_path(self, target: BackgroundTrainingTarget) -> Path:
        exact = self.model_dir / f"{target.target_id}.json"
        if exact.is_file():
            return exact

        candidates: list[tuple[float, Path]] = []
        for path, manifest in self._manifests():
            match = _model_key_target_match(
                dict(manifest.get("key") or {}),
                tuple(int(value) for value in manifest.get("shape") or ()),
                target,
            )
            if match["compatible"]:
                candidates.append(
                    (float(match["elevation_delta_deg"]), path)
                )
        if not candidates:
            raise FileNotFoundError(
                f"no compatible background model for {target.target_id}"
            )
        candidates.sort(key=lambda item: (item[0], item[1].name))
        minimum_delta = candidates[0][0]
        nearest = [
            path
            for delta, path in candidates
            if abs(delta - minimum_delta) <= 1.0e-9
        ]
        if len(nearest) != 1:
            raise ValueError(
                "ambiguous compatible background models for "
                f"{target.target_id}: "
                + ",".join(path.name for path in nearest)
            )
        return nearest[0]

    def _manifests(self) -> tuple[tuple[Path, dict[str, Any]], ...]:
        if self._manifest_index is None:
            manifests = []
            for path in sorted(self.model_dir.glob("*.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("schema") != "uk_wsr_background_model":
                    continue
                manifests.append((path, payload))
            self._manifest_index = tuple(manifests)
        return self._manifest_index


class ValidationSweepReadCache:
    """Bounded LRU for immutable sweep reads during sequential validation."""

    def __init__(self, max_entries: int = 8) -> None:
        if int(max_entries) < 0:
            raise ValueError("max_entries must be non-negative")
        self.max_entries = int(max_entries)
        self.hits = 0
        self.misses = 0
        self._entries: OrderedDict[
            tuple[str, ...],
            tuple[Any, Any, dict[str, Any]],
        ] = OrderedDict()

    def read(
        self,
        sweep: SweepDescriptor,
        target: BackgroundTrainingTarget,
    ) -> tuple[Any, Any, dict[str, Any]]:
        key = (
            str(Path(sweep.local_path)),
            str(sweep.sha256),
            str(sweep.source_id),
            str(sweep.dataset),
            str(sweep.field_group),
            str(target.target_id),
        )
        cached = self._entries.pop(key, None)
        if cached is not None:
            self.hits += 1
            self._entries[key] = cached
            return cached

        self.misses += 1
        loaded = _load_sweep(sweep)
        if self.max_entries > 0:
            self._entries[key] = loaded
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return loaded

    def statistics(self) -> dict[str, int]:
        return {
            "max_entries": self.max_entries,
            "entry_count": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
        }


def build_background_validation_jobs(
    targets: Iterable[BackgroundTrainingTarget],
    *,
    split: str,
    max_temporal_gap_minutes: int = DEFAULT_TEMPORAL_GAP_MINUTES,
    eligible_source_ids: Iterable[str] | None = None,
) -> tuple[BackgroundValidationJob, ...]:
    """Build validation jobs without borrowing context across data splits."""

    if split not in {"validation", "holdout"}:
        raise ValueError("split must be validation or holdout")
    eligible = (
        {str(value) for value in eligible_source_ids}
        if eligible_source_ids is not None
        else None
    )
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
            if eligible is not None and sweep.source_id not in eligible:
                continue
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
                    receiver_noise_cross_scan_required=bool(
                        target.pulse == "sp"
                        and target.elevation_deg < 80.0
                        and upper is None
                    ),
                )
            )
    return tuple(
        sorted(
            jobs,
            key=lambda job: (
                job.target.target_id,
                _sweep_datetime(job.sweep),
                job.sweep.source_id,
            ),
        )
    )


def validation_configuration_contract(
    config: EvidenceConfig,
    *,
    max_temporal_gap_minutes: int,
    temporal_manifest_sha256: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Return the frozen decision contract and its deterministic hash."""

    contract = {
        "schema": "uk_wsr_background_validation_configuration",
        "schema_version": 5,
        "evidence_version": EVIDENCE_VERSION,
        "evidence_config": asdict(config),
        "implementation_sha256": {
            name: file_sha256(Path(__file__).with_name(name))
            for name in (
                "background_validation_pipeline.py",
                "background_training_pipeline.py",
                "qc_evidence.py",
                "receiver_noise_model.py",
                "background_model_v3.py",
            )
        },
        "context_policy": {
            "companion_fields": "all_matching_fields_in_selected_dataset",
            "target_elevation_identity": (
                "observed elevations within 0.075 degrees of a nominal "
                "0.5-degree scan angle share that canonical target id; "
                "observed elevation metadata remains unchanged"
            ),
            "model_target_compatibility": (
                "exact geometry id is preferred; otherwise radar, pulse, "
                "quantity, array shape, range start, range scale, and "
                "elevation within 0.075 degrees must match uniquely"
            ),
            "receiver_noise_geometry": (
                "target rstart_km and rscale_m are required; missing or "
                "invalid geometry fails open"
            ),
            "receiver_noise_physical_model": (
                "robust DBZH versus log10(range) pedestal fit constrained "
                "to the radar-equation slope"
            ),
            "receiver_noise_independent_evidence": (
                "high CI and low SQI plus physical range support and at "
                "least two of polarimetric, Doppler, spatial, or hardware "
                "evidence families"
            ),
            "receiver_noise_cross_scan_requirement": (
                "SP PPI gates without a higher same-volume sweep require "
                "finite higher-elevation coverage or complete bracketing "
                "DBZH and VRAD coverage; uncovered gates fail open"
            ),
            "learned_statistics_version": (
                BACKGROUND_MODEL_V3_STATISTICS_VERSION
            ),
            "learned_date_count_array": (
                "low_ci_static_echo_date_sample_count"
            ),
            "learned_static_frequency_array": (
                "low_ci_static_echo_date_frequency"
            ),
            "learned_season_coverage_array": (
                "low_ci_static_echo_season_count"
            ),
            "learned_time_coverage_array": (
                "low_ci_static_echo_time_bucket_count"
            ),
            "learned_static_dbzh_distribution_arrays": (
                "date-balanced low-CI near-zero-VRAD static DBZH "
                "p10, median, and p90"
            ),
            "learned_static_dbzh_distribution_requirement": (
                "current DBZH must remain within the conditioned median "
                "and p90 margins, and the conditioned p10-p90 spread must "
                "be narrow enough to reject contaminated backgrounds"
            ),
            "upper_elevation": (
                "nearest_higher_same-source PPI with exact range geometry"
            ),
            "missing_expected_upper_elevation": (
                "learned clutter and anomalous propagation fail open"
            ),
            "temporal": (
                "same-target same-split neighbours within configured gap"
            ),
            "learned_temporal_requirement": (
                "both bracketing volumes must be present, DBZH must agree "
                "with both within the strict learned-clutter amplitude "
                "tolerance, and VRAD must be near zero in both; otherwise "
                "learned removal fails open"
            ),
            "learned_geometry_requirement": (
                "two-dimensional learned backgrounds apply only to PPI "
                "geometry; vertical geometry fails open"
            ),
            "max_temporal_gap_minutes": int(
                max_temporal_gap_minutes
            ),
            "missing_context": "fail_open",
        },
    }
    if temporal_manifest_sha256 is not None:
        contract["context_policy"].update(
            {
                "temporal_manifest_sha256": (
                    temporal_manifest_sha256
                ),
                "temporal_scoring_members": (
                    "interior_sequence_members_only"
                ),
            }
        )
    encoded = json.dumps(
        contract,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return contract, hashlib.sha256(encoded).hexdigest()


def _date_balanced_learned_context(
    model: BackgroundModel,
) -> dict[str, Any]:
    if (
        model.metadata.get("statistics_version")
        != BACKGROUND_MODEL_V3_STATISTICS_VERSION
    ):
        return {}
    array_mapping = {
        "background_distinct_date_count": (
            "low_ci_static_echo_date_sample_count"
        ),
        "background_static_echo_date_frequency": (
            "low_ci_static_echo_date_frequency"
        ),
        "background_static_echo_season_count": (
            "low_ci_static_echo_season_count"
        ),
        "background_static_echo_time_bucket_count": (
            "low_ci_static_echo_time_bucket_count"
        ),
        "background_static_dbzh_p10": "low_ci_static_dbzh_p10",
        "background_static_dbzh_median": (
            "low_ci_static_dbzh_median"
        ),
        "background_static_dbzh_p90": "low_ci_static_dbzh_p90",
    }
    if any(
        array_name not in model.arrays
        for array_name in array_mapping.values()
    ):
        return {}
    return {
        "background_statistics_version": (
            BACKGROUND_MODEL_V3_STATISTICS_VERSION
        ),
        **{
            context_name: model.arrays[array_name]
            for context_name, array_name in array_mapping.items()
        },
    }


def evaluate_background_validation_job(
    job: BackgroundValidationJob,
    model: BackgroundModel,
    *,
    config: EvidenceConfig,
    configuration_sha256: str,
    read_cache: ValidationSweepReadCache | None = None,
) -> BackgroundValidationEvaluation:
    """Evaluate baseline and learned candidates and retain exact decisions."""

    np = require_numpy()
    model_target_match = background_model_target_match(
        model,
        job.target,
    )
    if not model_target_match["compatible"]:
        raise ValueError(
            "background model does not match validation target: "
            + str(model_target_match["reason"])
        )

    values, metadata, companions = _read_sweep(
        job.sweep,
        job.target,
        require_target_elevation=True,
        read_cache=read_cache,
    )
    upper = (
        _read_context_dbzh(
            job.upper_sweep,
            job.target,
            read_cache=read_cache,
        )
        if job.upper_sweep is not None
        else None
    )
    previous, previous_vrad = (
        _read_context_dbzh_vrad(
            job.previous_sweep,
            job.target,
            read_cache=read_cache,
        )
        if job.previous_sweep is not None
        else (None, None)
    )
    following, following_vrad = (
        _read_context_dbzh_vrad(
            job.next_sweep,
            job.target,
            read_cache=read_cache,
        )
        if job.next_sweep is not None
        else (None, None)
    )
    common_context = {
        "previous_dbzh": previous,
        "next_dbzh": following,
        "previous_vrad": previous_vrad,
        "next_vrad": following_vrad,
        "upper_elevation_dbzh": upper,
        "upper_elevation_required": job.upper_elevation_expected,
        "elevation_deg": job.target.elevation_deg,
        "receiver_noise_cross_scan_required": (
            job.receiver_noise_cross_scan_required
        ),
    }
    learned_model_context = _date_balanced_learned_context(
        model,
    )
    learned = classify_nuisance_echoes(
        values,
        companions,
        pulse=job.target.pulse,
        rstart_km=job.target.rstart_km,
        rscale_m=job.target.rscale_m,
        config=config,
        context=EvidenceContext(
            **common_context,
            temporal_context_required=True,
            learned_background_allowed=(
                _geometry_class(job.target) == "ppi"
            ),
            **learned_model_context,
        ),
    )
    baseline = (
        classify_nuisance_echoes(
            values,
            companions,
            pulse=job.target.pulse,
            rstart_km=job.target.rstart_km,
            rscale_m=job.target.rscale_m,
            config=config,
            context=EvidenceContext(**common_context),
        )
        if config.isolated_speckle_enabled
        else _baseline_result_from_learned(learned)
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
            "target_match": model_target_match,
            "source_manifest_sha256": model.metadata.get(
                "source_manifest_sha256"
            ),
            "download_ledger_sha256": model.metadata.get(
                "download_ledger_sha256"
            ),
            "statistics_version": model.metadata.get(
                "statistics_version"
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
            "temporal_context_count": sum(
                sweep is not None
                for sweep in (
                    job.previous_sweep,
                    job.next_sweep,
                )
            ),
            "temporal_context_complete": bool(
                job.previous_sweep is not None
                and job.next_sweep is not None
            ),
            "learned_temporal_context_required": True,
            "temporal_velocity_context_count": sum(
                values is not None
                for values in (
                    previous_vrad,
                    following_vrad,
                )
            ),
            "temporal_velocity_context_complete": bool(
                previous_vrad is not None
                and following_vrad is not None
            ),
            "learned_background_allowed": (
                _geometry_class(job.target) == "ppi"
            ),
            "upper_elevation_available": (
                job.upper_sweep is not None
            ),
            "upper_elevation_expected": (
                job.upper_elevation_expected
            ),
            "receiver_noise_cross_scan_required": bool(
                job.receiver_noise_cross_scan_required
            ),
            "receiver_noise_cross_scan_available": bool(
                baseline.metadata["context"][
                    "receiver_noise_cross_scan_available"
                ]
            ),
            "receiver_noise_cross_scan_gate_count": int(
                baseline.metadata["context"][
                    "receiver_noise_cross_scan_gate_count"
                ]
            ),
            "learned_background_available": bool(
                learned_model_context
            ),
            "learned_background_schema_qualified": bool(
                learned_model_context
            ),
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


def background_model_target_match(
    model: BackgroundModel,
    target: BackgroundTrainingTarget,
) -> dict[str, Any]:
    """Describe exact or tolerance-based physical model compatibility."""

    return _model_key_target_match(
        model.key,
        tuple(model.shape),
        target,
    )


def _model_key_target_match(
    key: dict[str, Any],
    shape: tuple[int, ...],
    target: BackgroundTrainingTarget,
) -> dict[str, Any]:
    geometry_id = str(key.get("geometry_id") or "")
    base = {
        "target_id": target.target_id,
        "model_geometry_id": geometry_id or None,
        "elevation_tolerance_deg": DEFAULT_ELEVATION_TOLERANCE_DEG,
    }
    if tuple(shape) != target.shape:
        return base | {
            "compatible": False,
            "match_type": None,
            "elevation_delta_deg": None,
            "reason": "shape_mismatch",
        }
    if geometry_id == target.target_id:
        model_elevation = key.get("elevation_deg")
        delta = (
            abs(float(model_elevation) - target.elevation_deg)
            if model_elevation not in (None, "")
            else 0.0
        )
        return base | {
            "compatible": True,
            "match_type": "exact_geometry_id",
            "elevation_delta_deg": float(delta),
            "reason": None,
        }

    comparisons = (
        (
            str(key.get("radar") or "").lower()
            == target.radar.lower(),
            "radar_mismatch",
        ),
        (
            str(key.get("pulse") or "").lower()
            == target.pulse.lower(),
            "pulse_mismatch",
        ),
        (
            str(key.get("quantity") or "").upper()
            == target.quantity.upper(),
            "quantity_mismatch",
        ),
        (
            int(key.get("nrays") or -1) == target.nrays,
            "ray_count_mismatch",
        ),
        (
            int(key.get("nbins") or -1) == target.nbins,
            "gate_count_mismatch",
        ),
        (
            key.get("rstart_km") not in (None, "")
            and abs(float(key["rstart_km"]) - target.rstart_km)
            <= 1.0e-6,
            "range_start_mismatch",
        ),
        (
            key.get("rscale_m") not in (None, "")
            and abs(float(key["rscale_m"]) - target.rscale_m)
            <= 1.0e-3,
            "range_scale_mismatch",
        ),
    )
    for compatible, reason in comparisons:
        if not compatible:
            return base | {
                "compatible": False,
                "match_type": None,
                "elevation_delta_deg": None,
                "reason": reason,
            }
    model_elevation = key.get("elevation_deg")
    if model_elevation in (None, ""):
        return base | {
            "compatible": False,
            "match_type": None,
            "elevation_delta_deg": None,
            "reason": "missing_model_elevation",
        }
    elevation_delta = abs(float(model_elevation) - target.elevation_deg)
    if elevation_delta > DEFAULT_ELEVATION_TOLERANCE_DEG:
        return base | {
            "compatible": False,
            "match_type": None,
            "elevation_delta_deg": float(elevation_delta),
            "reason": "elevation_mismatch",
        }
    return base | {
        "compatible": True,
        "match_type": "physical_geometry_within_elevation_tolerance",
        "elevation_delta_deg": float(elevation_delta),
        "reason": None,
    }


def _baseline_result_from_learned(
    learned: EvidenceResult,
) -> EvidenceResult:
    """Remove learned-only decisions without recomputing shared evidence."""

    np = require_numpy()
    learned_nuisance_bits = int(
        NuisanceFlag.STATIC_CLUTTER
        | NuisanceFlag.ANOMALOUS_PROPAGATION
    )
    learned_evidence_bits = int(
        EvidenceFlag.LEARNED_PERSISTENCE
        | EvidenceFlag.LEARNED_STATIC_VELOCITY
        | EvidenceFlag.LEARNED_DBZH_COMPATIBLE
        | EvidenceFlag.LEARNED_DATE_COVERAGE
        | EvidenceFlag.LEARNED_SEASON_COVERAGE
        | EvidenceFlag.LEARNED_TIME_COVERAGE
        | EvidenceFlag.LEARNED_STATIC_DATE_FREQUENCY
    )
    nuisance = (
        np.asarray(learned.nuisance_mask, dtype="uint16")
        & np.uint16(~learned_nuisance_bits & 0xFFFF)
    )
    remove = nuisance != 0
    evidence = (
        np.asarray(learned.evidence_mask, dtype="uint32")
        & np.uint32(~learned_evidence_bits & 0xFFFFFFFF)
    )
    confidence = np.asarray(
        learned.confidence,
        dtype="float32",
    ).copy()
    confidence[~remove] = 0.0
    counts = dict(learned.counts)
    counts.update(
        {
            "removed": int(remove.sum()),
            "static_clutter": 0,
            "anomalous_propagation": 0,
        }
    )
    metadata = copy.deepcopy(learned.metadata)
    context = metadata.setdefault("context", {})
    context.update(
        {
            "learned_background": False,
            "learned_background_statistics_version": None,
            "learned_background_statistics_qualified": False,
        }
    )
    metadata["baseline_derivation"] = {
        "method": "clear_learned_only_nuisance_and_evidence_bits",
        "cleared_nuisance_flags": [
            NuisanceFlag.STATIC_CLUTTER.name,
            NuisanceFlag.ANOMALOUS_PROPAGATION.name,
        ],
        "isolated_speckle_enabled": False,
    }
    return EvidenceResult(
        remove_mask=remove,
        nuisance_mask=nuisance,
        evidence_mask=evidence,
        confidence=confidence,
        protected_mask=np.asarray(
            learned.protected_mask,
            dtype=bool,
        ).copy(),
        noise_profile=np.asarray(
            learned.noise_profile,
            dtype="float32",
        ).copy(),
        counts=counts,
        metadata=metadata,
        version=learned.version,
    )


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
    _write_deterministic_npz(
        temporary,
        evaluation.arrays,
        compression_level=VALIDATION_ARTIFACT_COMPRESSION_LEVEL,
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
        "archive": {
            "format": "npz",
            "compression": "deflate",
            "compression_level": VALIDATION_ARTIFACT_COMPRESSION_LEVEL,
            "member_timestamp": "1980-01-01T00:00:00",
        },
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


def _write_deterministic_npz(
    destination: Path,
    arrays: dict[str, Any],
    *,
    compression_level: int,
) -> None:
    np = require_numpy()
    with zipfile.ZipFile(destination, mode="w") as archive:
        for name, values in sorted(arrays.items()):
            payload = io.BytesIO()
            np.lib.format.write_array(
                payload,
                np.asarray(values),
                allow_pickle=False,
            )
            member = zipfile.ZipInfo(
                filename=f"{name}.npy",
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(
                member,
                payload.getvalue(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=int(compression_level),
            )


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


def merge_background_validation_shards(
    shard_paths: Iterable[str | Path],
    destination: str | Path,
) -> Path:
    """Merge complete, contract-identical shards into one canonical report."""

    paths = [Path(path) for path in shard_paths]
    if not paths:
        raise ValueError("at least one validation shard is required")

    reports = []
    for path in paths:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read validation shard {path}: {exc}") from exc
        if report.get("schema") != "uk_wsr_background_validation_results":
            raise ValueError(f"unexpected validation schema in {path}")
        if int(report.get("schema_version", 0)) != 1:
            raise ValueError(f"unsupported validation schema version in {path}")
        if not report.get("complete"):
            raise ValueError(f"validation shard is incomplete: {path}")
        if report.get("errors"):
            raise ValueError(f"validation shard contains errors: {path}")
        if int(report.get("scored_job_count", -1)) != len(
            report.get("records", ())
        ):
            raise ValueError(f"validation shard record count mismatch: {path}")
        reports.append(report)

    reference = reports[0]
    contract_fields = (
        "split",
        "configuration_sha256",
        "configuration",
        "frozen_policy_sha256",
        "artifact_root",
    )
    for path, report in zip(paths[1:], reports[1:]):
        for field in contract_fields:
            if report.get(field) != reference.get(field):
                raise ValueError(
                    f"validation shard {field} mismatch in {path}"
                )

    records = [
        dict(record)
        for report in reports
        for record in report.get("records", ())
    ]
    job_ids = [str(record.get("job_id", "")) for record in records]
    missing_job_ids = sum(not job_id for job_id in job_ids)
    if missing_job_ids:
        raise ValueError(
            f"validation records missing job_id: {missing_job_ids}"
        )
    duplicate_job_ids = sorted(
        job_id
        for job_id, count in Counter(job_ids).items()
        if count > 1
    )
    if duplicate_job_ids:
        preview = ", ".join(duplicate_job_ids[:5])
        raise ValueError(f"duplicate validation jobs across shards: {preview}")

    expected_job_count = sum(
        int(report["expected_job_count"]) for report in reports
    )
    if len(records) != expected_job_count:
        raise ValueError(
            "merged validation record count does not match shard expectations: "
            f"{len(records)} != {expected_job_count}"
        )

    records.sort(key=lambda record: str(record["job_id"]))
    return write_background_validation_report(
        destination,
        split=str(reference["split"]),
        expected_job_count=expected_job_count,
        records=records,
        errors=[],
        configuration_contract=dict(reference["configuration"]),
        configuration_sha256=str(reference["configuration_sha256"]),
        artifact_root=str(reference["artifact_root"]),
        all_jobs_attempted=True,
        frozen_policy_sha256=reference.get("frozen_policy_sha256"),
    )


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
    read_cache: ValidationSweepReadCache | None = None,
) -> tuple[Any, Any, dict[str, Any]]:
    values, metadata, companions = (
        read_cache.read(sweep, target)
        if read_cache is not None
        else _load_sweep(sweep)
    )
    _verify_read_geometry(
        values,
        metadata,
        target,
        require_target_elevation=require_target_elevation,
    )
    return values, metadata, companions


def _load_sweep(
    sweep: SweepDescriptor,
) -> tuple[Any, Any, dict[str, Any]]:
    return read_polar_field_with_companions(
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


def _read_context_dbzh(
    sweep: SweepDescriptor,
    target: BackgroundTrainingTarget,
    *,
    read_cache: ValidationSweepReadCache | None = None,
) -> Any:
    values, _, _ = _read_sweep(
        sweep,
        target,
        require_target_elevation=False,
        read_cache=read_cache,
    )
    return values


def _read_context_dbzh_vrad(
    sweep: SweepDescriptor,
    target: BackgroundTrainingTarget,
    *,
    read_cache: ValidationSweepReadCache | None = None,
) -> tuple[Any, Any | None]:
    values, _, companions = _read_sweep(
        sweep,
        target,
        require_target_elevation=False,
        read_cache=read_cache,
    )
    normalised = {
        normalized_quantity(quantity): field
        for quantity, field in companions.items()
    }
    velocity = next(
        (
            normalised[candidate]
            for candidate in VRAD_CANDIDATES
            if candidate in normalised
        ),
        None,
    )
    return values, velocity


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
        "receiver_noise_candidate_count": int(
            result.counts.get("receiver_noise_candidate", 0)
        ),
        "receiver_noise_context_fail_open_count": int(
            result.counts.get("receiver_noise_context_fail_open", 0)
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
