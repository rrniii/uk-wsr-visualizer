from __future__ import annotations

import numpy as np
import pytest

from uk_wsr_visualizer.qc_evidence import (
    EVIDENCE_VERSION,
    EvidenceContext,
    NuisanceFlag,
    classify_nuisance_echoes,
)
from uk_wsr_visualizer.qc_synthetic import (
    SyntheticConfig,
    SyntheticTruthFlag,
    evaluate_predicted_removal,
    generate_synthetic_scene,
)


@pytest.mark.parametrize("pulse", ["lp", "sp"])
def test_multi_evidence_candidate_preserves_coherent_signals(
    pulse: str,
) -> None:
    scene = generate_synthetic_scene(
        SyntheticConfig(pulse=pulse, nrays=180, nbins=220),
        seed=19,
    )

    result = classify_nuisance_echoes(
        scene.dbzh,
        scene.companions,
        pulse=pulse,
    )
    metrics = evaluate_predicted_removal(result.remove_mask, scene)

    assert result.version == EVIDENCE_VERSION
    assert metrics["retain_recall"] >= 0.995
    assert metrics["high_signal_retain_recall"] == 1.0
    assert metrics["precision"] >= 0.98
    assert metrics["per_artifact"]["receiver_noise"]["recall"] >= 0.80
    assert metrics["per_artifact"]["radial_interference"]["recall"] >= 0.50
    assert metrics["per_artifact"]["isolated_speckle"]["recall"] >= 0.50


def test_learned_prior_requires_current_static_confirmation() -> None:
    scene = generate_synthetic_scene(
        SyntheticConfig(pulse="lp", nrays=180, nbins=220),
        seed=23,
    )
    static = (
        scene.truth_mask & int(SyntheticTruthFlag.STATIC_CLUTTER)
    ) != 0
    persistence = np.zeros(scene.dbzh.shape, dtype="float32")
    static_frequency = np.zeros(scene.dbzh.shape, dtype="float32")
    persistence[static] = 0.99
    static_frequency[static] = 0.95

    result = classify_nuisance_echoes(
        scene.dbzh,
        scene.companions,
        pulse="lp",
        context=EvidenceContext(
            background_persistent_frequency=persistence,
            background_near_zero_vrad_frequency=static_frequency,
            background_conditioned_sample_count=np.full(
                scene.dbzh.shape,
                48.0,
                dtype="float32",
            ),
            background_dbzh_p90=scene.dbzh + 1.0,
        ),
    )

    static_prediction = result.nuisance(NuisanceFlag.STATIC_CLUTTER)
    assert (static_prediction & static).sum() / static.sum() >= 0.85
    assert not np.any(static_prediction & scene.retain_mask)


def test_learned_prior_without_sample_count_fails_open() -> None:
    scene = generate_synthetic_scene(
        SyntheticConfig(pulse="lp", nrays=180, nbins=220),
        seed=24,
    )
    static = (
        scene.truth_mask & int(SyntheticTruthFlag.STATIC_CLUTTER)
    ) != 0
    persistence = np.zeros(scene.dbzh.shape, dtype="float32")
    persistence[static] = 1.0

    result = classify_nuisance_echoes(
        scene.dbzh,
        scene.companions,
        pulse="lp",
        context=EvidenceContext(
            background_persistent_frequency=persistence,
            background_near_zero_vrad_frequency=persistence,
        ),
    )

    assert not result.nuisance(NuisanceFlag.STATIC_CLUTTER).any()


def test_learned_prior_rejects_new_echo_above_background_p90() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 30.0, dtype="float32")
    companions = {
        "CI": np.full(shape, 1.0, dtype="float32"),
        "VRADH": np.zeros(shape, dtype="float32"),
        "SQIH": np.full(shape, 0.8, dtype="float32"),
        "RHOHV": np.full(shape, 0.95, dtype="float32"),
        "ZDR": np.full(shape, 1.0, dtype="float32"),
        "PHIDP": np.full(shape, 10.0, dtype="float32"),
    }
    context = EvidenceContext(
        background_persistent_frequency=np.ones(shape, dtype="float32"),
        background_near_zero_vrad_frequency=np.ones(
            shape,
            dtype="float32",
        ),
        background_conditioned_sample_count=np.full(
            shape,
            48.0,
            dtype="float32",
        ),
        background_dbzh_p90=np.full(shape, 10.0, dtype="float32"),
    )

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="lp",
        context=context,
    )

    assert not result.remove_mask.any()
    assert not result.nuisance(NuisanceFlag.STATIC_CLUTTER).any()


def test_expected_but_missing_upper_elevation_fails_open() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")
    companions = {
        "CI": np.full(shape, 1.0, dtype="float32"),
        "VRADH": np.zeros(shape, dtype="float32"),
        "SQIH": np.full(shape, 0.8, dtype="float32"),
        "RHOHV": np.full(shape, 0.95, dtype="float32"),
        "ZDR": np.full(shape, 1.0, dtype="float32"),
        "PHIDP": np.full(shape, 10.0, dtype="float32"),
    }

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="lp",
        context=EvidenceContext(
            upper_elevation_required=True,
            background_persistent_frequency=np.ones(
                shape,
                dtype="float32",
            ),
            background_near_zero_vrad_frequency=np.ones(
                shape,
                dtype="float32",
            ),
            background_conditioned_sample_count=np.full(
                shape,
                48.0,
                dtype="float32",
            ),
            background_dbzh_p90=np.full(
                shape,
                12.0,
                dtype="float32",
            ),
        ),
    )

    assert not result.remove_mask.any()


def test_missing_companions_fail_open() -> None:
    scene = generate_synthetic_scene(
        SyntheticConfig(pulse="sp", nrays=90, nbins=120),
        seed=29,
    )

    result = classify_nuisance_echoes(scene.dbzh, {}, pulse="sp")

    assert result.counts["removed"] == 0
    assert not result.remove_mask.any()


def test_mismatched_context_shape_is_rejected() -> None:
    scene = generate_synthetic_scene(
        SyntheticConfig(pulse="lp", nrays=90, nbins=120),
        seed=31,
    )

    with pytest.raises(ValueError, match="upper-elevation"):
        classify_nuisance_echoes(
            scene.dbzh,
            scene.companions,
            pulse="lp",
            context=EvidenceContext(
                upper_elevation_dbzh=np.zeros((2, 2), dtype="float32")
            ),
        )


def test_dynamic_synthetic_geometry_moves_signal_and_transient_artifacts() -> None:
    first = generate_synthetic_scene(
        SyntheticConfig(
            pulse="lp",
            nrays=180,
            nbins=220,
            dynamic_geometry=True,
        ),
        seed=101,
    )
    second = generate_synthetic_scene(
        SyntheticConfig(
            pulse="lp",
            nrays=180,
            nbins=220,
            dynamic_geometry=True,
        ),
        seed=202,
    )
    first_static = (
        first.truth_mask & int(SyntheticTruthFlag.STATIC_CLUTTER)
    ) != 0
    second_static = (
        second.truth_mask & int(SyntheticTruthFlag.STATIC_CLUTTER)
    ) != 0
    first_ap = (
        first.truth_mask & int(SyntheticTruthFlag.ANOMALOUS_PROPAGATION)
    ) != 0
    second_ap = (
        second.truth_mask & int(SyntheticTruthFlag.ANOMALOUS_PROPAGATION)
    ) != 0

    assert _intersection_over_union(first_static, second_static) >= 0.45
    assert _intersection_over_union(first.retain_mask, second.retain_mask) < 0.50
    assert _intersection_over_union(first_ap, second_ap) < 0.25


def _intersection_over_union(first: np.ndarray, second: np.ndarray) -> float:
    union = np.asarray(first, dtype=bool) | np.asarray(second, dtype=bool)
    if not union.any():
        return 1.0
    intersection = np.asarray(first, dtype=bool) & np.asarray(second, dtype=bool)
    return float(intersection.sum() / union.sum())
