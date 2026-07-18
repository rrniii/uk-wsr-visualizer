from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from uk_wsr_visualizer.background_failure_attribution import (
    build_background_failure_attribution,
    write_background_failure_attribution,
)
from uk_wsr_visualizer.background_training_pipeline import file_sha256
from uk_wsr_visualizer.qc_evidence import EvidenceFlag, NuisanceFlag


def test_failure_attribution_uses_exact_persisted_masks(
    tmp_path: Path,
) -> None:
    increment = np.asarray([[1, 0], [1, 0]], dtype="uint8")
    nuisance = np.zeros((2, 2), dtype="uint16")
    nuisance[increment.astype(bool)] = int(NuisanceFlag.STATIC_CLUTTER)
    evidence = np.zeros((2, 2), dtype="uint32")
    evidence[increment.astype(bool)] = (
        int(EvidenceFlag.LOW_CI)
        | int(EvidenceFlag.NEAR_ZERO_VELOCITY)
        | int(EvidenceFlag.LEARNED_PERSISTENCE)
    )
    artifact = tmp_path / "artifact.npz"
    np.savez_compressed(
        artifact,
        learned_increment_mask=increment,
        learned_nuisance_mask=nuisance,
        learned_evidence_mask=evidence,
    )
    record = {
        "job_id": "job",
        "target_id": "target",
        "radar": "chenies",
        "pulse": "lp",
        "quantity": "DBZH",
        "geometry_class": "ppi",
        "elevation_deg": 1.0,
        "artifact_npz": str(artifact),
        "artifact_sha256": file_sha256(artifact),
        "source": {
            "source_id": "source",
            "date": "20250101",
            "time": "0000",
        },
        "baseline": {
            "removed_fraction": 0.25,
            "removed_dbzh": {
                "linear_reflectivity_fraction": 0.01,
            },
            "nuisance_counts": {
                "receiver_noise": 3,
                "static_clutter": 0,
            },
        },
        "delta": {
            "learned_increment_count": 2,
            "learned_increment_fraction": 0.5,
            "learned_increment_dbzh": {
                "linear_reflectivity_fraction": 0.4,
            },
        },
    }
    validation_path = tmp_path / "validation.json"
    validation_path.write_text(
        json.dumps(
            {
                "split": "validation",
                "complete": True,
                "error_count": 0,
                "expected_job_count": 1,
                "configuration_sha256": "a" * 64,
                "records": [record],
            }
        ),
        encoding="utf-8",
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "validation_results_sha256": file_sha256(validation_path),
                "configuration_sha256": "a" * 64,
                "holdout_scoring_target_count": 0,
                "targets": [
                    {
                        "target_id": "target",
                        "state": "quarantined",
                        "blockers": ["missing temporal context"],
                        "review_reasons": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = build_background_failure_attribution(
        validation_path,
        policy_path,
    )
    outputs = write_background_failure_attribution(
        report,
        json_path=tmp_path / "attribution.json",
        markdown_path=tmp_path / "attribution.md",
        csv_path=tmp_path / "attribution.csv",
    )

    assert report["status"] == "rejected_before_holdout"
    assert report["blocker_counts"] == {"missing temporal context": 1}
    assert report["global_baseline_nuisance_counts"][
        "receiver_noise"
    ] == 3
    assert report["global_learned_increment_nuisance_counts"][
        "static_clutter"
    ] == 2
    assert report["global_learned_increment_evidence_counts"][
        "learned_persistence"
    ] == 2
    assert report["global_learned_increment_evidence_counts"][
        "near_zero_velocity"
    ] == 2
    assert all(path is not None and path.is_file() for path in outputs)
