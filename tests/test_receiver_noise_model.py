from __future__ import annotations

import numpy as np
import pytest

from uk_wsr_visualizer.receiver_noise_model import (
    ReceiverNoiseModelConfig,
    fit_fixed_slope_receiver_noise,
    fit_range_corrected_receiver_noise,
)


def test_range_corrected_noise_fit_ignores_signal_tail() -> None:
    rng = np.random.default_rng(2401)
    shape = (360, 189)
    ranges = (np.arange(shape[1]) + 0.5) * 0.6
    expected_location = -27.3
    floor = 20.0 * np.log10(ranges) + expected_location
    values = np.broadcast_to(floor, shape).copy()
    values += rng.normal(0.0, 0.12, size=shape)
    values[40:100, 90:130] += 12.0
    seeds = np.ones(shape, dtype=bool)

    model = fit_range_corrected_receiver_noise(
        values,
        seeds,
        rstart_km=0.0,
        rscale_m=600.0,
    )

    assert model.qualified is True
    assert model.status == "qualified"
    assert model.range_slope_db_per_decade == pytest.approx(
        20.0,
        abs=0.1,
    )
    assert model.range_intercept_db == pytest.approx(
        expected_location,
        abs=0.05,
    )
    assert model.residual_location_db == pytest.approx(0.0, abs=0.05)
    assert model.supported_bin_count >= 130
    assert model.consistent_bin_fraction > 0.90
    assert model.compatible_mask[0, 150]
    assert not model.compatible_mask[60, 110]


def test_range_corrected_noise_fit_fails_open_without_range_law() -> None:
    rng = np.random.default_rng(2402)
    shape = (360, 189)
    values = rng.normal(5.0, 4.0, size=shape)
    seeds = np.ones(shape, dtype=bool)

    model = fit_range_corrected_receiver_noise(
        values,
        seeds,
        rstart_km=0.0,
        rscale_m=600.0,
    )

    assert model.qualified is False
    assert model.status == "nonphysical_range_slope"
    assert not model.compatible_mask.any()
    assert not model.valid_range_mask.any()


def test_fixed_slope_fit_recovers_a_minority_receiver_ridge() -> None:
    rng = np.random.default_rng(2410)
    shape = (360, 425)
    ranges = (np.arange(shape[1]) + 0.5) * 0.6
    ridge = 20.0 * np.log10(ranges) - 44.8
    values = rng.normal(7.0, 2.5, size=shape)
    receiver_truth = rng.random(shape) < 0.28
    values[receiver_truth] = (
        np.broadcast_to(ridge, shape)[receiver_truth]
        + rng.normal(0.0, 0.15, receiver_truth.sum())
    )
    seeds = np.ones(shape, dtype=bool)

    free_model = fit_range_corrected_receiver_noise(
        values,
        seeds,
        rstart_km=0.0,
        rscale_m=600.0,
    )
    fixed_model = fit_fixed_slope_receiver_noise(
        values,
        seeds,
        rstart_km=0.0,
        rscale_m=600.0,
    )

    assert free_model.qualified is False
    assert fixed_model.qualified is True
    assert fixed_model.status == "qualified_fixed_slope"
    assert fixed_model.fit_strategy == "fixed_slope_mode"
    assert fixed_model.range_slope_db_per_decade == 20.0
    assert fixed_model.range_intercept_db == pytest.approx(-44.8, abs=0.1)
    eligible_truth = receiver_truth & np.broadcast_to(
        fixed_model.valid_range_mask,
        shape,
    )
    true_positive = fixed_model.compatible_mask & eligible_truth
    assert true_positive.sum() / eligible_truth.sum() >= 0.95
    assert (
        true_positive.sum() / fixed_model.compatible_mask.sum()
        >= 0.975
    )


def test_fixed_slope_fit_rejects_a_broad_nonphysical_population() -> None:
    rng = np.random.default_rng(2411)
    shape = (360, 425)
    values = rng.normal(7.0, 4.0, size=shape)
    seeds = np.ones(shape, dtype=bool)

    model = fit_fixed_slope_receiver_noise(
        values,
        seeds,
        rstart_km=0.0,
        rscale_m=600.0,
    )

    assert model.qualified is False
    assert model.status == "fixed_slope_mode_not_qualified"
    assert not model.compatible_mask.any()
    assert not model.valid_range_mask.any()


def test_range_corrected_noise_fit_leaves_clipped_near_range_unsupported() -> None:
    rng = np.random.default_rng(2403)
    shape = (360, 425)
    ranges = (np.arange(shape[1]) + 0.5) * 0.6
    floor = 20.0 * np.log10(ranges) - 44.8
    values = np.broadcast_to(floor, shape).copy()
    values += rng.normal(0.0, 0.12, size=shape)
    values[:, ranges < 45.0] = -12.0
    seeds = np.ones(shape, dtype=bool)

    model = fit_range_corrected_receiver_noise(
        values,
        seeds,
        rstart_km=0.0,
        rscale_m=600.0,
    )

    assert model.qualified is True
    assert not model.valid_range_mask[ranges < 30.0].any()
    assert model.valid_range_mask[ranges > 50.0].mean() > 0.95


def test_range_corrected_noise_fit_ignores_repeated_encoded_floor() -> None:
    rng = np.random.default_rng(2404)
    shape = (360, 425)
    ranges = (np.arange(shape[1]) + 0.5) * 0.6
    floor = 20.0 * np.log10(ranges) - 44.8
    values = np.broadcast_to(floor, shape).copy()
    values += rng.normal(0.0, 0.15, size=shape)
    values[:, 300::3] = -32.0
    seeds = np.ones(shape, dtype=bool)

    model = fit_range_corrected_receiver_noise(
        values,
        seeds,
        rstart_km=0.0,
        rscale_m=600.0,
    )

    assert model.qualified is True
    assert model.range_intercept_db == pytest.approx(-44.8, abs=0.08)


def test_range_corrected_noise_fit_rejects_invalid_geometry() -> None:
    with pytest.raises(ValueError, match="same 2-D shape"):
        fit_range_corrected_receiver_noise(
            np.ones((2, 3)),
            np.ones((2, 2), dtype=bool),
            rstart_km=0.0,
            rscale_m=600.0,
        )

    with pytest.raises(ValueError, match="positive"):
        fit_range_corrected_receiver_noise(
            np.ones((2, 3)),
            np.ones((2, 3), dtype=bool),
            rstart_km=0.0,
            rscale_m=0.0,
            config=ReceiverNoiseModelConfig(minimum_seed_count=1),
        )
