from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from uk_wsr_visualizer.background_validation_audit import (
    audit_background_validation_run,
    write_background_validation_audit,
)
from uk_wsr_visualizer.background_validation_pipeline import (
    BackgroundValidationEvaluation,
    validation_configuration_contract,
    write_background_validation_artifact,
    write_background_validation_report,
)
from uk_wsr_visualizer.qc_evidence import EvidenceConfig


def test_validation_audit_verifies_artifacts_and_invariants(
    tmp_path: Path,
) -> None:
    report_path, _ = _write_fixture(tmp_path)

    audit = audit_background_validation_run(report_path)
    output = write_background_validation_audit(
        audit,
        tmp_path / "audit.json",
    )

    assert audit["status"] == "passed"
    assert audit["audited_record_count"] == 1
    assert audit["passed_record_count"] == 1
    assert audit["error_count"] == 0
    assert output.is_file()


def test_validation_audit_rejects_tampered_artifact(
    tmp_path: Path,
) -> None:
    report_path, artifact_path = _write_fixture(tmp_path)
    artifact_path.write_bytes(b"tampered")

    audit = audit_background_validation_run(report_path)

    assert audit["status"] == "failed"
    assert any(
        error["error"] == "artifact file hash does not verify"
        for error in audit["errors"]
    )


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    shape = (2, 3)
    raw = np.asarray(
        [[1.0, 2.0, np.nan], [3.0, 4.0, 5.0]],
        dtype="float32",
    )
    baseline = np.zeros(shape, dtype=bool)
    baseline[0, 0] = True
    learned = baseline.copy()
    learned[1, 0] = True
    increment = learned & ~baseline
    arrays = {
        "dbzh_raw": raw,
        "dbzh_baseline_cleaned": np.where(
            baseline,
            np.nan,
            raw,
        ).astype("float32"),
        "dbzh_learned_cleaned": np.where(
            learned,
            np.nan,
            raw,
        ).astype("float32"),
        "baseline_remove_mask": baseline.astype("uint8"),
        "baseline_nuisance_mask": baseline.astype("uint16"),
        "baseline_evidence_mask": np.zeros(shape, dtype="uint32"),
        "baseline_protected_mask": np.zeros(shape, dtype="uint8"),
        "baseline_confidence": baseline.astype("float32"),
        "baseline_noise_profile": np.zeros(shape[1], dtype="float32"),
        "learned_remove_mask": learned.astype("uint8"),
        "learned_nuisance_mask": learned.astype("uint16"),
        "learned_evidence_mask": np.zeros(shape, dtype="uint32"),
        "learned_protected_mask": np.zeros(shape, dtype="uint8"),
        "learned_confidence": learned.astype("float32"),
        "learned_noise_profile": np.zeros(shape[1], dtype="float32"),
        "learned_increment_mask": increment.astype("uint8"),
    }
    configuration, configuration_hash = validation_configuration_contract(
        EvidenceConfig(),
        max_temporal_gap_minutes=20,
    )
    empty_removed = {
        "count": 0,
        "minimum": None,
        "median": None,
        "p90": None,
        "maximum": None,
        "linear_reflectivity_fraction": 0.0,
        "count_at_or_above_dbzh": {
            key: 0 for key in ("0", "5", "10", "15", "20", "30")
        },
        "input_count_at_or_above_dbzh": {
            key: 0 for key in ("0", "5", "10", "15", "20", "30")
        },
    }
    nuisance_counts = {
        key: 0
        for key in (
            "receiver_noise",
            "static_clutter",
            "anomalous_propagation",
            "radial_interference",
            "isolated_speckle",
        )
    }
    record = {
        "schema": "uk_wsr_background_validation",
        "schema_version": 1,
        "job_id": "target__source",
        "split": "validation",
        "target_id": "target",
        "radar": "chenies",
        "pulse": "lp",
        "quantity": "DBZH",
        "geometry_class": "ppi",
        "elevation_deg": 1.0,
        "shape": list(shape),
        "rstart_km": 0.0,
        "rscale_m": 600.0,
        "dataset_aliases": ["dataset1"],
        "source": {
            "source_id": "source",
            "sha256": "a" * 64,
            "date": "20250101",
            "time": "0000",
            "dataset": "dataset1",
            "field_group": "data1",
        },
        "model": {
            "array_hash": "b" * 64,
            "geometry_id": "target",
            "source_manifest_sha256": "c" * 64,
            "download_ledger_sha256": "d" * 64,
            "promotion_eligible": False,
        },
        "configuration_sha256": configuration_hash,
        "companions": [],
        "context": {
            "upper_elevation": None,
            "previous": None,
            "next": None,
            "temporal_available": False,
            "upper_elevation_available": False,
            "upper_elevation_expected": False,
            "learned_background_available": True,
        },
        "baseline": {
            "finite_count": 5,
            "removed_count": 1,
            "removed_fraction": 0.2,
            "protected_count": 0,
            "removed_protected_count": 0,
            "upper_supported_count": 0,
            "removed_upper_supported_count": 0,
            "removed_dbzh": empty_removed,
            "nuisance_counts": nuisance_counts,
            "evidence_counts": {},
        },
        "learned": {
            "finite_count": 5,
            "removed_count": 2,
            "removed_fraction": 0.4,
            "protected_count": 0,
            "removed_protected_count": 0,
            "upper_supported_count": 0,
            "removed_upper_supported_count": 0,
            "removed_dbzh": empty_removed,
            "nuisance_counts": nuisance_counts,
            "evidence_counts": {},
        },
        "delta": {
            "learned_increment_count": 1,
            "learned_increment_fraction": 0.2,
            "learned_increment_dbzh": empty_removed,
            "learned_rescue_count": 0,
            "mask_disagreement_count": 1,
        },
        "status": "scored_research_artifact",
        "promotion_eligible": False,
    }
    evaluation = BackgroundValidationEvaluation(
        record=record,
        arrays=arrays,
    )
    artifact_root = tmp_path / "artifacts"
    npz_path, sidecar_path, sidecar = (
        write_background_validation_artifact(
            evaluation,
            artifact_root,
            configuration_contract=configuration,
        )
    )
    complete_record = record | {
        "artifact_npz": str(npz_path),
        "artifact_sidecar": str(sidecar_path),
        "artifact_sha256": sidecar["artifact_sha256"],
        "artifact_array_hash": sidecar["array_hash"],
        "resumed": False,
    }
    report_path = tmp_path / "validation.json"
    write_background_validation_report(
        report_path,
        split="validation",
        expected_job_count=1,
        records=[complete_record],
        errors=[],
        configuration_contract=configuration,
        configuration_sha256=configuration_hash,
        artifact_root=artifact_root,
        all_jobs_attempted=True,
    )
    return report_path, npz_path
