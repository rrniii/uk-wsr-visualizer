"""Physics-informed receiver-noise evidence for polar reflectivity scans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .dependencies import require_numpy


@dataclass(frozen=True)
class ReceiverNoiseModelConfig:
    """Conservative fit controls for a range-corrected noise pedestal."""

    minimum_fit_range_km: float = 30.0
    minimum_seed_count: int = 1000
    minimum_seed_rays_per_bin: int = 20
    minimum_supported_bins: int = 20
    minimum_supported_span_km: float = 20.0
    minimum_range_slope_db_per_decade: float = 15.0
    maximum_range_slope_db_per_decade: float = 25.0
    robust_fit_iterations: int = 4
    robust_fit_minimum_error_db: float = 0.75
    robust_fit_sigma: float = 3.5
    residual_histogram_bin_db: float = 0.10
    residual_mode_band_db: float = 2.0
    per_bin_support_band_db: float = 1.0
    minimum_per_bin_mode_fraction: float = 0.10
    maximum_per_bin_error_db: float = 0.75
    minimum_consistent_bin_fraction: float = 0.50
    maximum_fit_median_error_db: float = 0.50
    minimum_scale_db: float = 0.10
    maximum_scale_db: float = 1.00
    upper_quantile_sigma: float = 3.0
    lower_quantile_sigma: float = 3.0
    fixed_slope_db_per_decade: float = 20.0
    fixed_slope_candidate_peak_count: int = 64
    minimum_fixed_slope_mode_count: int = 250
    minimum_fixed_slope_mode_fraction: float = 0.04
    minimum_fixed_slope_per_bin_mode_fraction: float = 0.05
    minimum_fixed_slope_consistent_bin_fraction: float = 0.30
    minimum_fixed_slope_range_span_fraction: float = 0.30
    maximum_fixed_slope_raw_scale_db: float = 1.00
    fixed_slope_compatibility_sigma: float = 2.50
    encoded_floor_minimum_fraction: float = 0.01
    encoded_floor_tolerance_db: float = 0.05


@dataclass(frozen=True)
class ReceiverNoiseModel:
    """Fitted range law and the bins where it is independently supported."""

    status: str
    qualified: bool
    fit_strategy: str
    floor_profile_dbzh: Any
    compatible_mask: Any
    valid_range_mask: Any
    residual_location_db: float | None
    residual_scale_db: float | None
    lower_residual_db: float | None
    upper_residual_db: float | None
    range_slope_db_per_decade: float | None
    range_intercept_db: float | None
    seed_count: int
    supported_bin_count: int
    supported_span_km: float
    consistent_bin_fraction: float
    fit_median_error_db: float | None


def fit_range_corrected_receiver_noise(
    dbzh: Any,
    seed_mask: Any,
    *,
    rstart_km: float,
    rscale_m: float,
    config: ReceiverNoiseModelConfig | None = None,
) -> ReceiverNoiseModel:
    """Fit the radar-equation noise law without treating weak echoes as labels.

    Receiver power that is approximately constant before range correction
    appears in reflectivity as ``20 log10(range_km) + constant``. The fit uses
    only externally supplied nuisance seeds and qualifies only range bins that
    independently support that law. Unsupported or ambiguous scans fail open.
    """

    np = require_numpy()
    active = config or ReceiverNoiseModelConfig()
    values = np.asarray(dbzh, dtype="float32")
    seeds = np.asarray(seed_mask, dtype=bool)
    if values.ndim != 2 or seeds.shape != values.shape:
        raise ValueError("dbzh and seed_mask must have the same 2-D shape")
    if rscale_m <= 0:
        raise ValueError("rscale_m must be positive")

    ranges_km = (
        float(rstart_km)
        + (np.arange(values.shape[1], dtype="float64") + 0.5)
        * float(rscale_m)
        / 1000.0
    )
    finite_range = np.isfinite(ranges_km) & (ranges_km > 0.0)
    log_range = np.full(ranges_km.shape, np.nan, dtype="float64")
    log_range[finite_range] = np.log10(ranges_km[finite_range])
    fit_range = ranges_km >= float(active.minimum_fit_range_km)
    encoded_floor = _encoded_floor_mask(values, active)
    fit_seed = (
        seeds
        & np.isfinite(values)
        & np.isfinite(log_range)[np.newaxis, :]
        & fit_range[np.newaxis, :]
        & ~encoded_floor
    )
    seed_count = int(fit_seed.sum())
    if seed_count < int(active.minimum_seed_count):
        return _failed_model(
            values.shape,
            "insufficient_seed_count",
            seed_count=seed_count,
        )

    per_bin_location = np.full(values.shape[1], np.nan, dtype="float64")
    candidate_bins = np.zeros(values.shape[1], dtype=bool)
    for gate in range(values.shape[1]):
        gate_seed = fit_seed[:, gate]
        if int(gate_seed.sum()) < int(active.minimum_seed_rays_per_bin):
            continue
        candidate_bins[gate] = True
        per_bin_location[gate] = float(
            np.median(values[gate_seed, gate])
        )
    if int(candidate_bins.sum()) < int(active.minimum_supported_bins):
        return _failed_model(
            values.shape,
            "insufficient_range_bins",
            seed_count=seed_count,
        )
    slope, intercept, fit_inliers = _robust_range_fit(
        log_range[candidate_bins],
        per_bin_location[candidate_bins],
        config=active,
    )
    if (
        slope is None
        or intercept is None
        or slope < float(active.minimum_range_slope_db_per_decade)
        or slope > float(active.maximum_range_slope_db_per_decade)
    ):
        return _failed_model(
            values.shape,
            "nonphysical_range_slope",
            seed_count=seed_count,
            range_slope_db_per_decade=slope,
            range_intercept_db=intercept,
        )

    base_profile = slope * log_range + intercept
    residual = values.astype("float64") - base_profile[np.newaxis, :]
    seed_residuals = residual[fit_seed]
    location = _histogram_mode(
        seed_residuals,
        bin_width=float(active.residual_histogram_bin_db),
    )
    if location is None:
        return _failed_model(
            values.shape,
            "residual_mode_unavailable",
            seed_count=seed_count,
            range_slope_db_per_decade=slope,
            range_intercept_db=intercept,
        )

    mode_neighbours = seed_residuals[
        np.abs(seed_residuals - location)
        <= float(active.residual_mode_band_db)
    ]
    if mode_neighbours.size < int(active.minimum_seed_count):
        return _failed_model(
            values.shape,
            "insufficient_mode_support",
            seed_count=seed_count,
            range_slope_db_per_decade=slope,
            range_intercept_db=intercept,
        )
    location = float(np.median(mode_neighbours))
    mad = float(np.median(np.abs(mode_neighbours - location)))
    scale = min(
        float(active.maximum_scale_db),
        max(float(active.minimum_scale_db), 1.4826 * mad),
    )
    upper_residual = location + float(active.upper_quantile_sigma) * scale

    valid_range = np.zeros(values.shape[1], dtype=bool)
    per_bin_errors = []
    candidate_bin_count = int(candidate_bins.sum())
    for gate in range(values.shape[1]):
        if not candidate_bins[gate]:
            continue
        gate_seed = fit_seed[:, gate]
        gate_residual = residual[gate_seed, gate]
        near_mode = (
            np.abs(gate_residual - location)
            <= float(active.per_bin_support_band_db)
        )
        mode_fraction = float(near_mode.mean())
        if mode_fraction < float(active.minimum_per_bin_mode_fraction):
            continue
        gate_location = float(np.median(gate_residual))
        error = abs(gate_location - location)
        if error > float(active.maximum_per_bin_error_db):
            continue
        valid_range[gate] = True
        per_bin_errors.append(error)

    supported_bins = int(valid_range.sum())
    consistent_fraction = (
        supported_bins / candidate_bin_count
        if candidate_bin_count
        else 0.0
    )
    supported_span = _supported_span_km(ranges_km, valid_range)
    median_error = (
        float(np.median(np.asarray(per_bin_errors, dtype="float64")))
        if per_bin_errors
        else None
    )
    qualified = bool(
        supported_bins >= int(active.minimum_supported_bins)
        and supported_span >= float(active.minimum_supported_span_km)
        and consistent_fraction
        >= float(active.minimum_consistent_bin_fraction)
        and median_error is not None
        and median_error <= float(active.maximum_fit_median_error_db)
        and int(fit_inliers.sum()) >= int(active.minimum_supported_bins)
    )
    if not qualified:
        valid_range[:] = False

    profile = np.full(values.shape[1], np.nan, dtype="float32")
    profile[valid_range] = (
        base_profile[valid_range] + location
    ).astype("float32")
    compatible = (
        np.isfinite(values)
        & valid_range[np.newaxis, :]
        & (residual <= upper_residual)
    )
    return ReceiverNoiseModel(
        status="qualified" if qualified else "insufficient_physical_support",
        qualified=qualified,
        fit_strategy="free_slope",
        floor_profile_dbzh=profile,
        compatible_mask=compatible,
        valid_range_mask=valid_range,
        residual_location_db=location,
        residual_scale_db=scale,
        lower_residual_db=None,
        upper_residual_db=upper_residual,
        range_slope_db_per_decade=slope,
        range_intercept_db=intercept,
        seed_count=seed_count,
        supported_bin_count=supported_bins,
        supported_span_km=supported_span,
        consistent_bin_fraction=consistent_fraction,
        fit_median_error_db=median_error,
    )


def fit_fixed_slope_receiver_noise(
    dbzh: Any,
    seed_mask: Any,
    *,
    rstart_km: float,
    rscale_m: float,
    config: ReceiverNoiseModelConfig | None = None,
) -> ReceiverNoiseModel:
    """Find a minority receiver pedestal with the fixed radar-equation slope.

    Unlike the free-slope fit, this path does not require the receiver
    pedestal to dominate each range bin. It searches several narrow modes of
    ``DBZH - 20 log10(range_km)`` and qualifies a mode only when independent
    range bins support it. The resulting compatibility band is two-sided so
    unrelated weaker echoes are not absorbed into the receiver mask.
    """

    np = require_numpy()
    active = config or ReceiverNoiseModelConfig()
    values = np.asarray(dbzh, dtype="float32")
    seeds = np.asarray(seed_mask, dtype=bool)
    if values.ndim != 2 or seeds.shape != values.shape:
        raise ValueError("dbzh and seed_mask must have the same 2-D shape")
    if rscale_m <= 0:
        raise ValueError("rscale_m must be positive")

    ranges_km = (
        float(rstart_km)
        + (np.arange(values.shape[1], dtype="float64") + 0.5)
        * float(rscale_m)
        / 1000.0
    )
    finite_range = np.isfinite(ranges_km) & (ranges_km > 0.0)
    log_range = np.full(ranges_km.shape, np.nan, dtype="float64")
    log_range[finite_range] = np.log10(ranges_km[finite_range])
    fit_range = ranges_km >= float(active.minimum_fit_range_km)
    encoded_floor = _encoded_floor_mask(values, active)
    fit_seed = (
        seeds
        & np.isfinite(values)
        & np.isfinite(log_range)[np.newaxis, :]
        & fit_range[np.newaxis, :]
        & ~encoded_floor
    )
    seed_count = int(fit_seed.sum())
    if seed_count < int(active.minimum_seed_count):
        return _failed_model(
            values.shape,
            "insufficient_seed_count",
            seed_count=seed_count,
            fit_strategy="fixed_slope_mode",
        )

    slope = float(active.fixed_slope_db_per_decade)
    base_profile = slope * log_range
    residual = values.astype("float64") - base_profile[np.newaxis, :]
    seed_residuals = residual[fit_seed]
    candidate_bins = np.asarray(
        fit_seed.sum(axis=0) >= int(active.minimum_seed_rays_per_bin),
        dtype=bool,
    )
    candidate_bin_count = int(candidate_bins.sum())
    if candidate_bin_count < int(active.minimum_supported_bins):
        return _failed_model(
            values.shape,
            "insufficient_range_bins",
            seed_count=seed_count,
            fit_strategy="fixed_slope_mode",
            range_slope_db_per_decade=slope,
        )

    peaks = _histogram_peak_locations(
        seed_residuals,
        bin_width=float(active.residual_histogram_bin_db),
        maximum_count=int(active.fixed_slope_candidate_peak_count),
        minimum_separation_db=float(active.per_bin_support_band_db),
    )
    best: dict[str, Any] | None = None
    for peak in peaks:
        mode_neighbours = seed_residuals[
            np.abs(seed_residuals - peak)
            <= float(active.residual_mode_band_db)
        ]
        if mode_neighbours.size < int(
            active.minimum_fixed_slope_mode_count
        ):
            continue
        mode_fraction = float(mode_neighbours.size / seed_count)
        if mode_fraction < float(
            active.minimum_fixed_slope_mode_fraction
        ):
            continue
        location = float(np.median(mode_neighbours))
        mad = float(np.median(np.abs(mode_neighbours - location)))
        raw_scale = 1.4826 * mad
        if raw_scale > float(
            active.maximum_fixed_slope_raw_scale_db
        ):
            continue
        scale = min(
            float(active.maximum_scale_db),
            max(float(active.minimum_scale_db), raw_scale),
        )

        valid_range = np.zeros(values.shape[1], dtype=bool)
        per_bin_errors: list[float] = []
        for gate in np.flatnonzero(candidate_bins):
            gate_seed = fit_seed[:, gate]
            gate_residual = residual[gate_seed, gate]
            near_mode = (
                np.abs(gate_residual - location)
                <= float(active.per_bin_support_band_db)
            )
            if float(near_mode.mean()) < float(
                active.minimum_fixed_slope_per_bin_mode_fraction
            ):
                continue
            local_residuals = gate_residual[near_mode]
            if local_residuals.size == 0:
                continue
            gate_location = float(np.median(local_residuals))
            error = abs(gate_location - location)
            if error > float(active.maximum_per_bin_error_db):
                continue
            valid_range[gate] = True
            per_bin_errors.append(error)

        supported_bins = int(valid_range.sum())
        consistent_fraction = supported_bins / candidate_bin_count
        supported_span = _supported_span_km(ranges_km, valid_range)
        fit_domain_span = _supported_span_km(ranges_km, candidate_bins)
        required_span = max(
            float(active.minimum_supported_span_km),
            float(active.minimum_fixed_slope_range_span_fraction)
            * fit_domain_span,
        )
        median_error = (
            float(np.median(np.asarray(per_bin_errors, dtype="float64")))
            if per_bin_errors
            else None
        )
        qualified = bool(
            supported_bins >= int(active.minimum_supported_bins)
            and supported_span >= required_span
            and consistent_fraction
            >= float(
                active.minimum_fixed_slope_consistent_bin_fraction
            )
            and median_error is not None
            and median_error <= float(active.maximum_fit_median_error_db)
        )
        if not qualified:
            continue
        score = (
            mode_fraction,
            supported_bins,
            -scale,
            -float(median_error),
        )
        if best is None or score > best["score"]:
            best = {
                "score": score,
                "location": location,
                "scale": scale,
                "valid_range": valid_range,
                "supported_bins": supported_bins,
                "supported_span": supported_span,
                "consistent_fraction": consistent_fraction,
                "median_error": median_error,
            }

    if best is None:
        return _failed_model(
            values.shape,
            "fixed_slope_mode_not_qualified",
            seed_count=seed_count,
            fit_strategy="fixed_slope_mode",
            range_slope_db_per_decade=slope,
        )

    location = float(best["location"])
    scale = float(best["scale"])
    lower_residual = (
        -float(active.fixed_slope_compatibility_sigma) * scale
    )
    upper_residual = (
        float(active.fixed_slope_compatibility_sigma) * scale
    )
    valid_range = np.asarray(best["valid_range"], dtype=bool)
    profile = np.full(values.shape[1], np.nan, dtype="float32")
    profile[valid_range] = (
        base_profile[valid_range] + location
    ).astype("float32")
    centered_residual = residual - location
    compatible = (
        np.isfinite(values)
        & valid_range[np.newaxis, :]
        & (centered_residual >= lower_residual)
        & (centered_residual <= upper_residual)
    )
    return ReceiverNoiseModel(
        status="qualified_fixed_slope",
        qualified=True,
        fit_strategy="fixed_slope_mode",
        floor_profile_dbzh=profile,
        compatible_mask=compatible,
        valid_range_mask=valid_range,
        residual_location_db=0.0,
        residual_scale_db=scale,
        lower_residual_db=lower_residual,
        upper_residual_db=upper_residual,
        range_slope_db_per_decade=slope,
        range_intercept_db=location,
        seed_count=seed_count,
        supported_bin_count=int(best["supported_bins"]),
        supported_span_km=float(best["supported_span"]),
        consistent_bin_fraction=float(best["consistent_fraction"]),
        fit_median_error_db=float(best["median_error"]),
    )


def _histogram_mode(values: Any, *, bin_width: float) -> float | None:
    np = require_numpy()
    finite = np.asarray(values, dtype="float64")
    finite = finite[np.isfinite(finite)]
    if finite.size == 0 or bin_width <= 0:
        return None
    lower = float(np.floor(finite.min() / bin_width) * bin_width)
    upper = float(np.ceil(finite.max() / bin_width) * bin_width)
    if upper <= lower:
        return float(finite[0])
    edges = np.arange(lower, upper + 2.0 * bin_width, bin_width)
    counts, edges = np.histogram(finite, bins=edges)
    index = int(np.argmax(counts))
    return float((edges[index] + edges[index + 1]) / 2.0)


def _histogram_peak_locations(
    values: Any,
    *,
    bin_width: float,
    maximum_count: int,
    minimum_separation_db: float,
) -> tuple[float, ...]:
    np = require_numpy()
    finite = np.asarray(values, dtype="float64")
    finite = finite[np.isfinite(finite)]
    if finite.size == 0 or bin_width <= 0 or maximum_count <= 0:
        return ()
    lower = float(np.floor(finite.min() / bin_width) * bin_width)
    upper = float(np.ceil(finite.max() / bin_width) * bin_width)
    if upper <= lower:
        return (float(finite[0]),)
    edges = np.arange(lower, upper + 2.0 * bin_width, bin_width)
    counts, edges = np.histogram(finite, bins=edges)
    centres = (edges[:-1] + edges[1:]) / 2.0
    order = np.argsort(-counts, kind="stable")
    selected: list[float] = []
    separation = max(float(minimum_separation_db), float(bin_width))
    for index in order:
        if counts[index] <= 0:
            break
        candidate = float(centres[index])
        if any(abs(candidate - prior) < separation for prior in selected):
            continue
        selected.append(candidate)
        if len(selected) >= int(maximum_count):
            break
    return tuple(selected)


def _robust_range_fit(
    x: Any,
    y: Any,
    *,
    config: ReceiverNoiseModelConfig,
) -> tuple[float | None, float | None, Any]:
    np = require_numpy()
    predictors = np.asarray(x, dtype="float64")
    response = np.asarray(y, dtype="float64")
    inliers = np.isfinite(predictors) & np.isfinite(response)
    if int(inliers.sum()) < 2:
        return None, None, inliers
    slope = intercept = None
    for _ in range(max(1, int(config.robust_fit_iterations))):
        slope, intercept = np.polyfit(
            predictors[inliers],
            response[inliers],
            1,
        )
        errors = np.abs(response - (slope * predictors + intercept))
        median_error = float(np.median(errors[inliers]))
        mad = float(
            np.median(np.abs(errors[inliers] - median_error))
        )
        threshold = max(
            float(config.robust_fit_minimum_error_db),
            float(config.robust_fit_sigma) * 1.4826 * mad,
        )
        updated = (
            np.isfinite(errors)
            & (errors <= threshold)
        )
        if int(updated.sum()) < 2 or np.array_equal(updated, inliers):
            break
        inliers = updated
    return (
        float(slope) if slope is not None else None,
        float(intercept) if intercept is not None else None,
        inliers,
    )


def _supported_span_km(ranges_km: Any, valid_range: Any) -> float:
    np = require_numpy()
    selected = np.asarray(ranges_km, dtype="float64")[
        np.asarray(valid_range, dtype=bool)
    ]
    if selected.size < 2:
        return 0.0
    return float(selected.max() - selected.min())


def _encoded_floor_mask(
    values: Any,
    config: ReceiverNoiseModelConfig,
) -> Any:
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    finite = array[np.isfinite(array)]
    output = np.zeros(array.shape, dtype=bool)
    if finite.size == 0:
        return output
    minimum = float(finite.min())
    tolerance = float(config.encoded_floor_tolerance_db)
    at_floor = np.isfinite(array) & (array <= minimum + tolerance)
    if float(at_floor.sum() / finite.size) >= float(
        config.encoded_floor_minimum_fraction
    ):
        return at_floor
    return output


def _failed_model(
    shape: tuple[int, int],
    status: str,
    *,
    seed_count: int,
    fit_strategy: str = "free_slope",
    range_slope_db_per_decade: float | None = None,
    range_intercept_db: float | None = None,
) -> ReceiverNoiseModel:
    np = require_numpy()
    return ReceiverNoiseModel(
        status=status,
        qualified=False,
        fit_strategy=fit_strategy,
        floor_profile_dbzh=np.full(shape[1], np.nan, dtype="float32"),
        compatible_mask=np.zeros(shape, dtype=bool),
        valid_range_mask=np.zeros(shape[1], dtype=bool),
        residual_location_db=None,
        residual_scale_db=None,
        lower_residual_db=None,
        upper_residual_db=None,
        range_slope_db_per_decade=range_slope_db_per_decade,
        range_intercept_db=range_intercept_db,
        seed_count=seed_count,
        supported_bin_count=0,
        supported_span_km=0.0,
        consistent_bin_fraction=0.0,
        fit_median_error_db=None,
    )
