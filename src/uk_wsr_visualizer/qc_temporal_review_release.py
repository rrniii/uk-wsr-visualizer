"""Fail-closed release assessment for blinded temporal QC review."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .qc_benchmark import LABEL_TAXONOMY, canonical_json_sha256
from .qc_temporal_review import TEMPORAL_REVIEW_ID, TEMPORAL_REVIEW_SCHEMA


RELEASE_SCHEMA = "uk_wsr_qc_temporal_review_release"
RELEASE_SCHEMA_VERSION = 1


def assess_temporal_review_release(
    review: Mapping[str, Any],
    *,
    primary: Mapping[str, Any] | None,
    secondary: Mapping[str, Any] | None,
    adjudicated: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess human labels against learned-only removals without auto-promotion.

    A candidate is approved only when both blinded reviews are complete and
    agree, or an adjudicated review resolves their difference; every learned
    increment gate must then be labelled ``remove``.  Any overlap with a
    retained label rejects the candidate.  Missing evidence remains pending.
    """

    _validate_review(review)
    expected_ids = {str(item["target_id"]) for item in review["targets"]}
    stages = {
        "primary": _annotation_items(primary, "primary", review, expected_ids),
        "secondary": _annotation_items(secondary, "secondary", review, expected_ids),
        "adjudicated": _annotation_items(
            adjudicated, "adjudicated", review, expected_ids, required=False
        ),
    }

    outcomes = []
    for target in review["targets"]:
        target_id = str(target["target_id"])
        primary_item = stages["primary"].get(target_id)
        secondary_item = stages["secondary"].get(target_id)
        adjudicated_item = stages["adjudicated"].get(target_id)
        outcome = _assess_target(
            target,
            primary_item=primary_item,
            secondary_item=secondary_item,
            adjudicated_item=adjudicated_item,
        )
        outcomes.append(outcome)

    geometry_states: dict[str, list[str]] = {}
    for outcome in outcomes:
        if outcome["selection_role_internal"] != "candidate_challenge":
            continue
        geometry_states.setdefault(outcome["geometry_id"], []).append(
            outcome["state"]
        )
    geometry_outcomes = [
        {
            "geometry_id": geometry_id,
            "state": _aggregate_state(states),
            "candidate_target_count": len(states),
        }
        for geometry_id, states in sorted(geometry_states.items())
    ]
    counts = Counter(item["state"] for item in outcomes)
    geometry_counts = Counter(item["state"] for item in geometry_outcomes)
    return {
        "schema": RELEASE_SCHEMA,
        "schema_version": RELEASE_SCHEMA_VERSION,
        "review_id": TEMPORAL_REVIEW_ID,
        "review_targets_sha256": canonical_json_sha256(review),
        "generated_at": _now_utc(),
        "release_policy": {
            "automatic_promotion": False,
            "require_primary_and_secondary": True,
            "require_adjudication_on_disagreement": True,
            "retain_overlap_action": "reject",
            "unlabelled_learned_increment_action": "pending",
        },
        "review_completion": {
            stage: len(items) for stage, items in stages.items()
        },
        "target_count": len(outcomes),
        "candidate_target_count": sum(
            item["selection_role_internal"] == "candidate_challenge"
            for item in outcomes
        ),
        "target_state_counts": dict(sorted(counts.items())),
        "geometry_count": len(geometry_outcomes),
        "geometry_state_counts": dict(sorted(geometry_counts.items())),
        "promotion_eligible_target_count": 0,
        "promotion_eligible_model_count": 0,
        "outcomes": outcomes,
        "geometry_outcomes": geometry_outcomes,
    }


def write_temporal_review_release(
    release: Mapping[str, Any], path: str | Path) -> Path:
    """Write a canonical release assessment without mutating model manifests."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(release, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def _validate_review(review: Mapping[str, Any]) -> None:
    if review.get("schema") != TEMPORAL_REVIEW_SCHEMA:
        raise ValueError("temporal review-target schema mismatch")
    if review.get("review_id") != TEMPORAL_REVIEW_ID:
        raise ValueError("temporal review id mismatch")
    if review.get("selection", {}).get("sealed_holdout_opened") is not False:
        raise ValueError("sealed holdout must remain closed during review")


def _annotation_items(
    annotation: Mapping[str, Any] | None,
    stage: str,
    review: Mapping[str, Any],
    expected_ids: set[str],
    *,
    required: bool = True,
) -> dict[str, Mapping[str, Any]]:
    if annotation is None:
        if required:
            return {}
        return {}
    if annotation.get("review_id") != TEMPORAL_REVIEW_ID:
        raise ValueError(f"{stage}: temporal review id mismatch")
    if annotation.get("review_stage") != stage:
        raise ValueError(f"{stage}: annotation stage mismatch")
    if annotation.get("review_targets_sha256") != canonical_json_sha256(review):
        raise ValueError(f"{stage}: review-target hash mismatch")
    policy = annotation.get("review_policy") or {}
    for field in (
        "qc_outputs_visible",
        "ci_used_as_ground_truth",
        "selection_identity_visible",
        "reported_failure_visible",
        "sealed_holdout_opened",
    ):
        if policy.get(field) is not False:
            raise ValueError(f"{stage}: invalid review policy {field}")
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in annotation.get("items", ()):
        target_id = str(item.get("target_id") or "")
        if target_id not in expected_ids:
            raise ValueError(f"{stage}: unknown target {target_id}")
        if target_id in indexed:
            raise ValueError(f"{stage}: duplicate target {target_id}")
        if item.get("review_stage") != stage:
            raise ValueError(f"{stage}: item stage mismatch")
        if any(
            item.get(field) is not False
            for field in (
                "qc_outputs_visible",
                "ci_used_as_ground_truth",
                "selection_identity_visible",
                "reported_failure_visible",
                "sealed_holdout_opened",
            )
        ):
            raise ValueError(f"{stage}: item violates blinded review policy")
        indexed[target_id] = item
    return indexed


def _assess_target(
    target: Mapping[str, Any],
    *,
    primary_item: Mapping[str, Any] | None,
    secondary_item: Mapping[str, Any] | None,
    adjudicated_item: Mapping[str, Any] | None,
) -> dict[str, Any]:
    shape = tuple(int(value) for value in target["shape"])
    result = {
        "target_id": str(target["target_id"]),
        "geometry_id": str(target["geometry_id"]),
        "selection_role_internal": str(target["selection_role_internal"]),
        "state": "pending",
        "reason": "incomplete_double_review",
        "learned_increment_gate_count": 0,
        "remove_support_gate_count": 0,
        "retain_overlap_gate_count": 0,
        "unlabelled_increment_gate_count": 0,
        "review_disagreement_gate_count": 0,
    }
    if primary_item is None or secondary_item is None:
        return result
    increment = _load_increment_mask(target, shape)
    primary = _action_masks(primary_item, shape)
    secondary = _action_masks(secondary_item, shape)
    disagreement = increment & (primary["remove"] != secondary["remove"])
    disagreement |= increment & (primary["retain"] != secondary["retain"])
    selected = primary
    if disagreement.any():
        if adjudicated_item is None:
            result["reason"] = "review_disagreement_requires_adjudication"
            result["review_disagreement_gate_count"] = int(disagreement.sum())
            return result
        selected = _action_masks(adjudicated_item, shape)
    retain_overlap = increment & selected["retain"]
    remove_support = increment & selected["remove"] & ~selected["retain"]
    unlabelled = increment & ~selected["remove"] & ~selected["retain"]
    result.update(
        {
            "learned_increment_gate_count": int(increment.sum()),
            "remove_support_gate_count": int(remove_support.sum()),
            "retain_overlap_gate_count": int(retain_overlap.sum()),
            "unlabelled_increment_gate_count": int(unlabelled.sum()),
            "review_disagreement_gate_count": int(disagreement.sum()),
        }
    )
    if retain_overlap.any():
        result.update(state="rejected", reason="learned_increment_overlaps_retain")
    elif unlabelled.any():
        result.update(state="pending", reason="learned_increment_not_labelled_remove")
    else:
        result.update(state="approved", reason="reviewed_learned_increment_supported")
    return result


def _load_increment_mask(target: Mapping[str, Any], shape: tuple[int, int]):
    import numpy as np

    artifact = target.get("scoring_artifact") or {}
    path = Path(str(artifact.get("npz") or ""))
    if not path.exists():
        raise ValueError(f"missing scoring artifact for {target['target_id']}")
    with np.load(path) as arrays:
        if "learned_increment_mask" not in arrays:
            raise ValueError(f"missing learned increment mask for {target['target_id']}")
        values = np.asarray(arrays["learned_increment_mask"], dtype=bool)
    if values.shape != shape:
        raise ValueError(f"learned increment shape mismatch for {target['target_id']}")
    return values


def _action_masks(item: Mapping[str, Any], shape: tuple[int, int]):
    import numpy as np

    remove = np.zeros(shape, dtype=bool)
    retain = np.zeros(shape, dtype=bool)
    for region in item.get("regions", ()):
        taxonomy = LABEL_TAXONOMY.get(str(region.get("label") or ""))
        if taxonomy is None:
            raise ValueError(f"unknown annotation label {region.get('label')!r}")
        mask = _region_mask(region.get("geometry"), shape)
        if taxonomy["action"] == "remove":
            remove |= mask
        else:
            retain |= mask
    return {"remove": remove, "retain": retain}


def _region_mask(geometry: Any, shape: tuple[int, int]):
    import numpy as np

    if not isinstance(geometry, Mapping):
        raise ValueError("annotation geometry must be an object")
    nrays, nbins = shape
    kind = geometry.get("type")
    if kind == "full_sweep":
        return np.ones(shape, dtype=bool)
    mask = np.zeros(shape, dtype=bool)
    if kind == "row_major_rle":
        for offset, length in geometry.get("runs", ()):
            offsets = np.arange(int(offset), int(offset) + int(length))
            mask.flat[offsets] = True
        return mask
    if kind != "polar_gate_polygon":
        raise ValueError(f"unsupported annotation geometry {kind!r}")
    vertices = geometry.get("vertices") or []
    if len(vertices) < 3:
        raise ValueError("polar polygon requires at least three vertices")
    rays, gates = np.indices(shape, dtype=float)
    x = rays + 0.5
    y = gates + 0.5
    inside = np.zeros(shape, dtype=bool)
    previous_x, previous_y = (float(value) for value in vertices[-1])
    for current in vertices:
        current_x, current_y = (float(value) for value in current)
        intersects = ((current_y > y) != (previous_y > y)) & (
            x < (previous_x - current_x) * (y - current_y) /
            ((previous_y - current_y) or 1.0e-12) + current_x
        )
        inside ^= intersects
        previous_x, previous_y = current_x, current_y
    return inside


def _aggregate_state(states: list[str]) -> str:
    if "rejected" in states:
        return "rejected"
    if states and all(state == "approved" for state in states):
        return "approved"
    return "pending"


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
