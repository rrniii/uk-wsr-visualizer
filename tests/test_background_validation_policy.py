from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from uk_wsr_visualizer.background_validation_policy import (
    BackgroundValidationPolicyConfig,
    build_frozen_background_validation_policy,
    write_frozen_background_validation_policy,
)
from uk_wsr_visualizer.background_training_pipeline import file_sha256


def test_policy_requires_complete_validation(tmp_path: Path) -> None:
    path = tmp_path / "validation.json"
    path.write_text(
        json.dumps(
            {
                "split": "validation",
                "complete": False,
                "error_count": 0,
                "expected_job_count": 0,
                "records": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not complete"):
        build_frozen_background_validation_policy(path)


def test_policy_quarantines_invariant_failure_and_never_promotes(
    tmp_path: Path,
) -> None:
    artifact_paths = [
        _write_mask(tmp_path / f"mask-{index}.npz", index)
        for index in range(7)
    ]
    records = [
        _record(
            artifact_path,
            time=f"{index:02d}00",
            removed_protected=1 if index == 0 else 0,
        )
        for index, artifact_path in enumerate(artifact_paths)
    ]
    report_path = tmp_path / "validation.json"
    report_path.write_text(
        json.dumps(
            {
                "split": "validation",
                "complete": True,
                "error_count": 0,
                "expected_job_count": 7,
                "configuration_sha256": "a" * 64,
                "records": records,
            }
        ),
        encoding="utf-8",
    )

    policy = build_frozen_background_validation_policy(report_path)
    output = write_frozen_background_validation_policy(
        policy,
        tmp_path / "policy.json",
    )

    assert policy["status"] == "frozen"
    assert policy["state_counts"] == {"quarantined": 1}
    assert policy["promotion_eligible_target_count"] == 0
    assert "candidate removed protected gates" in policy["targets"][0][
        "blockers"
    ]
    assert output.is_file()


def test_policy_allows_one_missing_upper_context_with_fail_open(
    tmp_path: Path,
) -> None:
    artifact_paths = [
        _write_mask(tmp_path / f"mask-{index}.npz", 0)
        for index in range(8)
    ]
    records = [
        _record(
            artifact_path,
            time=f"{index:02d}00",
            removed_protected=0,
            upper_expected=True,
            upper_available=index != 3,
        )
        for index, artifact_path in enumerate(artifact_paths)
    ]
    report_path = _write_report(tmp_path, records)

    policy = build_frozen_background_validation_policy(report_path)
    target = policy["targets"][0]

    assert target["state"] == "requires_blinded_review"
    assert not target["blockers"]
    assert target["upper_context_coverage_fraction"] == pytest.approx(7 / 8)
    assert target["upper_context_missing_sweep_count"] == 1
    assert "partial volumes use learned-clutter fail-open" in target[
        "review_reasons"
    ]


def test_policy_quarantines_inadequate_upper_context_coverage(
    tmp_path: Path,
) -> None:
    artifact_paths = [
        _write_mask(tmp_path / f"mask-{index}.npz", 0)
        for index in range(8)
    ]
    records = [
        _record(
            artifact_path,
            time=f"{index:02d}00",
            removed_protected=0,
            upper_expected=True,
            upper_available=index < 5,
        )
        for index, artifact_path in enumerate(artifact_paths)
    ]
    report_path = _write_report(tmp_path, records)

    policy = build_frozen_background_validation_policy(
        report_path,
        config=BackgroundValidationPolicyConfig(
            minimum_expected_upper_context_coverage_fraction=0.75
        ),
    )

    assert policy["targets"][0]["state"] == "quarantined"
    assert (
        "expected upper-elevation context coverage is inadequate"
        in policy["targets"][0]["blockers"]
    )


def test_policy_rejects_corrupt_persisted_mask(tmp_path: Path) -> None:
    artifact = _write_mask(tmp_path / "mask.npz", 0)
    record = _record(
        artifact,
        time="0000",
        removed_protected=0,
    )
    records = [dict(record) for _ in range(7)]
    for index, selected in enumerate(records):
        selected["job_id"] = f"target-{index}"
        selected["source"] = dict(selected["source"]) | {
            "source_id": f"source-{index}",
            "date": f"202501{index + 1:02d}",
        }
    report_path = _write_report(tmp_path, records)
    artifact.write_bytes(b"corrupt")

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        build_frozen_background_validation_policy(report_path)


def _write_mask(path: Path, offset: int) -> Path:
    mask = np.zeros((5, 5), dtype="uint8")
    mask[2, min(4, offset % 5)] = 1
    np.savez_compressed(path, learned_increment_mask=mask)
    return path


def _record(
    artifact_path: Path,
    *,
    time: str,
    removed_protected: int,
    upper_expected: bool = False,
    upper_available: bool = False,
) -> dict:
    removed_dbzh = {
        "linear_reflectivity_fraction": 0.02,
        "count_at_or_above_dbzh": {"20": 1},
    }
    return {
        "job_id": f"target-{time}",
        "target_id": "target",
        "radar": "chenies",
        "pulse": "lp",
        "quantity": "DBZH",
        "geometry_class": "ppi",
        "elevation_deg": 4.0,
        "shape": [5, 5],
        "artifact_npz": str(artifact_path),
        "artifact_sha256": file_sha256(artifact_path),
        "configuration_sha256": "a" * 64,
        "source": {
            "source_id": f"source-{time}",
            "date": f"202501{int(time[:2]) + 1:02d}",
            "time": time,
        },
        "context": {
            "upper_elevation_available": upper_available,
            "upper_elevation_expected": upper_expected,
        },
        "learned": {
            "finite_count": 25,
            "removed_fraction": 0.1,
            "removed_protected_count": removed_protected,
            "removed_upper_supported_count": 0,
        },
        "delta": {
            "learned_increment_count": 1,
            "learned_increment_fraction": 0.04,
            "learned_increment_dbzh": removed_dbzh,
            "learned_rescue_count": 0,
        },
    }


def _write_report(tmp_path: Path, records: list[dict]) -> Path:
    report_path = tmp_path / "validation.json"
    report_path.write_text(
        json.dumps(
            {
                "split": "validation",
                "complete": True,
                "error_count": 0,
                "expected_job_count": len(records),
                "configuration_sha256": "a" * 64,
                "records": records,
            }
        ),
        encoding="utf-8",
    )
    return report_path
