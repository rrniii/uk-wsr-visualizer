from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from uk_wsr_visualizer.qc_synthetic_validation import (
    CANDIDATE_METHOD,
    CURRENT_METHOD,
    LEARNED_CANDIDATE_METHOD,
    run_learned_prior_synthetic_validation,
    run_synthetic_validation,
    write_learned_prior_synthetic_validation,
    write_synthetic_validation,
)


def test_synthetic_validation_compares_current_and_candidate() -> None:
    run = run_synthetic_validation(seeds=range(2), nrays=90, nbins=120)
    report = run.report
    current = report["summary"][CURRENT_METHOD]["all"]
    candidate = report["summary"][CANDIDATE_METHOD]["all"]

    assert current["scene_count"] == 4
    assert candidate["scene_count"] == 4
    assert candidate["artifact_recall"] > current["artifact_recall"] + 0.5
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
