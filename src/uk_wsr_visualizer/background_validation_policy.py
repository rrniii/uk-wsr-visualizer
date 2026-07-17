"""Fail-closed safety policy derived from completed real-data validation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .background_training_pipeline import file_sha256
from .dependencies import require_numpy

BACKGROUND_VALIDATION_POLICY_SCHEMA = "uk_wsr_background_validation_policy"
BACKGROUND_VALIDATION_POLICY_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BackgroundValidationPolicyConfig:
    """Safety screens that can reject, but never prove, a model."""

    minimum_sweeps_per_target: int = 7
    minimum_expected_upper_context_coverage_fraction: float = 0.75
    maximum_total_removal_fraction_per_sweep: float = 0.98
    maximum_learned_increment_fraction_per_sweep: float = 0.20
    maximum_removed_protected_gates: int = 0
    maximum_removed_upper_supported_gates: int = 0
    maximum_learned_rescue_gates: int = 0
    stability_gate_minimum_increment_fraction: float = 0.005
    minimum_nonempty_increment_jaccard: float = 0.05
    review_increment_fraction: float = 0.01
    review_linear_reflectivity_fraction: float = 0.01
    review_dbzh_threshold: float = 20.0


def build_frozen_background_validation_policy(
    validation_results_path: str | Path,
    *,
    config: BackgroundValidationPolicyConfig | None = None,
) -> dict[str, Any]:
    """Freeze per-target safety decisions before holdout is opened."""

    np = require_numpy()
    config = config or BackgroundValidationPolicyConfig()
    source = Path(validation_results_path)
    report = json.loads(source.read_text(encoding="utf-8"))
    if report.get("split") != "validation":
        raise ValueError("policy source must be the validation split")
    if (
        report.get("complete") is not True
        or int(report.get("error_count", -1)) != 0
    ):
        raise ValueError("validation run is not complete and error-free")
    records = list(report.get("records") or [])
    if len(records) != int(report.get("expected_job_count", -1)):
        raise ValueError("validation record count is incomplete")
    configuration_sha256 = str(report.get("configuration_sha256") or "")
    if not configuration_sha256:
        raise ValueError("validation configuration hash is missing")
    if any(
        record.get("configuration_sha256") != configuration_sha256
        for record in records
    ):
        raise ValueError("validation record configuration hash mismatch")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["target_id"]), []).append(record)
    target_policies: list[dict[str, Any]] = []
    for target_id, selected in sorted(grouped.items()):
        finite_count = sum(
            int(record["learned"]["finite_count"])
            for record in selected
        )
        increment_count = sum(
            int(record["delta"]["learned_increment_count"])
            for record in selected
        )
        removed_protected = sum(
            int(record["learned"]["removed_protected_count"])
            for record in selected
        )
        removed_upper = sum(
            int(record["learned"]["removed_upper_supported_count"])
            for record in selected
        )
        learned_rescue = sum(
            int(record["delta"]["learned_rescue_count"])
            for record in selected
        )
        max_total = max(
            float(record["learned"]["removed_fraction"])
            for record in selected
        )
        max_increment = max(
            float(record["delta"]["learned_increment_fraction"])
            for record in selected
        )
        max_increment_linear = max(
            float(
                record["delta"]["learned_increment_dbzh"][
                    "linear_reflectivity_fraction"
                ]
            )
            for record in selected
        )
        high_increment_count = sum(
            int(
                record["delta"]["learned_increment_dbzh"][
                    "count_at_or_above_dbzh"
                ][f"{config.review_dbzh_threshold:g}"]
            )
            for record in selected
        )
        upper_context_count = sum(
            bool(record["context"]["upper_elevation_available"])
            for record in selected
        )
        upper_expected_count = sum(
            bool(record["context"]["upper_elevation_expected"])
            for record in selected
        )
        upper_context_coverage = (
            upper_context_count / upper_expected_count
            if upper_expected_count
            else None
        )
        stability = _increment_stability(selected)
        blockers: list[str] = []
        if len(selected) < config.minimum_sweeps_per_target:
            blockers.append("insufficient validation sweep coverage")
        if removed_protected > config.maximum_removed_protected_gates:
            blockers.append("candidate removed protected gates")
        if (
            removed_upper
            > config.maximum_removed_upper_supported_gates
        ):
            blockers.append(
                "candidate removed upper-elevation-supported gates"
            )
        if learned_rescue > config.maximum_learned_rescue_gates:
            blockers.append(
                "learned context unexpectedly rescued baseline removals"
            )
        if (
            max_total
            > config.maximum_total_removal_fraction_per_sweep
        ):
            blockers.append("extreme total removal fraction")
        if (
            max_increment
            > config.maximum_learned_increment_fraction_per_sweep
        ):
            blockers.append("extreme learned-only removal fraction")
        aggregate_increment_fraction = (
            increment_count / finite_count if finite_count else 0.0
        )
        if (
            aggregate_increment_fraction
            >= config.stability_gate_minimum_increment_fraction
            and stability["nonempty_pair_count"] > 0
            and stability["mean_nonempty_pairwise_jaccard"]
            < config.minimum_nonempty_increment_jaccard
        ):
            blockers.append("learned-only mask is spatially unstable")
        if upper_expected_count not in {0, len(selected)}:
            blockers.append(
                "upper-elevation expectation changed within target"
            )
        if (
            upper_context_coverage is not None
            and upper_context_coverage
            < config.minimum_expected_upper_context_coverage_fraction
        ):
            blockers.append(
                "expected upper-elevation context coverage is inadequate"
            )

        review_reasons: list[str] = []
        if (
            upper_context_coverage is not None
            and upper_context_coverage < 1.0
        ):
            review_reasons.append(
                "partial volumes use learned-clutter fail-open"
            )
        if (
            aggregate_increment_fraction
            >= config.review_increment_fraction
        ):
            review_reasons.append("material learned-only gate fraction")
        if (
            max_increment_linear
            >= config.review_linear_reflectivity_fraction
        ):
            review_reasons.append(
                "material learned-only reflectivity power"
            )
        if high_increment_count:
            review_reasons.append(
                f"learned-only removals at or above "
                f"{config.review_dbzh_threshold:g} dBZ"
            )
        if str(selected[0]["geometry_class"]) == "vertical":
            review_reasons.append("vertical geometry requires separate review")
        if not review_reasons:
            review_reasons.append(
                "independent class labels are not yet complete"
            )

        state = "quarantined" if blockers else "requires_blinded_review"
        first = selected[0]
        target_policies.append(
            {
                "target_id": target_id,
                "radar": first["radar"],
                "pulse": first["pulse"],
                "quantity": first["quantity"],
                "geometry_class": first["geometry_class"],
                "elevation_deg": first["elevation_deg"],
                "validation_sweep_count": len(selected),
                "validation_date_count": len(
                    {record["source"]["date"] for record in selected}
                ),
                "finite_gate_count": finite_count,
                "learned_increment_count": increment_count,
                "learned_increment_fraction": (
                    aggregate_increment_fraction
                ),
                "maximum_total_removal_fraction": max_total,
                "maximum_learned_increment_fraction": max_increment,
                "maximum_learned_increment_linear_reflectivity_fraction": (
                    max_increment_linear
                ),
                "learned_increment_count_at_or_above_review_dbzh": (
                    high_increment_count
                ),
                "removed_protected_gate_count": removed_protected,
                "removed_upper_supported_gate_count": removed_upper,
                "learned_rescue_gate_count": learned_rescue,
                "upper_context_expected": bool(
                    upper_expected_count
                ),
                "upper_context_sweep_count": upper_context_count,
                "upper_context_expected_sweep_count": (
                    upper_expected_count
                ),
                "upper_context_missing_sweep_count": (
                    upper_expected_count - upper_context_count
                ),
                "upper_context_coverage_fraction": (
                    upper_context_coverage
                ),
                "increment_stability": stability,
                "state": state,
                "blockers": blockers,
                "review_reasons": review_reasons,
                "promotion_eligible": False,
            }
        )

    state_counts = dict(
        sorted(
            {
                state: sum(
                    target["state"] == state
                    for target in target_policies
                )
                for state in {
                    target["state"] for target in target_policies
                }
            }.items()
        )
    )
    return {
        "schema": BACKGROUND_VALIDATION_POLICY_SCHEMA,
        "schema_version": BACKGROUND_VALIDATION_POLICY_SCHEMA_VERSION,
        "generated_at": _now_utc(),
        "status": "frozen",
        "purpose": (
            "pre-holdout safety screen; rejection is permitted, promotion "
            "requires independent labels and cross-platform parity"
        ),
        "validation_results": str(source),
        "validation_results_sha256": file_sha256(source),
        "configuration_sha256": report["configuration_sha256"],
        "policy_config": asdict(config),
        "target_count": len(target_policies),
        "state_counts": state_counts,
        "holdout_scoring_target_count": len(target_policies),
        "promotion_eligible_target_count": 0,
        "targets": target_policies,
    }


def write_frozen_background_validation_policy(
    policy: dict[str, Any],
    path: str | Path,
) -> Path:
    """Write the frozen policy atomically."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            policy,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def _increment_stability(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    np = require_numpy()
    masks = []
    for record in records:
        artifact = Path(record["artifact_npz"])
        expected_hash = str(record.get("artifact_sha256") or "")
        if not expected_hash:
            raise ValueError(
                f"validation artifact hash is missing for {record['job_id']}"
            )
        if not artifact.is_file() or file_sha256(artifact) != expected_hash:
            raise ValueError(
                f"validation artifact hash mismatch for {record['job_id']}"
            )
        with np.load(artifact, allow_pickle=False) as loaded:
            if "learned_increment_mask" not in loaded.files:
                raise ValueError(
                    "validation artifact lacks learned_increment_mask for "
                    f"{record['job_id']}"
                )
            raw_mask = np.asarray(loaded["learned_increment_mask"])
        expected_shape = tuple(record.get("shape") or raw_mask.shape)
        if raw_mask.shape != expected_shape:
            raise ValueError(
                f"validation mask shape mismatch for {record['job_id']}"
            )
        if not np.isin(raw_mask, (0, 1)).all():
            raise ValueError(
                f"validation mask is not binary for {record['job_id']}"
            )
        masks.append(raw_mask.astype(bool))
    jaccards: list[float] = []
    for first_index, first in enumerate(masks):
        for second in masks[first_index + 1 :]:
            union = first | second
            if not union.any():
                continue
            jaccards.append(float((first & second).sum() / union.sum()))
    frequency = (
        np.stack(masks, axis=0).mean(axis=0)
        if masks
        else np.asarray([], dtype="float32")
    )
    return {
        "nonempty_pair_count": len(jaccards),
        "mean_nonempty_pairwise_jaccard": (
            float(np.mean(jaccards)) if jaccards else 1.0
        ),
        "minimum_nonempty_pairwise_jaccard": (
            float(np.min(jaccards)) if jaccards else 1.0
        ),
        "gate_count_seen_in_at_least_half_of_sweeps": (
            int((frequency >= 0.5).sum()) if frequency.size else 0
        ),
        "gate_count_seen_in_every_sweep": (
            int((frequency >= 1.0).sum()) if frequency.size else 0
        ),
    }


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
