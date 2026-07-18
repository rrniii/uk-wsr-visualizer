from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from uk_wsr_visualizer.background_model import (
    BACKGROUND_MODEL_ARRAY_NAMES,
    BackgroundModel,
    hash_arrays,
)
from uk_wsr_visualizer.background_training_audit import (
    audit_background_training_run,
    write_background_training_audit,
)
from uk_wsr_visualizer.background_training_pipeline import (
    _write_research_model,
)


def test_training_audit_verifies_model_contract(tmp_path: Path) -> None:
    inventory_path, results_path, model_dir = _write_audit_fixture(tmp_path)

    audit = audit_background_training_run(
        inventory_path,
        results_path,
    )
    output_path = write_background_training_audit(
        audit,
        tmp_path / "audit.json",
    )

    assert audit["status"] == "passed"
    assert audit["audited_model_count"] == 1
    assert audit["passed_model_count"] == 1
    assert audit["artifact_file_count"] == 2
    assert audit["conditioned_support_by_geometry"]["ppi"][
        "target_count"
    ] == 1
    assert output_path.is_file()


def test_training_audit_rejects_tampered_arrays(tmp_path: Path) -> None:
    inventory_path, results_path, model_dir = _write_audit_fixture(tmp_path)
    npz_path = model_dir / "chenies_lp_dbzh_e01000_2x3_r0m_s600000mm.npz"
    with np.load(npz_path) as loaded:
        arrays = {name: loaded[name] for name in loaded.files}
    arrays["persistent_echo_frequency"] = np.full(
        (2, 3),
        2.0,
        dtype="float32",
    )
    np.savez_compressed(npz_path, **arrays)

    audit = audit_background_training_run(
        inventory_path,
        results_path,
    )

    assert audit["status"] == "failed"
    messages = [item["error"] for item in audit["errors"]]
    assert "manifest array hash does not verify" in messages
    assert "persistent_echo_frequency is outside [0, 1]" in messages


def _write_audit_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    target_id = "chenies_lp_dbzh_e01000_2x3_r0m_s600000mm"
    shape = (2, 3)
    arrays = {
        name: np.ones(shape, dtype="float32")
        for name in BACKGROUND_MODEL_ARRAY_NAMES
    }
    arrays["dbzh_p10"][:] = 1.0
    arrays["dbzh_median"][:] = 2.0
    arrays["dbzh_p90"][:] = 3.0
    model = BackgroundModel(
        key={
            "radar": "chenies",
            "pulse": "lp",
            "quantity": "DBZH",
            "dataset": "dataset1",
            "dataset_aliases": ["dataset1"],
            "elevation_deg": 1.0,
            "nrays": 2,
            "nbins": 3,
            "rstart_km": 0.0,
            "rscale_m": 600.0,
            "geometry_id": target_id,
        },
        shape=shape,
        arrays=arrays,
        metadata={
            "source_manifest_sha256": "a" * 64,
            "download_ledger_sha256": "b" * 64,
            "source_count": 1,
            "source_date_count": 1,
            "source_dates": ["20230101"],
            "training_source_ids": ["source-1"],
            "training_source_sha256": ["c" * 64],
            "split_source_counts": {
                "training": 1,
                "validation": 1,
                "holdout": 1,
            },
            "companion_coverage": {"CI": 1, "VRADH": 1},
            "promotion_eligible": False,
        },
        array_hash=hash_arrays(arrays),
    )
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    _write_research_model(
        model,
        model_dir / f"{target_id}.npz",
        model_dir / f"{target_id}.json",
    )

    inventory = {
        "source_manifest_sha256": "a" * 64,
        "download_ledger_sha256": "b" * 64,
        "target_count": 1,
        "targets": [
            {
                "target_id": target_id,
                "radar": "chenies",
                "pulse": "lp",
                "quantity": "DBZH",
                "elevation_deg": 1.0,
                "shape": [2, 3],
                "rstart_km": 0.0,
                "rscale_m": 600.0,
                "dataset_aliases": ["dataset1"],
                "source_counts": {
                    "training": 1,
                    "validation": 1,
                    "holdout": 1,
                },
                "date_counts": {
                    "training": 1,
                    "validation": 1,
                    "holdout": 1,
                },
            }
        ],
    }
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    results = {
        "complete": True,
        "source_manifest_sha256": "a" * 64,
        "download_ledger_sha256": "b" * 64,
        "model_dir": str(model_dir),
        "target_count": 1,
        "error_count": 0,
        "errors": [],
        "models": [
            {
                "target_id": target_id,
                "model_array_hash": model.array_hash,
                "conditioned_support_gate_fraction": 0.0,
                "promotion_eligible": False,
            }
        ],
    }
    results_path = tmp_path / "training_results.json"
    results_path.write_text(json.dumps(results), encoding="utf-8")
    return inventory_path, results_path, model_dir
