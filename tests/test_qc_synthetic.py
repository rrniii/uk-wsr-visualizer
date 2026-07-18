from __future__ import annotations

import numpy as np
import pytest

from uk_wsr_visualizer.qc_synthetic import (
    SyntheticConfig,
    SyntheticTruthFlag,
    evaluate_predicted_removal,
    generate_synthetic_scene,
    inject_artifacts_into_base,
)


def test_synthetic_scene_is_deterministic_and_contains_every_truth_class() -> None:
    first = generate_synthetic_scene(SyntheticConfig(pulse="sp", nrays=180, nbins=220), seed=42)
    second = generate_synthetic_scene(SyntheticConfig(pulse="sp", nrays=180, nbins=220), seed=42)

    np.testing.assert_equal(first.dbzh, second.dbzh)
    np.testing.assert_array_equal(first.truth_mask, second.truth_mask)
    np.testing.assert_array_equal(first.retain_mask, second.retain_mask)
    assert not np.any(first.remove_mask & first.retain_mask)
    assert first.retain_mask.sum() > 0
    for flag in SyntheticTruthFlag:
        assert ((first.truth_mask & int(flag)) != 0).sum() > 0
    assert all(values.shape == first.dbzh.shape for values in first.companions.values())


def test_sp_receiver_noise_pedestal_is_higher_than_lp() -> None:
    lp = generate_synthetic_scene(SyntheticConfig(pulse="lp", nrays=180, nbins=220), seed=4)
    sp = generate_synthetic_scene(SyntheticConfig(pulse="sp", nrays=180, nbins=220), seed=4)
    lp_noise = (lp.truth_mask & int(SyntheticTruthFlag.RECEIVER_NOISE)) != 0
    sp_noise = (sp.truth_mask & int(SyntheticTruthFlag.RECEIVER_NOISE)) != 0
    ranges = (np.arange(220) + 0.5) * 0.6
    range_law = 20.0 * np.log10(ranges)
    lp_profile = np.broadcast_to(
        np.maximum(range_law - 45.0, -32.0),
        lp.dbzh.shape,
    )
    sp_profile = np.broadcast_to(
        np.maximum(range_law - 27.5, -18.0),
        sp.dbzh.shape,
    )

    assert float(np.nanmedian(lp.dbzh[lp_noise])) == pytest.approx(
        float(np.median(lp_profile[lp_noise])),
        abs=0.25,
    )
    assert float(np.nanmedian(sp.dbzh[sp_noise])) == pytest.approx(
        float(np.median(sp_profile[sp_noise])),
        abs=0.25,
    )
    assert (
        float(np.nanmedian(sp.dbzh[sp_noise]))
        - float(np.nanmedian(lp.dbzh[lp_noise]))
        > 15.0
    )


def test_perfect_prediction_scores_artifact_and_retention_as_one() -> None:
    scene = generate_synthetic_scene(SyntheticConfig(nrays=120, nbins=160), seed=7)

    metrics = evaluate_predicted_removal(scene.remove_mask, scene)

    assert metrics["precision"] == 1.0
    assert metrics["artifact_recall"] == 1.0
    assert metrics["retain_recall"] == 1.0
    assert metrics["coherent_signal_removal_fraction"] == 0.0
    assert metrics["high_signal_retain_recall"] == 1.0
    assert all(item["recall"] == 1.0 for item in metrics["per_artifact"].values())


def test_remove_everything_exposes_coherent_signal_failure() -> None:
    scene = generate_synthetic_scene(SyntheticConfig(nrays=120, nbins=160), seed=8)

    metrics = evaluate_predicted_removal(np.ones(scene.dbzh.shape, dtype=bool), scene)

    assert metrics["artifact_recall"] == 1.0
    assert metrics["retain_recall"] == 0.0
    assert metrics["coherent_signal_removal_fraction"] == 1.0
    assert metrics["precision"] < 1.0


def test_semi_synthetic_injection_preserves_protected_base_signal() -> None:
    base = np.full((120, 160), np.nan, dtype="float32")
    base[20:50, 30:70] = 25.0
    protected = np.isfinite(base)

    scene = inject_artifacts_into_base(
        base,
        pulse="sp",
        seed=11,
        protected_mask=protected,
    )

    np.testing.assert_array_equal(scene.dbzh[protected], base[protected])
    assert not np.any(scene.remove_mask & protected)
    assert scene.remove_mask.sum() > 0
    for flag in SyntheticTruthFlag:
        assert ((scene.truth_mask & int(flag)) != 0).sum() > 0


def test_semi_synthetic_injection_honours_a_larger_exclusion_mask() -> None:
    base = np.full((120, 160), np.nan, dtype="float32")
    protected = np.zeros(base.shape, dtype=bool)
    protected[30, 40] = True
    exclusion = protected.copy()
    exclusion[29:32, 39:42] = True

    scene = inject_artifacts_into_base(
        base,
        pulse="lp",
        seed=19,
        protected_mask=protected,
        artifact_exclusion_mask=exclusion,
    )

    np.testing.assert_array_equal(scene.retain_mask, protected)
    assert not np.any(scene.remove_mask & exclusion)
    assert scene.metadata["retain_count"] == 1
    assert scene.metadata["artifact_exclusion_count"] == 9
