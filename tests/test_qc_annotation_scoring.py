from __future__ import annotations

import numpy as np

from uk_wsr_visualizer.qc_annotation_scoring import (
    annotation_action_masks,
    consensus_action_masks,
    rasterize_annotation_geometry,
    score_prediction_against_annotations,
)


def _item(*regions: dict, shape: tuple[int, int] = (4, 4)) -> dict:
    return {
        "shape": list(shape),
        "regions": list(regions),
    }


def _region(
    action: str,
    geometry: dict,
    *,
    label: str | None = None,
    confidence: float = 1.0,
) -> dict:
    return {
        "region_id": f"{action}-{label or action}",
        "label": label or action,
        "action": action,
        "confidence": confidence,
        "geometry": geometry,
    }


def test_rasterizes_row_major_rle_exactly() -> None:
    mask = rasterize_annotation_geometry(
        {
            "type": "row_major_rle",
            "runs": [[1, 2], [8, 3]],
        },
        (3, 4),
    )
    assert np.flatnonzero(mask).tolist() == [1, 2, 8, 9, 10]


def test_rasterizes_polar_polygon_in_display_coordinates() -> None:
    mask = rasterize_annotation_geometry(
        {
            "type": "polar_gate_polygon",
            "vertices": [
                [0.0, 0.01],
                [0.0, 3.99],
                [0.5, 3.99],
                [1.0, 3.99],
                [1.0, 0.01],
            ],
        },
        (4, 4),
    )
    assert mask.sum() == 4
    assert mask[0].all()
    assert not mask[1:].any()


def test_action_masks_exclude_ignore_and_remove_retain_conflicts() -> None:
    item = _item(
        _region(
            "remove",
            {"type": "row_major_rle", "runs": [[0, 4]]},
            label="receiver_noise",
        ),
        _region(
            "retain",
            {"type": "row_major_rle", "runs": [[2, 4]]},
            label="precipitation",
        ),
        _region(
            "ignore",
            {"type": "row_major_rle", "runs": [[6, 1]]},
            label="uncertain",
        ),
    )
    masks = annotation_action_masks(item)
    assert np.flatnonzero(masks["remove"]).tolist() == [0, 1]
    assert np.flatnonzero(masks["retain"]).tolist() == [4, 5]
    assert np.flatnonzero(masks["conflict"]).tolist() == [2, 3]
    assert np.flatnonzero(masks["ignore"]).tolist() == [2, 3, 6]


def test_consensus_requires_every_reviewer_to_label_same_action() -> None:
    first = _item(
        _region(
            "remove",
            {"type": "row_major_rle", "runs": [[0, 3]]},
            label="receiver_noise",
        )
    )
    second = _item(
        _region(
            "remove",
            {"type": "row_major_rle", "runs": [[0, 2]]},
            label="receiver_noise",
        ),
        _region(
            "retain",
            {"type": "row_major_rle", "runs": [[2, 1]]},
            label="precipitation",
        ),
    )
    masks = consensus_action_masks([first, second])
    assert np.flatnonzero(masks["remove"]).tolist() == [0, 1]
    assert np.flatnonzero(masks["conflict"]).tolist() == [2]
    assert masks["reviewer_count"] == 2


def test_scores_only_annotated_consensus_gates_and_reports_labels() -> None:
    item = _item(
        _region(
            "remove",
            {"type": "row_major_rle", "runs": [[0, 4]]},
            label="receiver_noise",
        ),
        _region(
            "retain",
            {"type": "row_major_rle", "runs": [[4, 4]]},
            label="precipitation",
        ),
    )
    predicted = np.zeros((4, 4), dtype=bool)
    predicted.reshape(-1)[[0, 1, 4]] = True
    score = score_prediction_against_annotations(predicted, [item])

    assert score["counts"] == {
        "gate_count": 16,
        "annotated_count": 8,
        "remove_label_count": 4,
        "retain_label_count": 4,
        "ignored_count": 0,
        "reviewer_disagreement_count": 0,
        "unlabelled_count": 8,
        "predicted_removed_count": 3,
        "true_positive": 2,
        "false_positive": 1,
        "false_negative": 2,
        "true_negative": 3,
    }
    assert score["metrics"]["precision"] == 2 / 3
    assert score["metrics"]["nuisance_recall"] == 0.5
    assert score["metrics"]["retain_recall"] == 0.75
    assert score["by_label"]["receiver_noise"]["correct_fraction"] == 0.5
    assert score["by_label"]["precipitation"]["correct_fraction"] == 0.75


def test_minimum_confidence_can_leave_a_sweep_unlabelled() -> None:
    item = _item(
        _region(
            "retain",
            {"type": "full_sweep"},
            label="biological",
            confidence=0.5,
        )
    )
    score = score_prediction_against_annotations(
        np.zeros((4, 4), dtype=bool),
        [item],
        minimum_confidence=0.75,
    )
    assert score["counts"]["annotated_count"] == 0
    assert score["metrics"]["retain_recall"] is None
