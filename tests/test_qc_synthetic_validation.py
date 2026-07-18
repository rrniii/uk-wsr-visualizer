from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from uk_wsr_visualizer.qc_synthetic_validation import (
    CANDIDATE_METHOD,
    CURRENT_METHOD,
    LEARNED_CANDIDATE_METHOD,
    SemiSyntheticBaseCase,
    build_conservative_real_signal_anchor,
    run_learned_prior_synthetic_validation,
    run_real_semi_synthetic_validation,
    run_synthetic_validation,
    select_signal_rich_semi_synthetic_records,
    write_learned_prior_synthetic_validation,
    write_real_semi_synthetic_validation,
    write_synthetic_validation,
)


def test_synthetic_validation_compares_current_and_candidate() -> None:
    run = run_synthetic_validation(seeds=range(2), nrays=90, nbins=120)
    report = run.report
    current = report["summary"][CURRENT_METHOD]["all"]
    candidate = report["summary"][CANDIDATE_METHOD]["all"]

    assert current["scene_count"] == 4
    assert candidate["scene_count"] == 4
    assert (
        candidate["artifact_recall"] - current["artifact_recall"]
        >= report["promotion_gates"][
            "artifact_recall_improvement_min"
        ]
    )
    assert candidate["precision"] >= 0.995
    assert candidate["retain_recall"] >= 0.9995
    assert candidate["high_signal_retain_recall"] == 1.0
    assert report["synthetic_gate_passed"]
    assert report["promotion_eligible"] is False


def test_synthetic_validation_writes_metrics_fixtures_and_plots(
    tmp_path: Path,
) -> None:
    run = run_synthetic_validation(seeds=[3], nrays=90, nbins=120)

    written = write_synthetic_validation(run, tmp_path)

    assert {path.name for path in written} >= {
        "summary.json",
        "scene_metrics.csv",
        "exact_scene_lp.npz",
        "exact_scene_sp.npz",
        "exact_scene_lp_comparison.png",
        "exact_scene_sp_comparison.png",
        "method_comparison.png",
        "artifact_recall.png",
        "README.md",
    }
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["synthetic_gate_passed"]
    for name in (
        "method_comparison.png",
        "artifact_recall.png",
        "exact_scene_lp_comparison.png",
        "exact_scene_sp_comparison.png",
    ):
        image = Image.open(tmp_path / name)
        assert image.width >= 1000
        assert image.height >= 400


def test_semi_synthetic_selection_uses_signal_rich_case_per_group() -> None:
    records = [
        _selection_record("weak", "chenies", "lp", strong=2),
        _selection_record("strong", "chenies", "lp", strong=20),
        _selection_record("sp", "chenies", "sp", strong=5),
    ]

    selected = select_signal_rich_semi_synthetic_records(records)

    assert [record["job_id"] for record in selected] == [
        "strong",
        "sp",
    ]


def test_real_signal_anchor_excludes_low_quality_receiver_field() -> None:
    shape = (24, 30)
    dbzh = np.full(shape, -8.0, dtype="float32")
    companions = {
        "VRADH": np.zeros(shape, dtype="float32"),
        "SQIH": np.full(shape, 0.01, dtype="float32"),
        "RHOHV": np.full(shape, 0.1, dtype="float32"),
    }
    dbzh[4:12, 5:15] = 12.0
    companions["VRADH"][4:12, 5:15] = 5.0
    companions["SQIH"][4:12, 5:15] = 0.7
    companions["RHOHV"][4:12, 5:15] = 0.8

    anchor, counts = build_conservative_real_signal_anchor(
        dbzh,
        companions,
    )

    assert anchor[7, 9]
    assert not anchor[18, 22]
    assert counts["anchor_gate_count"] > 0


def test_real_semi_synthetic_validation_persists_exact_artifacts(
    tmp_path: Path,
) -> None:
    cases = [
        _semi_synthetic_case("lp-case", "lp"),
        _semi_synthetic_case("sp-case", "sp"),
    ]
    run = run_real_semi_synthetic_validation(cases, seed_start=9000)

    written = write_real_semi_synthetic_validation(
        run,
        tmp_path / "report",
        artifact_root=tmp_path / "artifacts",
    )

    assert run.report["case_count"] == 2
    assert (
        run.report["injection_contract"]["context_mode"]
        == "persistent_static"
    )
    assert run.report["summary"]["all"]["retain_recall"] == 1.0
    assert {path.name for path in written} >= {
        "summary.json",
        "case_metrics.csv",
        "real_semi_synthetic_lp.png",
        "real_semi_synthetic_sp.png",
        "README.md",
        "lp-case.npz",
        "sp-case.npz",
    }
    summary = json.loads(
        (tmp_path / "report" / "summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(summary["records"]) == 2
    for record in summary["records"]:
        with np.load(record["artifact_npz"], allow_pickle=False) as artifact:
            assert set(artifact.files) >= {
                "truth_mask",
                "anchor_mask",
                "artifact_exclusion_mask",
                "predicted_remove_mask",
                "evidence_mask",
            }
            assert not np.any(
                artifact["truth_mask"]
                & artifact["artifact_exclusion_mask"]
            )


def test_learned_prior_uses_disjoint_dynamic_train_and_holdout_scenes() -> None:
    run = run_learned_prior_synthetic_validation(
        training_seeds=range(100, 148),
        holdout_seeds=range(500, 504),
        nrays=180,
        nbins=220,
    )
    report = run.report
    baseline = report["summary"][CANDIDATE_METHOD]["all"]
    learned = report["summary"][LEARNED_CANDIDATE_METHOD]["all"]

    assert report["training_contract"]["seeds_disjoint"]
    assert report["training_contract"]["dynamic_geometry"]
    assert learned["precision"] >= 0.995
    assert learned["retain_recall"] >= 0.9995
    assert report["validation_gate_passed"]
    assert learned["per_artifact"]["static_clutter"]["recall"] >= 0.90
    assert learned["per_artifact"]["static_clutter"]["recall"] > (
        baseline["per_artifact"]["static_clutter"]["recall"] + 0.50
    )
    assert report["promotion_eligible"] is False


def test_learned_prior_validation_writes_fixtures_and_plots(
    tmp_path: Path,
) -> None:
    run = run_learned_prior_synthetic_validation(
        training_seeds=range(100, 108),
        holdout_seeds=[500],
        nrays=180,
        nbins=220,
    )

    written = write_learned_prior_synthetic_validation(run, tmp_path)

    assert {path.name for path in written} >= {
        "summary.json",
        "holdout_metrics.csv",
        "learned_prior_holdout_lp.npz",
        "learned_prior_holdout_sp.npz",
        "learned_prior_holdout_lp.png",
        "learned_prior_holdout_sp.png",
        "learned_prior_comparison.png",
        "README.md",
    }
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["training_contract"]["seeds_disjoint"]
    for name in (
        "learned_prior_comparison.png",
        "learned_prior_holdout_lp.png",
        "learned_prior_holdout_sp.png",
    ):
        image = Image.open(tmp_path / name)
        assert image.width >= 1000
        assert image.height >= 400


def _selection_record(
    job_id: str,
    radar: str,
    pulse: str,
    *,
    strong: int,
) -> dict:
    return {
        "job_id": job_id,
        "radar": radar,
        "pulse": pulse,
        "geometry_class": "ppi",
        "learned": {
            "finite_count": 100,
            "removed_fraction": 0.0,
            "removed_dbzh": {
                "input_count_at_or_above_dbzh": {
                    "10": strong + 10,
                    "20": strong,
                }
            },
        },
    }


def _semi_synthetic_case(case_id: str, pulse: str) -> SemiSyntheticBaseCase:
    shape = (90, 120)
    dbzh = np.full(shape, np.nan, dtype="float32")
    companions = {
        name: np.full(shape, np.nan, dtype="float32")
        for name in ("VRADH", "SQIH", "RHOHV", "ZDR", "PHIDP", "CI")
    }
    signal = np.zeros(shape, dtype=bool)
    signal[20:45, 18:48] = True
    dbzh[signal] = 25.0
    companions["VRADH"][signal] = 6.0
    companions["SQIH"][signal] = 0.8
    companions["RHOHV"][signal] = 0.95
    companions["ZDR"][signal] = 1.0
    companions["PHIDP"][signal] = 20.0
    companions["CI"][signal] = 5.0
    return SemiSyntheticBaseCase(
        case_id=case_id,
        radar="chenies",
        pulse=pulse,
        elevation_deg=1.0,
        source_id=f"{case_id}-source",
        source_sha256="a" * 64,
        dataset="dataset1",
        date="20250101",
        time="0000",
        rstart_km=0.0,
        rscale_m=600.0,
        dbzh=dbzh,
        companions=companions,
    )
