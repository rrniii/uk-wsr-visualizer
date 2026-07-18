from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from uk_wsr_visualizer.background_model import BackgroundModel, hash_arrays
from uk_wsr_visualizer.background_model_v3 import (
    BACKGROUND_MODEL_V3_STATISTICS_VERSION,
)
from uk_wsr_visualizer.background_training_pipeline import (
    BackgroundTrainingTarget,
    SweepDescriptor,
)
from uk_wsr_visualizer.background_validation_pipeline import (
    BackgroundValidationEvaluation,
    BackgroundValidationModelResolver,
    ValidationSweepReadCache,
    _baseline_result_from_learned,
    _read_sweep,
    background_model_target_match,
    build_background_validation_jobs,
    evaluate_background_validation_job,
    load_resumable_validation_record,
    merge_background_validation_shards,
    summarise_background_validation,
    validation_configuration_contract,
    write_background_validation_artifact,
    write_background_validation_report,
)
from uk_wsr_visualizer.qc_evidence import (
    EvidenceConfig,
    EvidenceContext,
    classify_nuisance_echoes,
)


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


def test_model_resolver_accepts_unique_physical_elevation_alias(
    tmp_path: Path,
) -> None:
    target = _target(
        "chenies_lp_dbzh_e04000_5x5_r0m_s600000mm",
        4.0,
        (),
    )
    model_path = tmp_path / (
        "chenies_lp_dbzh_e03950_5x5_r0m_s600000mm.json"
    )
    model_path.write_text(
        json.dumps(
            {
                "schema": "uk_wsr_background_model",
                "shape": [5, 5],
                "key": {
                    "geometry_id": model_path.stem,
                    "radar": "chenies",
                    "pulse": "lp",
                    "quantity": "DBZH",
                    "elevation_deg": 3.95,
                    "nrays": 5,
                    "nbins": 5,
                    "rstart_km": 0.0,
                    "rscale_m": 600.0,
                },
            }
        ),
        encoding="utf-8",
    )

    resolved = BackgroundValidationModelResolver(tmp_path).resolve_path(
        target
    )

    assert resolved == model_path


def test_model_resolver_rejects_ambiguous_elevation_aliases(
    tmp_path: Path,
) -> None:
    target = _target("canonical", 4.0, ())
    for elevation in (3.95, 4.05):
        path = tmp_path / f"model-{elevation}.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "uk_wsr_background_model",
                    "shape": [5, 5],
                    "key": {
                        "geometry_id": path.stem,
                        "radar": "chenies",
                        "pulse": "lp",
                        "quantity": "DBZH",
                        "elevation_deg": elevation,
                        "nrays": 5,
                        "nbins": 5,
                        "rstart_km": 0.0,
                        "rscale_m": 600.0,
                    },
                }
            ),
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="ambiguous"):
        BackgroundValidationModelResolver(tmp_path).resolve_path(target)


def test_model_target_match_persists_tolerance_alias() -> None:
    target = _target("canonical", 4.0, ())
    model = BackgroundModel(
        key={
            "geometry_id": "legacy",
            "radar": "chenies",
            "pulse": "lp",
            "quantity": "DBZH",
            "elevation_deg": 3.95,
            "nrays": 5,
            "nbins": 5,
            "rstart_km": 0.0,
            "rscale_m": 600.0,
        },
        shape=(5, 5),
        arrays={},
    )

    match = background_model_target_match(model, target)

    assert match["compatible"] is True
    assert (
        match["match_type"]
        == "physical_geometry_within_elevation_tolerance"
    )
    assert match["elevation_delta_deg"] == pytest.approx(0.05)


def test_validation_jobs_score_only_eligible_sequence_members() -> None:
    sweeps = tuple(
        _sweep(
            f"volume-{index}",
            "dataset1",
            1.0,
            f"00{index}0",
        )
        for index in range(4)
    )
    target = _target("target", 1.0, sweeps)

    jobs = build_background_validation_jobs(
        (target,),
        split="validation",
        eligible_source_ids={
            "volume-1",
            "volume-2",
        },
    )

    assert [job.sweep.source_id for job in jobs] == [
        "volume-1",
        "volume-2",
    ]
    assert jobs[0].previous_sweep == sweeps[0]
    assert jobs[0].next_sweep == sweeps[2]
    assert jobs[1].previous_sweep == sweeps[1]
    assert jobs[1].next_sweep == sweeps[3]


def test_highest_sp_ppi_requires_cross_scan_receiver_context() -> None:
    lower_sweeps = (
        _sweep(
            "volume-a",
            "dataset1",
            4.0,
            "0000",
            pulse="sp",
        ),
        _sweep(
            "volume-b",
            "dataset1",
            4.0,
            "0010",
            pulse="sp",
        ),
    )
    upper_sweeps = (
        _sweep(
            "volume-a",
            "dataset2",
            9.0,
            "0000",
            pulse="sp",
        ),
    )
    lower = _target("lower", 4.0, lower_sweeps, pulse="sp")
    upper = _target("upper", 9.0, upper_sweeps, pulse="sp")

    jobs = build_background_validation_jobs(
        (lower, upper),
        split="validation",
    )
    indexed = {
        (job.target.target_id, job.sweep.source_id): job
        for job in jobs
    }

    assert (
        indexed[("lower", "volume-a")].receiver_noise_cross_scan_required
        is False
    )
    assert (
        indexed[("lower", "volume-b")].receiver_noise_cross_scan_required
        is True
    )
    assert (
        indexed[("upper", "volume-a")].receiver_noise_cross_scan_required
        is True
    )


def test_validation_sweep_read_cache_reuses_verified_payload(
    monkeypatch,
) -> None:
    sweep = _sweep("volume-a", "dataset1", 1.0, "0000")
    target = _target("target", 1.0, (sweep,))
    values = np.full((5, 5), 10.0, dtype="float32")
    metadata = SimpleNamespace(
        elevation_deg=1.0,
        rstart_km=0.0,
        rscale_m=600.0,
    )
    calls = 0

    def fake_read(*args, **kwargs):
        nonlocal calls
        del args, kwargs
        calls += 1
        return values, metadata, {"DBZH": values}

    monkeypatch.setattr(
        "uk_wsr_visualizer.background_validation_pipeline."
        "read_polar_field_with_companions",
        fake_read,
    )
    cache = ValidationSweepReadCache(max_entries=2)

    first = _read_sweep(
        sweep,
        target,
        require_target_elevation=True,
        read_cache=cache,
    )
    second = _read_sweep(
        sweep,
        target,
        require_target_elevation=False,
        read_cache=cache,
    )

    assert calls == 1
    assert first[0] is second[0]
    assert first[1] is second[1]
    assert first[2] is second[2]
    assert cache.statistics() == {
        "max_entries": 2,
        "entry_count": 1,
        "hits": 1,
        "misses": 1,
    }


def test_evaluation_adds_only_supported_learned_clutter(
    monkeypatch,
) -> None:
    shape = (5, 5)
    sweeps = (
        _sweep("volume-a", "dataset1", 1.0, "0000"),
        _sweep("volume-b", "dataset1", 1.0, "0010"),
        _sweep("volume-c", "dataset1", 1.0, "0020"),
    )
    target = _target("target", 1.0, sweeps)
    jobs = build_background_validation_jobs(
        (target,),
        split="validation",
    )
    job = next(
        selected
        for selected in jobs
        if selected.sweep.source_id == "volume-b"
    )
    values = np.full(shape, 10.0, dtype="float32")
    companions = {
        "CI": np.full(shape, 1.0, dtype="float32"),
        "VRADH": np.zeros(shape, dtype="float32"),
            "SQIH": np.full(shape, 0.4, dtype="float32"),
            "RHOHV": np.full(shape, 0.4, dtype="float32"),
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
        "low_ci_static_echo_date_sample_count": np.full(
            shape,
            8.0,
            dtype="float32",
        ),
        "low_ci_static_echo_date_frequency": np.ones(
            shape,
            dtype="float32",
        ),
        "low_ci_static_echo_season_count": np.full(
            shape,
            4.0,
            dtype="float32",
        ),
            "low_ci_static_echo_time_bucket_count": np.full(
                shape,
                2.0,
                dtype="float32",
            ),
            "low_ci_static_dbzh_p10": np.full(
                shape,
                9.0,
                dtype="float32",
            ),
            "low_ci_static_dbzh_median": np.full(
                shape,
                10.0,
                dtype="float32",
            ),
            "low_ci_static_dbzh_p90": np.full(
                shape,
                12.0,
                dtype="float32",
            ),
        }
    model = BackgroundModel(
        key={"geometry_id": "target"},
        shape=shape,
        arrays=model_arrays,
        metadata={
            "statistics_version": (
                BACKGROUND_MODEL_V3_STATISTICS_VERSION
            )
        },
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
    assert evaluation.record["context"]["temporal_context_count"] == 2
    assert evaluation.record["context"]["temporal_context_complete"] is True
    assert not evaluation.record["promotion_eligible"]


def test_derived_baseline_matches_independent_classification() -> None:
    shape = (180, 220)
    ranges_km = (np.arange(shape[1]) + 0.5) * 0.6
    profile = 20.0 * np.log10(ranges_km) - 27.5
    dbzh = np.broadcast_to(profile, shape).astype("float32").copy()
    checker = np.indices(shape).sum(axis=0) % 2
    rng = np.random.default_rng(19)
    companions = {
        "CI": np.full(shape, 7.0, dtype="float32"),
        "SQIH": np.full(shape, 0.01, dtype="float32"),
        "RHOHV": np.full(shape, 0.1, dtype="float32"),
        "ZDR": np.where(checker, 10.0, -4.0).astype("float32"),
        "PHIDP": np.where(checker, 170.0, -170.0).astype("float32"),
        "VRADH": rng.uniform(-30.0, 30.0, shape).astype("float32"),
    }
    common_context = {
        "previous_dbzh": dbzh + 5.0,
        "next_dbzh": dbzh - 5.0,
        "previous_vrad": np.full(shape, -40.0, dtype="float32"),
        "next_vrad": np.full(shape, 40.0, dtype="float32"),
        "receiver_noise_cross_scan_required": True,
    }
    independent = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="sp",
        rstart_km=0.0,
        rscale_m=600.0,
        context=EvidenceContext(**common_context),
    )
    learned = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="sp",
        rstart_km=0.0,
        rscale_m=600.0,
        context=EvidenceContext(
            **common_context,
            temporal_context_required=True,
            background_statistics_version=(
                BACKGROUND_MODEL_V3_STATISTICS_VERSION
            ),
            background_distinct_date_count=np.full(
                shape,
                8.0,
                dtype="float32",
            ),
            background_static_echo_date_frequency=np.ones(
                shape,
                dtype="float32",
            ),
            background_static_echo_season_count=np.full(
                shape,
                4.0,
                dtype="float32",
            ),
            background_static_echo_time_bucket_count=np.full(
                shape,
                2.0,
                dtype="float32",
            ),
            background_static_dbzh_p10=dbzh - 1.0,
            background_static_dbzh_median=dbzh,
            background_static_dbzh_p90=dbzh + 1.0,
        ),
    )

    derived = _baseline_result_from_learned(learned)

    np.testing.assert_array_equal(
        derived.remove_mask,
        independent.remove_mask,
    )
    np.testing.assert_array_equal(
        derived.nuisance_mask,
        independent.nuisance_mask,
    )
    np.testing.assert_array_equal(
        derived.evidence_mask,
        independent.evidence_mask,
    )
    np.testing.assert_array_equal(
        derived.confidence,
        independent.confidence,
    )
    assert derived.counts == independent.counts


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


def test_validation_artifact_archive_is_deterministic(
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
        "dbzh_raw": np.array(
            [[np.nan, 1.0], [2.0, 3.0]],
            dtype="float32",
        ),
        "learned_remove_mask": np.array(
            [[0, 1], [0, 0]],
            dtype="uint8",
        ),
    }
    evaluation = BackgroundValidationEvaluation(
        record=record,
        arrays=arrays,
    )

    first, _, first_sidecar = write_background_validation_artifact(
        evaluation,
        tmp_path / "first",
        configuration_contract=contract,
    )
    second, _, second_sidecar = write_background_validation_artifact(
        evaluation,
        tmp_path / "second",
        configuration_contract=contract,
    )

    assert first.read_bytes() == second.read_bytes()
    assert (
        first_sidecar["artifact_sha256"]
        == second_sidecar["artifact_sha256"]
    )
    assert first_sidecar["array_hash"] == second_sidecar["array_hash"]
    assert first_sidecar["archive"]["compression_level"] == 1
    with np.load(first) as persisted:
        for name, expected in arrays.items():
            np.testing.assert_array_equal(
                persisted[name],
                expected,
            )


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


def test_validation_shards_merge_only_contract_identical_records(
    tmp_path: Path,
) -> None:
    contract, config_hash = validation_configuration_contract(
        EvidenceConfig(),
        max_temporal_gap_minutes=20,
    )
    first = _summary_record()
    second = dict(first) | {
        "job_id": "second",
        "target_id": "second",
        "radar": "clee-hill",
        "source": dict(first["source"]) | {"source_id": "source-2"},
    }
    artifact_root = tmp_path / "artifacts"
    shards = []
    for index, record in enumerate((first, second), start=1):
        path = tmp_path / f"shard-{index}.json"
        write_background_validation_report(
            path,
            split="validation",
            expected_job_count=1,
            records=[record],
            errors=[],
            configuration_contract=contract,
            configuration_sha256=config_hash,
            artifact_root=artifact_root,
            all_jobs_attempted=True,
        )
        shards.append(path)

    destination = merge_background_validation_shards(
        shards,
        tmp_path / "merged.json",
    )

    import json

    merged = json.loads(destination.read_text(encoding="utf-8"))
    assert merged["complete"] is True
    assert merged["expected_job_count"] == 2
    assert merged["scored_job_count"] == 2
    assert merged["summary"]["radar_count"] == 2
    assert [record["job_id"] for record in merged["records"]] == [
        "ppi",
        "second",
    ]


def test_validation_shards_reject_duplicate_jobs(tmp_path: Path) -> None:
    contract, config_hash = validation_configuration_contract(
        EvidenceConfig(),
        max_temporal_gap_minutes=20,
    )
    shards = []
    for index in range(2):
        path = tmp_path / f"shard-{index}.json"
        write_background_validation_report(
            path,
            split="validation",
            expected_job_count=1,
            records=[_summary_record()],
            errors=[],
            configuration_contract=contract,
            configuration_sha256=config_hash,
            artifact_root=tmp_path / "artifacts",
            all_jobs_attempted=True,
        )
        shards.append(path)

    import pytest

    with pytest.raises(ValueError, match="duplicate validation jobs"):
        merge_background_validation_shards(
            shards,
            tmp_path / "merged.json",
        )


def _target(
    target_id: str,
    elevation: float,
    sweeps: tuple[SweepDescriptor, ...],
    *,
    pulse: str = "lp",
) -> BackgroundTrainingTarget:
    return BackgroundTrainingTarget(
        target_id=target_id,
        radar="chenies",
        pulse=pulse,
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
    *,
    pulse: str = "lp",
) -> SweepDescriptor:
    return SweepDescriptor(
        source_id=source_id,
        radar="chenies",
        pulse=pulse,
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
