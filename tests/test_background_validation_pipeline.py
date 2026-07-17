from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from uk_wsr_visualizer.background_model import BackgroundModel, hash_arrays
from uk_wsr_visualizer.background_training_pipeline import (
    BackgroundTrainingTarget,
    SweepDescriptor,
)
from uk_wsr_visualizer.background_validation_pipeline import (
    BackgroundValidationEvaluation,
    build_background_validation_jobs,
    evaluate_background_validation_job,
    load_resumable_validation_record,
    summarise_background_validation,
    validation_configuration_contract,
    write_background_validation_artifact,
)
from uk_wsr_visualizer.qc_evidence import EvidenceConfig


def test_validation_jobs_select_only_nearby_and_same_volume_context() -> None:
    low_sweeps = (
        _sweep("volume-a", "dataset1", 1.0, "0000"),
        _sweep("volume-b", "dataset1", 1.0, "0010"),
        _sweep("volume-c", "dataset1", 1.0, "1200"),
    )
    upper_sweeps = (
        _sweep("volume-a", "dataset2", 2.0, "0000"),
        _sweep("volume-b", "dataset2", 2.0, "0010"),
        _sweep("volume-c", "dataset2", 2.0, "1200"),
    )
    low = _target("low", 1.0, low_sweeps)
    upper = _target("upper", 2.0, upper_sweeps)

    jobs = build_background_validation_jobs(
        (low, upper),
        split="validation",
        max_temporal_gap_minutes=20,
    )
    low_jobs = {
        job.sweep.source_id: job
        for job in jobs
        if job.target.target_id == "low"
    }

    assert len(jobs) == 6
    assert low_jobs["volume-a"].upper_sweep == upper_sweeps[0]
    assert low_jobs["volume-a"].upper_elevation_expected is True
    assert low_jobs["volume-a"].next_sweep == low_sweeps[1]
    assert low_jobs["volume-b"].previous_sweep == low_sweeps[0]
    assert low_jobs["volume-b"].next_sweep is None
    assert low_jobs["volume-c"].previous_sweep is None


def test_evaluation_adds_only_supported_learned_clutter(
    monkeypatch,
) -> None:
    shape = (5, 5)
    sweep = _sweep("volume-a", "dataset1", 1.0, "0000")
    target = _target("target", 1.0, (sweep,))
    job = build_background_validation_jobs(
        (target,),
        split="validation",
    )[0]
    values = np.full(shape, 10.0, dtype="float32")
    companions = {
        "CI": np.full(shape, 1.0, dtype="float32"),
        "VRADH": np.zeros(shape, dtype="float32"),
        "SQIH": np.full(shape, 0.8, dtype="float32"),
        "RHOHV": np.full(shape, 0.95, dtype="float32"),
        "ZDR": np.full(shape, 1.0, dtype="float32"),
        "PHIDP": np.full(shape, 10.0, dtype="float32"),
    }
    metadata = SimpleNamespace(
        elevation_deg=1.0,
        rstart_km=0.0,
        rscale_m=600.0,
    )

    def fake_read(*args, **kwargs):
        del args, kwargs
        return values, metadata, companions

    monkeypatch.setattr(
        "uk_wsr_visualizer.background_validation_pipeline."
        "read_polar_field_with_companions",
        fake_read,
    )
    model_arrays = {
        "low_ci_sample_count": np.full(
            shape,
            48.0,
            dtype="float32",
        ),
        "low_ci_vrad_sample_count": np.full(
            shape,
            48.0,
            dtype="float32",
        ),
        "low_ci_persistent_echo_frequency": np.ones(
            shape,
            dtype="float32",
        ),
        "low_ci_near_zero_vrad_frequency": np.ones(
            shape,
            dtype="float32",
        ),
        "dbzh_p90": np.full(shape, 12.0, dtype="float32"),
    }
    model = BackgroundModel(
        key={"geometry_id": "target"},
        shape=shape,
        arrays=model_arrays,
        metadata={},
        array_hash=hash_arrays(model_arrays),
    )
    config = EvidenceConfig()
    _, config_hash = validation_configuration_contract(
        config,
        max_temporal_gap_minutes=20,
    )

    evaluation = evaluate_background_validation_job(
        job,
        model,
        config=config,
        configuration_sha256=config_hash,
    )

    assert evaluation.record["baseline"]["removed_count"] == 0
    assert evaluation.record["learned"]["removed_count"] == 25
    assert evaluation.record["delta"]["learned_increment_count"] == 25
    assert not evaluation.record["promotion_eligible"]


def test_validation_artifact_is_hash_verified_for_resume(
    tmp_path: Path,
) -> None:
    config = EvidenceConfig()
    contract, config_hash = validation_configuration_contract(
        config,
        max_temporal_gap_minutes=20,
    )
    record = {
        "split": "validation",
        "target_id": "target",
        "source": {
            "source_id": "source",
            "sha256": "a" * 64,
        },
        "model": {"array_hash": "b" * 64},
        "configuration_sha256": config_hash,
    }
    arrays = {
        "dbzh_raw": np.arange(6, dtype="float32").reshape(2, 3),
        "learned_remove_mask": np.zeros((2, 3), dtype="uint8"),
    }
    evaluation = BackgroundValidationEvaluation(
        record=record,
        arrays=arrays,
    )

    _, sidecar_path, _ = write_background_validation_artifact(
        evaluation,
        tmp_path,
        configuration_contract=contract,
    )
    resumed = load_resumable_validation_record(
        sidecar_path,
        source_sha256="a" * 64,
        model_array_hash="b" * 64,
        configuration_sha256=config_hash,
    )

    assert resumed is not None
    assert resumed["resumed"] is True
    assert resumed["artifact_sha256"]


def test_validation_summary_separates_geometry() -> None:
    record = _summary_record()
    summary = summarise_background_validation(
        (
            record,
            dict(record)
            | {
                "job_id": "vertical",
                "target_id": "vertical",
                "geometry_class": "vertical",
                "pulse": "sp",
                "source": dict(record["source"])
                | {"source_id": "source-2"},
            },
        )
    )

    assert summary["record_count"] == 2
    assert summary["groups"]["ppi"]["sweep_count"] == 1
    assert summary["groups"]["vertical"]["sweep_count"] == 1
    assert summary["promotion_eligible"] is False


def _target(
    target_id: str,
    elevation: float,
    sweeps: tuple[SweepDescriptor, ...],
) -> BackgroundTrainingTarget:
    return BackgroundTrainingTarget(
        target_id=target_id,
        radar="chenies",
        pulse="lp",
        quantity="DBZH",
        elevation_deg=elevation,
        nrays=5,
        nbins=5,
        rstart_km=0.0,
        rscale_m=600.0,
        dataset_aliases=tuple(
            sorted({sweep.dataset for sweep in sweeps})
        ),
        sweeps=sweeps,
    )


def _sweep(
    source_id: str,
    dataset: str,
    elevation: float,
    time: str,
) -> SweepDescriptor:
    return SweepDescriptor(
        source_id=source_id,
        radar="chenies",
        pulse="lp",
        split="validation",
        date="20250101",
        time=time,
        local_path="/tmp/unused.h5",
        sha256="a" * 64,
        dataset=dataset,
        field_group=f"{dataset}/data1",
        quantity="DBZH",
        elevation_deg=elevation,
        nrays=5,
        nbins=5,
        rstart_km=0.0,
        rscale_m=600.0,
        companion_quantities=("CI", "VRADH"),
    )


def _summary_record() -> dict:
    removed_dbzh = {
        "count": 1,
        "minimum": 1.0,
        "median": 1.0,
        "p90": 1.0,
        "maximum": 1.0,
        "linear_reflectivity_fraction": 0.01,
        "count_at_or_above_dbzh": {
            key: 0 for key in ("0", "5", "10", "15", "20", "30")
        },
        "input_count_at_or_above_dbzh": {
            key: 1 for key in ("0", "5", "10", "15", "20", "30")
        },
    }
    method = {
        "finite_count": 100,
        "removed_count": 1,
        "removed_fraction": 0.01,
        "removed_dbzh": removed_dbzh,
        "nuisance_counts": {
            "receiver_noise": 1,
            "static_clutter": 0,
            "anomalous_propagation": 0,
            "radial_interference": 0,
            "isolated_speckle": 0,
        },
    }
    return {
        "job_id": "ppi",
        "target_id": "ppi",
        "radar": "chenies",
        "pulse": "lp",
        "geometry_class": "ppi",
        "elevation_deg": 1.0,
        "source": {
            "source_id": "source-1",
            "date": "20250101",
            "time": "0000",
        },
        "context": {
            "upper_elevation_available": True,
            "temporal_available": False,
        },
        "baseline": method,
        "learned": method,
        "delta": {
            "learned_increment_count": 0,
            "learned_increment_fraction": 0.0,
        },
    }
