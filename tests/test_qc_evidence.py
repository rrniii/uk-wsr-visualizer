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
        ),
    )

    static_prediction = result.nuisance(NuisanceFlag.STATIC_CLUTTER)
    assert (static_prediction & static).sum() / static.sum() >= 0.85
    assert not np.any(static_prediction & scene.retain_mask)


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
