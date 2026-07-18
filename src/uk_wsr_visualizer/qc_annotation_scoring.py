"""Deterministic gate scoring for blinded UK WSR QC annotations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .dependencies import require_numpy


ANNOTATION_SCORE_SCHEMA = "uk_wsr_qc_annotation_score"
ANNOTATION_SCORE_SCHEMA_VERSION = 1
VALID_ACTIONS = frozenset({"remove", "retain", "ignore"})


def rasterize_annotation_geometry(
    geometry: Mapping[str, Any],
    shape: tuple[int, int] | list[int],
) -> Any:
    """Rasterize one annotation geometry into a polar gate mask."""

    np = require_numpy()
    nrays, nbins = _validated_shape(shape)
    geometry_type = str(geometry.get("type") or "")
    if geometry_type == "full_sweep":
        return np.ones((nrays, nbins), dtype=bool)
    if geometry_type == "row_major_rle":
        mask = np.zeros(nrays * nbins, dtype=bool)
        for raw_run in geometry.get("runs") or ():
            if not isinstance(raw_run, (list, tuple)) or len(raw_run) != 2:
                raise ValueError("RLE run must contain offset and length")
            offset, length = (int(value) for value in raw_run)
            if offset < 0 or length < 1 or offset + length > mask.size:
                raise ValueError("RLE run is outside the sweep")
            mask[offset : offset + length] = True
        return mask.reshape((nrays, nbins))
    if geometry_type == "polar_gate_polygon":
        vertices = geometry.get("vertices")
        if not isinstance(vertices, list) or len(vertices) < 3:
            raise ValueError("polar polygon requires at least three vertices")
        return _polar_polygon_mask(vertices, nrays=nrays, nbins=nbins)
    raise ValueError(f"unsupported annotation geometry: {geometry_type}")


def annotation_action_masks(
    item: Mapping[str, Any],
    *,
    minimum_confidence: float = 0.0,
) -> dict[str, Any]:
    """Build mutually exclusive remove, retain, and ignored gate masks."""

    np = require_numpy()
    shape = _validated_shape(item.get("shape"))
    threshold = float(minimum_confidence)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("minimum confidence must be between zero and one")

    action_masks = {
        action: np.zeros(shape, dtype=bool)
        for action in VALID_ACTIONS
    }
    label_masks: dict[str, Any] = {}
    label_actions: dict[str, str] = {}
    included_regions = 0
    for region in item.get("regions") or ():
        action = str(region.get("action") or "")
        if action not in VALID_ACTIONS:
            raise ValueError(f"unsupported annotation action: {action}")
        confidence = float(region.get("confidence"))
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("annotation confidence must be between zero and one")
        if confidence < threshold:
            continue
        mask = rasterize_annotation_geometry(region.get("geometry") or {}, shape)
        action_masks[action] |= mask
        included_regions += 1

        label = str(region.get("label") or "").strip()
        if not label:
            raise ValueError("annotation label must not be empty")
        previous_action = label_actions.setdefault(label, action)
        if previous_action != action:
            raise ValueError(
                f"annotation label {label!r} uses conflicting actions"
            )
        label_masks.setdefault(label, np.zeros(shape, dtype=bool))
        label_masks[label] |= mask

    conflict = action_masks["remove"] & action_masks["retain"]
    ignored = action_masks["ignore"] | conflict
    remove = action_masks["remove"] & ~ignored
    retain = action_masks["retain"] & ~ignored
    labelled = remove | retain
    return {
        "remove": remove,
        "retain": retain,
        "ignore": ignored,
        "conflict": conflict,
        "labelled": labelled,
        "unlabelled": ~(labelled | ignored),
        "label_masks": {
            label: mask & labelled
            for label, mask in sorted(label_masks.items())
        },
        "label_actions": dict(sorted(label_actions.items())),
        "included_region_count": included_regions,
    }


def consensus_action_masks(
    items: Iterable[Mapping[str, Any]],
    *,
    minimum_confidence: float = 0.0,
) -> dict[str, Any]:
    """Keep only gates independently labelled with the same action."""

    np = require_numpy()
    documents = tuple(items)
    if not documents:
        raise ValueError("at least one annotation item is required")
    shape = _validated_shape(documents[0].get("shape"))
    if any(_validated_shape(item.get("shape")) != shape for item in documents):
        raise ValueError("annotation item shapes do not match")

    masks = [
        annotation_action_masks(
            item,
            minimum_confidence=minimum_confidence,
        )
        for item in documents
    ]
    remove = np.logical_and.reduce([entry["remove"] for entry in masks])
    retain = np.logical_and.reduce([entry["retain"] for entry in masks])
    any_labelled = np.logical_or.reduce(
        [entry["labelled"] for entry in masks]
    )
    any_ignored = np.logical_or.reduce(
        [entry["ignore"] for entry in masks]
    )
    disagreement = any_labelled & ~(remove | retain)
    ignored = any_ignored | disagreement
    remove &= ~ignored
    retain &= ~ignored
    labelled = remove | retain
    return {
        "remove": remove,
        "retain": retain,
        "ignore": ignored,
        "conflict": disagreement,
        "labelled": labelled,
        "unlabelled": ~(labelled | ignored),
        "reviewer_count": len(documents),
    }


def score_prediction_against_annotations(
    predicted_remove_mask: Any,
    items: Iterable[Mapping[str, Any]],
    *,
    minimum_confidence: float = 0.0,
) -> dict[str, Any]:
    """Score one exact candidate mask only where reviewers supplied labels."""

    np = require_numpy()
    documents = tuple(items)
    consensus = consensus_action_masks(
        documents,
        minimum_confidence=minimum_confidence,
    )
    predicted = np.asarray(predicted_remove_mask, dtype=bool)
    if predicted.shape != consensus["remove"].shape:
        raise ValueError("prediction and annotation shapes do not match")

    remove_truth = consensus["remove"]
    retain_truth = consensus["retain"]
    true_positive = int((predicted & remove_truth).sum())
    false_negative = int((~predicted & remove_truth).sum())
    false_positive = int((predicted & retain_truth).sum())
    true_negative = int((~predicted & retain_truth).sum())
    remove_count = int(remove_truth.sum())
    retain_count = int(retain_truth.sum())
    annotated_count = remove_count + retain_count
    predicted_removed_count = true_positive + false_positive

    result = {
        "schema": ANNOTATION_SCORE_SCHEMA,
        "schema_version": ANNOTATION_SCORE_SCHEMA_VERSION,
        "minimum_confidence": float(minimum_confidence),
        "reviewer_count": consensus["reviewer_count"],
        "shape": list(predicted.shape),
        "counts": {
            "gate_count": int(predicted.size),
            "annotated_count": annotated_count,
            "remove_label_count": remove_count,
            "retain_label_count": retain_count,
            "ignored_count": int(consensus["ignore"].sum()),
            "reviewer_disagreement_count": int(
                consensus["conflict"].sum()
            ),
            "unlabelled_count": int(consensus["unlabelled"].sum()),
            "predicted_removed_count": predicted_removed_count,
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "true_negative": true_negative,
        },
        "metrics": {
            "precision": _ratio(
                true_positive,
                true_positive + false_positive,
            ),
            "nuisance_recall": _ratio(true_positive, remove_count),
            "retain_recall": _ratio(true_negative, retain_count),
            "false_removal_rate": _ratio(false_positive, retain_count),
            "missed_nuisance_rate": _ratio(false_negative, remove_count),
            "intersection_over_union": _ratio(
                true_positive,
                true_positive + false_positive + false_negative,
            ),
            "annotated_removal_fraction": _ratio(
                predicted_removed_count,
                annotated_count,
            ),
        },
    }
    if len(documents) == 1:
        result["by_label"] = _score_labels(
            predicted,
            annotation_action_masks(
                documents[0],
                minimum_confidence=minimum_confidence,
            ),
        )
    return result


def _score_labels(predicted: Any, masks: Mapping[str, Any]) -> dict[str, Any]:
    scores = {}
    for label, mask in masks["label_masks"].items():
        action = masks["label_actions"][label]
        count = int(mask.sum())
        removed = int((predicted & mask).sum())
        correct = removed if action == "remove" else count - removed
        scores[label] = {
            "action": action,
            "gate_count": count,
            "predicted_removed_count": removed,
            "correct_count": correct,
            "correct_fraction": _ratio(correct, count),
        }
    return scores


def _polar_polygon_mask(
    vertices: list[Any],
    *,
    nrays: int,
    nbins: int,
) -> Any:
    np = require_numpy()
    checked = []
    for vertex in vertices:
        if not isinstance(vertex, (list, tuple)) or len(vertex) != 2:
            raise ValueError("polygon vertex must contain ray and gate")
        ray, gate = (float(value) for value in vertex)
        if not 0.0 <= ray < nrays or not 0.0 <= gate < nbins:
            raise ValueError("polygon vertex is outside the sweep")
        checked.append((ray, gate))

    vertex_rays = np.asarray([value[0] for value in checked], dtype="float64")
    vertex_gates = np.asarray([value[1] for value in checked], dtype="float64")
    vertex_angles = vertex_rays * (2.0 * np.pi / nrays)
    vertex_radius = vertex_gates / nbins
    polygon_x = np.sin(vertex_angles) * vertex_radius
    polygon_y = -np.cos(vertex_angles) * vertex_radius

    ray_centres = (
        np.arange(nrays, dtype="float64") + 0.5
    ) * (2.0 * np.pi / nrays)
    gate_centres = (
        np.arange(nbins, dtype="float64") + 0.5
    ) / nbins
    point_x = (
        np.sin(ray_centres)[:, np.newaxis]
        * gate_centres[np.newaxis, :]
    )
    point_y = (
        -np.cos(ray_centres)[:, np.newaxis]
        * gate_centres[np.newaxis, :]
    )

    inside = np.zeros((nrays, nbins), dtype=bool)
    previous = len(checked) - 1
    for current in range(len(checked)):
        x_current = polygon_x[current]
        y_current = polygon_y[current]
        x_previous = polygon_x[previous]
        y_previous = polygon_y[previous]
        crosses = (y_current > point_y) != (y_previous > point_y)
        denominator = y_previous - y_current
        if abs(denominator) < 1.0e-15:
            previous = current
            continue
        boundary_x = (
            (x_previous - x_current)
            * (point_y - y_current)
            / denominator
            + x_current
        )
        inside ^= crosses & (point_x < boundary_x)
        previous = current
    return inside


def _validated_shape(raw: Any) -> tuple[int, int]:
    if (
        not isinstance(raw, (list, tuple))
        or len(raw) != 2
        or any(int(value) < 1 for value in raw)
    ):
        raise ValueError("annotation shape must contain two positive dimensions")
    return int(raw[0]), int(raw[1])


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None
