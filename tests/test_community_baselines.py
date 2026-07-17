from __future__ import annotations

import numpy as np

from uk_wsr_visualizer.community_baselines import (
    COMMUNITY_BASELINE_METHODS,
    community_method_metrics,
    select_community_baseline_records,
    summarise_community_baselines,
)


def test_stratified_selection_covers_each_radar_and_pulse() -> None:
    records = [
        _record(radar, pulse, index)
        for radar in ("a", "b")
        for pulse in ("lp", "sp")
        for index in range(5)
    ]

    selected = select_community_baseline_records(
        records,
        case_count=12,
    )

    assert len(selected) == 12
    assert {
        (record["radar"], record["pulse"]) for record in selected
    } == {("a", "lp"), ("a", "sp"), ("b", "lp"), ("b", "sp")}
    assert all(record["geometry_class"] == "ppi" for record in selected)


def test_method_metrics_report_candidate_conflicts_without_labels() -> None:
    dbzh = np.asarray([[5.0, 25.0], [10.0, np.nan]], dtype="float32")
    method = np.asarray([[1, 1], [0, 1]], dtype="uint8")
    candidate = np.asarray([[1, 0], [0, 0]], dtype="uint8")
    increment = candidate.copy()
    protected = np.asarray([[0, 1], [0, 0]], dtype="uint8")
    evidence = np.zeros((2, 2), dtype="uint32")

    metrics = community_method_metrics(
        dbzh,
        method,
        candidate_remove_mask=candidate,
        candidate_increment_mask=increment,
        candidate_protected_mask=protected,
        candidate_evidence_mask=evidence,
    )

    assert metrics["finite_count"] == 3
    assert metrics["removed_count"] == 2
    assert metrics["removed_at_or_above_dbzh"]["20"] == 1
    assert metrics["candidate_overlap_count"] == 1
    assert metrics["candidate_protected_count"] == 1


def test_summary_keeps_methods_descriptive() -> None:
    metrics = {
        "finite_count": 10,
        "removed_count": 2,
        "removed_fraction": 0.2,
        "candidate_protected_count": 0,
        "candidate_upper_supported_count": 0,
        "removed_at_or_above_dbzh": {
            key: 0 for key in ("0", "5", "10", "15", "20", "30")
        },
    }
    methods = {
        method: {"status": "scored", "metrics": dict(metrics)}
        for method in COMMUNITY_BASELINE_METHODS
    }
    summary = summarise_community_baselines(
        [
            {
                "radar": "a",
                "pulse": "lp",
                "methods": methods,
            }
        ]
    )

    assert summary["methods"]["wradlib_gabella"][
        "removed_fraction"
    ] == 0.2
    assert summary["promotion_eligible"] is False
    assert "not error" in summary["interpretation"]


def _record(radar: str, pulse: str, index: int) -> dict:
    return {
        "job_id": f"{radar}-{pulse}-{index}",
        "radar": radar,
        "pulse": pulse,
        "geometry_class": "ppi",
        "elevation_deg": float(index),
        "source": {
            "date": f"202501{index + 1:02d}",
            "time": "0000",
        },
        "learned": {
            "removed_fraction": index / 10,
        },
        "delta": {
            "learned_increment_fraction": index / 20,
            "learned_increment_dbzh": {
                "linear_reflectivity_fraction": index / 30,
            },
        },
    }
