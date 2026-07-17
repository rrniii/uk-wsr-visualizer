from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from uk_wsr_visualizer.qc_synthetic_validation import (
    CANDIDATE_METHOD,
    CURRENT_METHOD,
    run_synthetic_validation,
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
