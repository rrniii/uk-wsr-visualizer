from __future__ import annotations

import numpy as np
import pytest

from uk_wsr_visualizer.background_model_v3 import (
    BACKGROUND_MODEL_V3_STATISTICS_VERSION,
)
from uk_wsr_visualizer.qc_evidence import (
    EVIDENCE_VERSION,
    EvidenceContext,
    EvidenceFlag,
    NuisanceFlag,
    classify_nuisance_echoes,
)
from uk_wsr_visualizer.qc_synthetic import (
    SyntheticConfig,
    SyntheticTruthFlag,
    evaluate_predicted_removal,
    generate_synthetic_scene,
)


@pytest.mark.parametrize(
    ("pulse", "minimum_noise_recall", "minimum_interference_recall"),
    [
        ("lp", 0.40, 0.45),
        ("sp", 0.60, 0.29),
    ],
)
def test_multi_evidence_candidate_preserves_coherent_signals(
    pulse: str,
    minimum_noise_recall: float,
    minimum_interference_recall: float,
) -> None:
    scene = generate_synthetic_scene(
        SyntheticConfig(pulse=pulse, nrays=180, nbins=220),
        seed=19,
    )
    receiver_context = (
        EvidenceContext(
            previous_dbzh=scene.dbzh + 5.0,
            next_dbzh=scene.dbzh - 5.0,
            previous_vrad=np.full(
                scene.dbzh.shape,
                -40.0,
                dtype="float32",
            ),
            next_vrad=np.full(
                scene.dbzh.shape,
                40.0,
                dtype="float32",
            ),
        )
        if pulse == "lp"
        else None
    )

    result = classify_nuisance_echoes(
        scene.dbzh,
        scene.companions,
        pulse=pulse,
        rstart_km=scene.metadata["rstart_km"],
        rscale_m=scene.metadata["rscale_m"],
        context=receiver_context,
    )
    metrics = evaluate_predicted_removal(result.remove_mask, scene)

    assert result.version == EVIDENCE_VERSION
    assert metrics["retain_recall"] == 1.0
    assert metrics["high_signal_retain_recall"] == 1.0
    assert metrics["precision"] == 1.0
    assert (
        metrics["per_artifact"]["receiver_noise"]["recall"]
        >= minimum_noise_recall
    )
    assert (
        metrics["per_artifact"]["radial_interference"]["recall"]
        >= minimum_interference_recall
    )
    assert metrics["per_artifact"]["anomalous_propagation"]["recall"] == 0
    assert metrics["per_artifact"]["isolated_speckle"]["recall"] <= 0.025
    assert metrics["per_artifact"]["static_clutter"]["recall"] == 0


def test_physical_range_law_with_two_evidence_families_is_removed() -> None:
    dbzh, companions = _physical_receiver_case()
    shape = dbzh.shape

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="sp",
        rstart_km=0.0,
        rscale_m=600.0,
    )

    receiver = result.nuisance(NuisanceFlag.RECEIVER_NOISE)
    physical = (
        result.evidence_mask
        & int(EvidenceFlag.PHYSICAL_NOISE_RANGE_LAW)
    ) != 0
    assert result.metadata["receiver_noise_model"]["qualified"] is True
    assert receiver.sum() > shape[0] * 120
    assert np.all(~receiver | physical)
    assert receiver.sum() / physical.sum() >= 0.95
    assert not receiver[:, :45].any()


def test_receiver_noise_missing_geometry_fails_open() -> None:
    dbzh, companions = _physical_receiver_case()

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="sp",
    )

    assert not result.nuisance(NuisanceFlag.RECEIVER_NOISE).any()
    assert (
        result.metadata["receiver_noise_model"]["status"]
        == "missing_or_invalid_geometry"
    )


def test_required_receiver_cross_scan_context_missing_fails_open() -> None:
    dbzh, companions = _physical_receiver_case()

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="sp",
        rstart_km=0.0,
        rscale_m=600.0,
        context=EvidenceContext(
            receiver_noise_cross_scan_required=True,
        ),
    )

    assert result.metadata["receiver_noise_model"]["qualified"] is True
    assert result.counts["receiver_noise_candidate"] > 0
    assert result.counts["receiver_noise"] == 0
    assert (
        result.counts["receiver_noise_context_fail_open"]
        == result.counts["receiver_noise_candidate"]
    )
    assert (
        result.metadata["context"][
            "receiver_noise_cross_scan_required"
        ]
        is True
    )


def test_complete_receiver_cross_scan_coverage_allows_noise_removal() -> None:
    dbzh, companions = _physical_receiver_case()
    shape = dbzh.shape

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="sp",
        rstart_km=0.0,
        rscale_m=600.0,
        context=EvidenceContext(
            previous_dbzh=dbzh + 5.0,
            next_dbzh=dbzh - 5.0,
            previous_vrad=np.full(shape, -40.0, dtype="float32"),
            next_vrad=np.full(shape, 40.0, dtype="float32"),
            receiver_noise_cross_scan_required=True,
        ),
    )

    receiver = result.nuisance(NuisanceFlag.RECEIVER_NOISE)
    cross_scan = (
        result.evidence_mask
        & int(EvidenceFlag.RECEIVER_CROSS_SCAN_CONTEXT)
    ) != 0
    assert receiver.any()
    assert np.all(~receiver | cross_scan)
    assert result.counts["receiver_noise_context_fail_open"] == 0


def test_receiver_cross_scan_coverage_is_gate_specific() -> None:
    dbzh, companions = _physical_receiver_case()
    upper = np.full(dbzh.shape, np.nan, dtype="float32")
    upper[:, 100:] = dbzh[:, 100:] + 20.0

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="sp",
        rstart_km=0.0,
        rscale_m=600.0,
        context=EvidenceContext(
            upper_elevation_dbzh=upper,
            receiver_noise_cross_scan_required=True,
        ),
    )

    receiver = result.nuisance(NuisanceFlag.RECEIVER_NOISE)
    assert not receiver[:, :100].any()
    assert receiver[:, 100:].any()
    assert result.counts["receiver_noise_context_fail_open"] > 0


def test_lp_fixed_slope_mode_recovers_minority_ridge_with_full_context() -> None:
    dbzh, companions, receiver_truth = _minority_lp_receiver_case()
    shape = dbzh.shape
    no_context = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="lp",
        rstart_km=0.0,
        rscale_m=600.0,
    )

    assert (
        no_context.metadata["receiver_noise_model"]["fit_strategy"]
        == "fixed_slope_mode"
    )
    assert (
        no_context.metadata["receiver_noise_model"][
            "free_slope_qualified"
        ]
        is False
    )
    assert no_context.counts["receiver_noise_candidate"] > 0
    assert no_context.counts["receiver_noise"] == 0
    assert (
        no_context.counts["receiver_noise_context_fail_open"]
        == no_context.counts["receiver_noise_candidate"]
    )

    with_context = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="lp",
        rstart_km=0.0,
        rscale_m=600.0,
        context=EvidenceContext(
            previous_dbzh=dbzh + 5.0,
            next_dbzh=dbzh - 5.0,
            previous_vrad=np.full(shape, -40.0, dtype="float32"),
            next_vrad=np.full(shape, 40.0, dtype="float32"),
        ),
    )
    receiver = with_context.nuisance(NuisanceFlag.RECEIVER_NOISE)
    fixed_ridge = (
        with_context.evidence_mask
        & int(EvidenceFlag.FIXED_SLOPE_NOISE_RIDGE)
    ) != 0
    true_positive = receiver & receiver_truth

    assert receiver.any()
    assert np.all(~receiver | fixed_ridge)
    assert true_positive.sum() / receiver_truth.sum() >= 0.80
    assert true_positive.sum() / receiver.sum() >= 0.95
    assert (
        with_context.metadata["context"][
            "receiver_noise_internal_context_required"
        ]
        is True
    )


def test_sp_does_not_use_lp_fixed_slope_mode() -> None:
    dbzh, companions, _ = _minority_lp_receiver_case()

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="sp",
        rstart_km=0.0,
        rscale_m=600.0,
    )

    assert (
        result.metadata["receiver_noise_model"][
            "fixed_slope_attempted"
        ]
        is False
    )
    assert (
        result.metadata["receiver_noise_model"]["fit_strategy"]
        == "free_slope"
    )
    assert not result.nuisance(NuisanceFlag.RECEIVER_NOISE).any()


def test_correlated_polarimetric_symptoms_count_as_one_family() -> None:
    dbzh, companions = _physical_receiver_case()
    companions["VRADH"] = np.zeros(dbzh.shape, dtype="float32")

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="sp",
        rstart_km=0.0,
        rscale_m=600.0,
    )

    assert result.metadata["receiver_noise_model"]["qualified"] is True
    assert not result.nuisance(NuisanceFlag.RECEIVER_NOISE).any()


def test_nonphysical_weak_field_fails_open() -> None:
    dbzh, companions = _physical_receiver_case()
    rng = np.random.default_rng(91)
    dbzh[:] = rng.normal(4.0, 0.8, dbzh.shape)

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="sp",
        rstart_km=0.0,
        rscale_m=600.0,
    )

    assert result.metadata["receiver_noise_model"]["qualified"] is False
    assert not result.nuisance(NuisanceFlag.RECEIVER_NOISE).any()


def test_dualpol_anomaly_without_learned_static_evidence_is_retained() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 15.0, dtype="float32")
    checker = np.indices(shape).sum(axis=0) % 2
    rng = np.random.default_rng(17)
    companions = {
        "CI": np.full(shape, 1.0, dtype="float32"),
        "SQIH": np.full(shape, 0.4, dtype="float32"),
        "RHOHV": np.full(shape, 0.3, dtype="float32"),
        "ZDR": np.where(checker, 10.0, -4.0).astype("float32"),
        "PHIDP": np.where(checker, 170.0, -170.0).astype("float32"),
        "VRADH": np.zeros(shape, dtype="float32"),
    }

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="lp",
    )

    assert not result.remove_mask.any()
    assert not result.nuisance(NuisanceFlag.ANOMALOUS_PROPAGATION).any()


def test_learned_prior_requires_current_static_confirmation() -> None:
    scene = generate_synthetic_scene(
        SyntheticConfig(pulse="lp", nrays=180, nbins=220),
        seed=23,
    )
    static = (
        scene.truth_mask & int(SyntheticTruthFlag.STATIC_CLUTTER)
    ) != 0
    static_frequency = np.zeros(scene.dbzh.shape, dtype="float32")
    static_frequency[static] = 0.95
    companions = {
        name: np.asarray(values).copy()
        for name, values in scene.companions.items()
    }
    companions["SQIH"][static] = 0.4
    companions["RHOHV"][static] = 0.4

    result = classify_nuisance_echoes(
        scene.dbzh,
        companions,
        pulse="lp",
        context=_learned_context(
            scene.dbzh.shape,
            scene.dbzh,
            background_static_echo_date_frequency=static_frequency,
            background_distinct_date_count=np.full(
                scene.dbzh.shape,
                8.0,
                dtype="float32",
            ),
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
            temporal_context_required=True,
            previous_dbzh=scene.dbzh,
            next_dbzh=scene.dbzh,
            previous_vrad=scene.companions["VRADH"],
            next_vrad=scene.companions["VRADH"],
            background_statistics_version=(
                BACKGROUND_MODEL_V3_STATISTICS_VERSION
            ),
            background_static_echo_date_frequency=persistence,
        ),
    )

    assert not result.nuisance(NuisanceFlag.STATIC_CLUTTER).any()


@pytest.mark.parametrize(
    "missing_field",
    [
        "background_distinct_date_count",
        "background_static_echo_season_count",
        "background_static_echo_time_bucket_count",
        "background_static_dbzh_p10",
        "background_static_dbzh_median",
    ],
)
def test_learned_prior_missing_required_model_field_fails_open(
    missing_field: str,
) -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")

    result = classify_nuisance_echoes(
        dbzh,
        _static_companions(shape),
        pulse="lp",
        context=_learned_context(
            shape,
            dbzh,
            **{missing_field: None},
        ),
    )

    assert not result.nuisance(NuisanceFlag.STATIC_CLUTTER).any()
    assert result.metadata["context"]["learned_background"] is False


def test_old_learned_statistics_version_fails_open() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")

    result = classify_nuisance_echoes(
        dbzh,
        _static_companions(shape),
        pulse="lp",
        context=_learned_context(
            shape,
            dbzh,
            background_statistics_version="scan-weighted-v1",
        ),
    )

    assert not result.nuisance(NuisanceFlag.STATIC_CLUTTER).any()
    assert (
        result.metadata["context"][
            "learned_background_statistics_qualified"
        ]
        is False
    )


def test_required_temporal_context_missing_fails_open() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")
    companions = _static_companions(shape)

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="lp",
        context=_learned_context(
            shape,
            dbzh,
            temporal_context_required=True,
            previous_dbzh=None,
            next_dbzh=None,
            previous_vrad=None,
            next_vrad=None,
        ),
    )

    assert not result.nuisance(NuisanceFlag.STATIC_CLUTTER).any()
    assert result.metadata["context"]["temporal_context_count"] == 0
    assert result.metadata["context"]["temporal_context_complete"] is False
    assert result.metadata["context"]["temporal_context_required"] is True


def test_required_bracketing_temporal_context_confirms_static_clutter() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")
    companions = _nuisance_static_companions(shape)

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="lp",
        context=_learned_context(
            shape,
            dbzh,
            temporal_context_required=True,
            previous_dbzh=dbzh + 0.5,
            next_dbzh=dbzh - 0.5,
            previous_vrad=np.zeros(shape, dtype="float32"),
            next_vrad=np.zeros(shape, dtype="float32"),
        ),
    )

    assert result.nuisance(NuisanceFlag.STATIC_CLUTTER).all()
    assert result.metadata["context"]["temporal_context_count"] == 2
    assert result.metadata["context"]["temporal_context_complete"] is True
    assert (
        result.metadata["context"]["temporal_velocity_context_complete"]
        is True
    )


def test_evolving_echo_fails_learned_static_amplitude_gate() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")

    result = classify_nuisance_echoes(
        dbzh,
        _nuisance_static_companions(shape),
        pulse="lp",
        context=_learned_context(
            shape,
            dbzh,
            previous_dbzh=dbzh + 1.0,
            next_dbzh=dbzh - 1.0,
            previous_vrad=np.zeros(shape, dtype="float32"),
            next_vrad=np.zeros(shape, dtype="float32"),
        ),
    )

    assert not result.remove_mask.any()
    assert not result.nuisance(NuisanceFlag.STATIC_CLUTTER).any()
    assert result.counts["learned_static_amplitude_stability"] == 0


def test_learned_prior_does_not_delete_high_quality_stationary_echo() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")

    result = classify_nuisance_echoes(
        dbzh,
        _static_companions(shape),
        pulse="lp",
        context=_learned_context(shape, dbzh),
    )

    assert not result.remove_mask.any()
    assert not result.nuisance(NuisanceFlag.STATIC_CLUTTER).any()
    assert (
        result.counts["quality_coherent_signal_protected"]
        == dbzh.size
    )


def test_advection_protects_moving_echo_from_learned_static_prior() -> None:
    shape = (15, 15)
    gate_gradient = np.arange(shape[1], dtype="float32") * 0.75
    dbzh = np.broadcast_to(
        10.0 + gate_gradient,
        shape,
    ).copy()
    previous = np.roll(dbzh, -1, axis=1)
    previous[:, -1] = np.nan
    following = np.roll(dbzh, 1, axis=1)
    following[:, 0] = np.nan

    result = classify_nuisance_echoes(
        dbzh,
        _nuisance_static_companions(shape),
        pulse="lp",
        context=_learned_context(
            shape,
            dbzh,
            previous_dbzh=previous,
            next_dbzh=following,
        ),
    )

    interior = np.zeros(shape, dtype=bool)
    interior[:, 1:-1] = True
    assert result.counts["temporal_advection_protected"] > 0
    assert not np.any(result.remove_mask & interior)
    assert np.all(result.protected_mask[interior])


def test_low_elevation_transient_nonmeteorological_echo_is_diagnostic_only() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")

    result = classify_nuisance_echoes(
        dbzh,
        _nuisance_static_companions(shape),
        pulse="lp",
        context=EvidenceContext(
            previous_dbzh=np.full(shape, 20.0, dtype="float32"),
            next_dbzh=np.full(shape, 20.0, dtype="float32"),
            previous_vrad=np.zeros(shape, dtype="float32"),
            next_vrad=np.zeros(shape, dtype="float32"),
            elevation_deg=0.5,
        ),
    )

    assert not result.nuisance(NuisanceFlag.ANOMALOUS_PROPAGATION).any()
    assert not result.remove_mask.any()
    assert (
        result.counts["independent_anomalous_propagation_candidate"]
        == dbzh.size
    )


def test_high_elevation_transient_echo_is_not_classified_as_ap() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")

    result = classify_nuisance_echoes(
        dbzh,
        _nuisance_static_companions(shape),
        pulse="lp",
        context=EvidenceContext(
            previous_dbzh=np.full(shape, 20.0, dtype="float32"),
            next_dbzh=np.full(shape, 20.0, dtype="float32"),
            previous_vrad=np.zeros(shape, dtype="float32"),
            next_vrad=np.zeros(shape, dtype="float32"),
            elevation_deg=4.0,
        ),
    )

    assert not result.remove_mask.any()
    assert not result.nuisance(NuisanceFlag.ANOMALOUS_PROPAGATION).any()


def test_persistent_echo_without_learned_prior_is_not_ap() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")

    result = classify_nuisance_echoes(
        dbzh,
        _nuisance_static_companions(shape),
        pulse="lp",
        context=EvidenceContext(
            previous_dbzh=dbzh.copy(),
            next_dbzh=dbzh.copy(),
            previous_vrad=np.zeros(shape, dtype="float32"),
            next_vrad=np.zeros(shape, dtype="float32"),
            elevation_deg=0.5,
        ),
    )

    assert not result.remove_mask.any()
    assert not result.nuisance(NuisanceFlag.ANOMALOUS_PROPAGATION).any()


def test_temporally_inconsistent_echo_is_retained_despite_learned_prior() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 30.0, dtype="float32")
    companions = _static_companions(shape)

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="lp",
        context=_learned_context(
            shape,
            dbzh,
            temporal_context_required=True,
            previous_dbzh=np.full(shape, 12.0, dtype="float32"),
            next_dbzh=np.full(shape, 18.0, dtype="float32"),
            previous_vrad=np.zeros(shape, dtype="float32"),
            next_vrad=np.zeros(shape, dtype="float32"),
        ),
    )

    assert not result.remove_mask.any()
    assert not result.nuisance(NuisanceFlag.STATIC_CLUTTER).any()


def test_learned_clutter_missing_temporal_velocity_fails_open() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")

    result = classify_nuisance_echoes(
        dbzh,
        _static_companions(shape),
        pulse="lp",
        context=_learned_context(
            shape,
            dbzh,
            temporal_context_required=True,
            previous_dbzh=dbzh,
            next_dbzh=dbzh,
            previous_vrad=None,
            next_vrad=None,
        ),
    )

    assert not result.remove_mask.any()
    assert (
        result.metadata["context"]["temporal_velocity_context_complete"]
        is False
    )


def test_vertical_geometry_disables_two_dimensional_learned_background() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")

    result = classify_nuisance_echoes(
        dbzh,
        _static_companions(shape),
        pulse="lp",
        context=_learned_context(
            shape,
            dbzh,
            temporal_context_required=True,
            previous_dbzh=dbzh,
            next_dbzh=dbzh,
            previous_vrad=np.zeros(shape, dtype="float32"),
            next_vrad=np.zeros(shape, dtype="float32"),
            learned_background_allowed=False,
        ),
    )

    assert not result.remove_mask.any()
    assert result.metadata["context"]["learned_background_allowed"] is False


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
    context = _learned_context(
        shape,
        dbzh,
        background_static_dbzh_p90=np.full(
            shape,
            10.0,
            dtype="float32",
        ),
    )

    result = classify_nuisance_echoes(
        dbzh,
        companions,
        pulse="lp",
        context=context,
    )

    assert not result.remove_mask.any()
    assert not result.nuisance(NuisanceFlag.STATIC_CLUTTER).any()


def test_learned_prior_rejects_echo_above_background_median_guard() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")

    result = classify_nuisance_echoes(
        dbzh,
        _nuisance_static_companions(shape),
        pulse="lp",
        context=_learned_context(
            shape,
            dbzh,
            background_static_dbzh_p10=np.full(
                shape,
                4.0,
                dtype="float32",
            ),
            background_static_dbzh_median=np.full(
                shape,
                6.0,
                dtype="float32",
            ),
            background_static_dbzh_p90=np.full(
                shape,
                12.0,
                dtype="float32",
            ),
        ),
    )

    assert not result.remove_mask.any()


def test_learned_prior_rejects_broad_background_distribution() -> None:
    shape = (9, 9)
    dbzh = np.full(shape, 10.0, dtype="float32")

    result = classify_nuisance_echoes(
        dbzh,
        _nuisance_static_companions(shape),
        pulse="lp",
        context=_learned_context(
            shape,
            dbzh,
            background_static_dbzh_p10=np.zeros(shape, dtype="float32"),
            background_static_dbzh_median=np.full(
                shape,
                8.0,
                dtype="float32",
            ),
            background_static_dbzh_p90=np.full(
                shape,
                10.0,
                dtype="float32",
            ),
        ),
    )

    assert not result.remove_mask.any()


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
        context=_learned_context(
            shape,
            dbzh,
            upper_elevation_required=True,
            background_static_dbzh_p90=np.full(
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


def _static_companions(shape: tuple[int, int]) -> dict[str, np.ndarray]:
    return {
        "CI": np.full(shape, 1.0, dtype="float32"),
        "VRADH": np.zeros(shape, dtype="float32"),
        "SQIH": np.full(shape, 0.8, dtype="float32"),
        "RHOHV": np.full(shape, 0.95, dtype="float32"),
        "ZDR": np.full(shape, 1.0, dtype="float32"),
        "PHIDP": np.full(shape, 10.0, dtype="float32"),
    }


def _nuisance_static_companions(
    shape: tuple[int, int],
) -> dict[str, np.ndarray]:
    checker = np.indices(shape).sum(axis=0) % 2
    return {
        "CI": np.full(shape, 1.0, dtype="float32"),
        "VRADH": np.zeros(shape, dtype="float32"),
        "SQIH": np.full(shape, 0.4, dtype="float32"),
        "RHOHV": np.full(shape, 0.4, dtype="float32"),
        "ZDR": np.where(checker, 10.0, -4.0).astype("float32"),
        "PHIDP": np.where(checker, 170.0, -170.0).astype("float32"),
    }


def _learned_context(
    shape: tuple[int, int],
    dbzh: np.ndarray,
    **overrides: object,
) -> EvidenceContext:
    values: dict[str, object] = {
        "previous_dbzh": np.asarray(dbzh, dtype="float32"),
        "next_dbzh": np.asarray(dbzh, dtype="float32"),
        "previous_vrad": np.zeros(shape, dtype="float32"),
        "next_vrad": np.zeros(shape, dtype="float32"),
        "temporal_context_required": True,
        "background_statistics_version": (
            BACKGROUND_MODEL_V3_STATISTICS_VERSION
        ),
        "background_distinct_date_count": np.full(
            shape,
            8.0,
            dtype="float32",
        ),
        "background_static_echo_date_frequency": np.ones(
            shape,
            dtype="float32",
        ),
        "background_static_echo_season_count": np.full(
            shape,
            4.0,
            dtype="float32",
        ),
        "background_static_echo_time_bucket_count": np.full(
            shape,
            2.0,
            dtype="float32",
        ),
        "background_static_dbzh_p10": (
            np.asarray(dbzh, dtype="float32") - 1.0
        ),
        "background_static_dbzh_median": np.asarray(
            dbzh,
            dtype="float32",
        ),
        "background_static_dbzh_p90": (
            np.asarray(dbzh, dtype="float32") + 1.0
        ),
    }
    values.update(overrides)
    return EvidenceContext(**values)


def _physical_receiver_case() -> tuple[
    np.ndarray,
    dict[str, np.ndarray],
]:
    shape = (180, 220)
    ranges_km = (np.arange(shape[1]) + 0.5) * 0.6
    profile = 20.0 * np.log10(ranges_km) - 27.5
    dbzh = np.broadcast_to(profile, shape).astype("float32").copy()
    checker = np.indices(shape).sum(axis=0) % 2
    rng = np.random.default_rng(17)
    companions = {
        "CI": np.full(shape, 7.0, dtype="float32"),
        "SQIH": np.full(shape, 0.01, dtype="float32"),
        "RHOHV": np.full(shape, 0.1, dtype="float32"),
        "ZDR": np.where(checker, 10.0, -4.0).astype("float32"),
        "PHIDP": np.where(checker, 170.0, -170.0).astype("float32"),
        "VRADH": rng.uniform(-30.0, 30.0, shape).astype("float32"),
    }
    return dbzh, companions


def _minority_lp_receiver_case() -> tuple[
    np.ndarray,
    dict[str, np.ndarray],
    np.ndarray,
]:
    rng = np.random.default_rng(23)
    shape = (180, 425)
    ranges_km = (np.arange(shape[1]) + 0.5) * 0.6
    profile = 20.0 * np.log10(ranges_km) - 44.8
    receiver_truth = rng.random(shape) < 0.30
    dbzh = rng.normal(7.0, 2.5, shape).astype("float32")
    dbzh[receiver_truth] = (
        np.broadcast_to(profile, shape)[receiver_truth]
        + rng.normal(0.0, 0.15, receiver_truth.sum())
    )
    checker = np.indices(shape).sum(axis=0) % 2
    companions = {
        "CI": np.full(shape, 7.0, dtype="float32"),
        "SQIH": np.full(shape, 0.01, dtype="float32"),
        "RHOHV": np.full(shape, 0.1, dtype="float32"),
        "ZDR": np.where(checker, 10.0, -4.0).astype("float32"),
        "PHIDP": np.where(checker, 170.0, -170.0).astype("float32"),
        "VRADH": rng.uniform(-30.0, 30.0, shape).astype("float32"),
    }
    return dbzh, companions, receiver_truth
