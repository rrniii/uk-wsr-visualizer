from __future__ import annotations

import json

import numpy as np

from uk_wsr_visualizer.qc_benchmark import canonical_json_sha256
from uk_wsr_visualizer.qc_temporal_review import (
    TEMPORAL_REVIEW_ID,
    TEMPORAL_REVIEW_SCHEMA,
)
from uk_wsr_visualizer.qc_temporal_review_release import (
    assess_temporal_review_release,
)


def _review(tmp_path):
    artifact = tmp_path / "target.npz"
    np.savez(artifact, learned_increment_mask=np.array([[True, False], [False, False]]))
    return {
        "schema": TEMPORAL_REVIEW_SCHEMA,
        "review_id": TEMPORAL_REVIEW_ID,
        "selection": {"sealed_holdout_opened": False},
        "targets": [{
            "target_id": "target-1",
            "geometry_id": "geometry-1",
            "selection_role_internal": "candidate_challenge",
            "shape": [2, 2],
            "scoring_artifact": {"npz": str(artifact)},
        }],
    }


def _annotation(review, stage, label):
    return {
        "review_id": TEMPORAL_REVIEW_ID,
        "review_targets_sha256": canonical_json_sha256(review),
        "review_stage": stage,
        "review_policy": {
            "qc_outputs_visible": False,
            "ci_used_as_ground_truth": False,
            "selection_identity_visible": False,
            "reported_failure_visible": False,
            "sealed_holdout_opened": False,
        },
        "items": [{
            "target_id": "target-1",
            "review_stage": stage,
            "qc_outputs_visible": False,
            "ci_used_as_ground_truth": False,
            "selection_identity_visible": False,
            "reported_failure_visible": False,
            "sealed_holdout_opened": False,
            "regions": [{
                "region_id": "all",
                "label": label,
                "geometry": {"type": "full_sweep"},
            }],
        }],
    }


def test_release_requires_remove_support_for_every_learned_increment(tmp_path):
    review = _review(tmp_path)
    primary = _annotation(review, "primary", "static_ground_clutter")
    release = assess_temporal_review_release(review, primary=primary)

    assert release["geometry_state_counts"] == {"approved": 1}
    assert release["promotion_eligible_model_count"] == 0


def test_release_rejects_retained_echo_overlap(tmp_path):
    review = _review(tmp_path)
    primary = _annotation(review, "primary", "precipitation")
    release = assess_temporal_review_release(review, primary=primary)

    assert release["geometry_state_counts"] == {"rejected": 1}
    assert release["outcomes"][0]["retain_overlap_gate_count"] == 1


def test_release_requires_adjudication_for_disagreement(tmp_path):
    review = _review(tmp_path)
    review["selection"]["required_reviewer_count"] = 2
    primary = _annotation(review, "primary", "static_ground_clutter")
    secondary = _annotation(review, "secondary", "precipitation")

    release = assess_temporal_review_release(
        review, primary=primary, secondary=secondary
    )

    assert release["geometry_state_counts"] == {"pending": 1}
    assert release["outcomes"][0]["reason"] == "review_disagreement_requires_adjudication"
