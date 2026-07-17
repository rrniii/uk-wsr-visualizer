"""Conservative multi-evidence nuisance classification for UK WSR sweeps."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from enum import IntFlag
from typing import Any

from .dependencies import require_numpy
from .qc import (
    CI_CANDIDATES,
    PHIDP_CANDIDATES,
    RHOHV_CANDIDATES,
    SQI_CANDIDATES,
    VRAD_CANDIDATES,
    WIDTH_CANDIDATES,
    ZDR_CANDIDATES,
    normalized_quantity,
)

EVIDENCE_VERSION = "qc-v3-candidate-1"


class EvidenceFlag(IntFlag):
    HIGH_CI = 1
    LOW_CI = 2
    LOW_SQI = 4
    LOW_RHOHV = 8
    ZDR_OUTLIER = 16
    PHIDP_TEXTURE = 32
    VRAD_TEXTURE = 64
    NEAR_NOISE_PROFILE = 128
    SPATIALLY_INCOHERENT = 256
    SPATIALLY_COHERENT = 512
    NEAR_ZERO_VELOCITY = 1024
    RADIAL_SPOKE = 2048
    LEARNED_PERSISTENCE = 4096
    LEARNED_STATIC_VELOCITY = 8192
    TEMPORAL_PERSISTENCE = 16384
    UPPER_ELEVATION_SUPPORT = 32768
    WIDE_SPECTRUM = 65536
    LEARNED_DBZH_COMPATIBLE = 131072


class NuisanceFlag(IntFlag):
    RECEIVER_NOISE = 1
    STATIC_CLUTTER = 2
    ANOMALOUS_PROPAGATION = 4
    RADIAL_INTERFERENCE = 8
    ISOLATED_SPECKLE = 16


@dataclass(frozen=True)
class EvidenceConfig:
    """Thresholds for high-confidence removal, not broad echo classification."""

    ci_noise_min: float = 6.0
    ci_clutter_max: float = 2.0
    sqi_noise_max: float = 0.08
    sqi_clutter_max: float = 0.65
    rhohv_noise_max: float = 0.25
    rhohv_clutter_max: float = 0.85
    zdr_min_db: float = -3.0
    zdr_max_db: float = 8.0
    phidp_texture_min_deg: float = 30.0
    phidp_noise_texture_min_deg: float = 60.0
    velocity_texture_min_ms: float = 9.0
    velocity_noise_texture_min_ms: float = 18.0
    near_zero_velocity_max_ms: float = 0.75
    spectrum_width_max_ms: float = 8.0
    similar_dbzh_tolerance_db: float = 4.0
    coherent_neighbour_min: int = 2
    isolated_neighbour_max: int = 1
    noise_profile_percentile: float = 95.0
    noise_profile_margin_db: float = 1.0
    noise_profile_window_bins: int = 11
    noise_min_bad_moments_near_profile: int = 1
    noise_min_bad_moments_without_profile: int = 4
    interference_min_gate_fraction: float = 0.06
    interference_ray_fraction_min: float = 0.22
    interference_ray_excess_min: float = 0.10
    background_persistence_min: float = 0.95
    background_static_velocity_frequency_min: float = 0.80
    background_conditioned_min_samples: int = 12
    background_dbzh_excess_max_db: float = 3.0
    temporal_dbzh_tolerance_db: float = 3.0
    upper_elevation_dbzh_tolerance_db: float = 8.0


@dataclass(frozen=True)
class EvidenceContext:
    """Optional independent support; absent arrays always fail open."""

    previous_dbzh: Any | None = None
    next_dbzh: Any | None = None
    upper_elevation_dbzh: Any | None = None
    upper_elevation_required: bool = False
    background_persistent_frequency: Any | None = None
    background_near_zero_vrad_frequency: Any | None = None
    background_conditioned_sample_count: Any | None = None
    background_dbzh_p90: Any | None = None


@dataclass
class EvidenceResult:
    """Per-gate evidence, nuisance decisions, and protected-signal state."""

    remove_mask: Any
    nuisance_mask: Any
    evidence_mask: Any
    confidence: Any
    protected_mask: Any
    noise_profile: Any
    counts: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = EVIDENCE_VERSION

    def nuisance(self, flag: NuisanceFlag) -> Any:
        return (self.nuisance_mask & int(flag)) != 0


def classify_nuisance_echoes(
    dbzh: Any,
    companion_fields: dict[str, Any] | None = None,
    *,
    pulse: str,
    config: EvidenceConfig | None = None,
    context: EvidenceContext | None = None,
) -> EvidenceResult:
    """Remove only gates with converging evidence of a nuisance mechanism."""

    np = require_numpy()
    config = config or EvidenceConfig()
    context = context or EvidenceContext()
    values = np.asarray(dbzh, dtype="float32")
    if values.ndim != 2:
        raise ValueError("DBZH must be a two-dimensional polar sweep")
    shape = values.shape
    finite = np.isfinite(values)
    fields = _normalise_fields(companion_fields or {}, shape)
    ci = _field(fields, CI_CANDIDATES)
    sqi = _field(fields, SQI_CANDIDATES)
    rhohv = _field(fields, RHOHV_CANDIDATES)
    zdr = _field(fields, ZDR_CANDIDATES)
    phidp = _field(fields, PHIDP_CANDIDATES)
    velocity = _field(fields, VRAD_CANDIDATES)
    width = _field(fields, WIDTH_CANDIDATES)

    evidence = np.zeros(shape, dtype="uint32")
    high_ci = _threshold(ci, finite, minimum=config.ci_noise_min)
    low_ci = _threshold(ci, finite, maximum=config.ci_clutter_max)
    low_sqi = _threshold(sqi, finite, maximum=config.sqi_noise_max)
    clutter_sqi = _threshold(sqi, finite, maximum=config.sqi_clutter_max)
    low_rho_noise = _threshold(rhohv, finite, maximum=config.rhohv_noise_max)
    low_rho_clutter = _threshold(
        rhohv,
        finite,
        maximum=config.rhohv_clutter_max,
    )
    zdr_outlier = _outside(zdr, finite, config.zdr_min_db, config.zdr_max_db)
    phidp_texture = _local_texture(phidp, angular=True)
    velocity_texture = _local_texture(velocity)
    phidp_rough = _at_least(
        phidp_texture,
        finite,
        config.phidp_texture_min_deg,
    )
    phidp_chaotic = _at_least(
        phidp_texture,
        finite,
        config.phidp_noise_texture_min_deg,
    )
    velocity_rough = _at_least(
        velocity_texture,
        finite,
        config.velocity_texture_min_ms,
    )
    velocity_chaotic = _at_least(
        velocity_texture,
        finite,
        config.velocity_noise_texture_min_ms,
    )
    near_zero_velocity = _absolute_at_most(
        velocity,
        finite,
        config.near_zero_velocity_max_ms,
    )
    wide_spectrum = _threshold(
        width,
        finite,
        minimum=config.spectrum_width_max_ms,
    )
    similar_neighbours, _ = _neighbour_support(
        values,
        tolerance=config.similar_dbzh_tolerance_db,
    )
    spatially_coherent = finite & (
        similar_neighbours >= max(1, config.coherent_neighbour_min)
    )
    spatially_incoherent = finite & (
        similar_neighbours <= max(0, config.isolated_neighbour_max)
    )

    profile = _evidence_noise_profile(
        values,
        high_ci & low_sqi,
        percentile=config.noise_profile_percentile,
        window_bins=config.noise_profile_window_bins,
    )
    threshold = np.broadcast_to(
        profile[np.newaxis, :] + config.noise_profile_margin_db,
        shape,
    )
    near_profile = finite & np.isfinite(threshold) & (values <= threshold)

    temporal_persistence = _temporal_persistence(
        values,
        context,
        tolerance=config.temporal_dbzh_tolerance_db,
    )
    upper_support = _upper_elevation_support(
        values,
        context.upper_elevation_dbzh,
        tolerance=config.upper_elevation_dbzh_tolerance_db,
    )
    upper_context_qualified = (
        not context.upper_elevation_required
        or context.upper_elevation_dbzh is not None
    )
    learned_persistence = _context_threshold(
        context.background_persistent_frequency,
        shape,
        config.background_persistence_min,
    )
    learned_static = _context_threshold(
        context.background_near_zero_vrad_frequency,
        shape,
        config.background_static_velocity_frequency_min,
    )
    learned_sample_support = _context_threshold(
        context.background_conditioned_sample_count,
        shape,
        float(config.background_conditioned_min_samples),
    )
    learned_dbzh_compatible = _context_ceiling(
        values,
        context.background_dbzh_p90,
        margin=config.background_dbzh_excess_max_db,
    )
    learned_persistence &= learned_sample_support
    learned_static &= learned_sample_support

    _set_evidence(evidence, high_ci, EvidenceFlag.HIGH_CI)
    _set_evidence(evidence, low_ci, EvidenceFlag.LOW_CI)
    _set_evidence(evidence, low_sqi, EvidenceFlag.LOW_SQI)
    _set_evidence(
        evidence,
        low_rho_noise | low_rho_clutter,
        EvidenceFlag.LOW_RHOHV,
    )
    _set_evidence(evidence, zdr_outlier, EvidenceFlag.ZDR_OUTLIER)
    _set_evidence(evidence, phidp_rough, EvidenceFlag.PHIDP_TEXTURE)
    _set_evidence(evidence, velocity_rough, EvidenceFlag.VRAD_TEXTURE)
    _set_evidence(evidence, near_profile, EvidenceFlag.NEAR_NOISE_PROFILE)
    _set_evidence(
        evidence,
        spatially_incoherent,
        EvidenceFlag.SPATIALLY_INCOHERENT,
    )
    _set_evidence(evidence, spatially_coherent, EvidenceFlag.SPATIALLY_COHERENT)
    _set_evidence(
        evidence,
        near_zero_velocity,
        EvidenceFlag.NEAR_ZERO_VELOCITY,
    )
    _set_evidence(
        evidence,
        learned_persistence,
        EvidenceFlag.LEARNED_PERSISTENCE,
    )
    _set_evidence(
        evidence,
        learned_static,
        EvidenceFlag.LEARNED_STATIC_VELOCITY,
    )
    _set_evidence(
        evidence,
        learned_dbzh_compatible,
        EvidenceFlag.LEARNED_DBZH_COMPATIBLE,
    )
    _set_evidence(
        evidence,
        temporal_persistence,
        EvidenceFlag.TEMPORAL_PERSISTENCE,
    )
    _set_evidence(
        evidence,
        upper_support,
        EvidenceFlag.UPPER_ELEVATION_SUPPORT,
    )
    _set_evidence(evidence, wide_spectrum, EvidenceFlag.WIDE_SPECTRUM)

    interference_sqi = _threshold(sqi, finite, maximum=0.20)
    interference_rhohv = _threshold(rhohv, finite, maximum=0.50)
    ray_bad = (
        finite
        & interference_sqi
        & interference_rhohv
        & (phidp_rough | velocity_rough)
    )
    spoke_rays = _radial_spoke_rays(
        ray_bad,
        minimum_gate_fraction=config.interference_min_gate_fraction,
        minimum_ray_fraction=config.interference_ray_fraction_min,
        minimum_excess=config.interference_ray_excess_min,
    )
    radial_spoke = np.broadcast_to(spoke_rays[:, np.newaxis], shape) & ray_bad
    _set_evidence(evidence, radial_spoke, EvidenceFlag.RADIAL_SPOKE)

    bad_moment_score = (
        low_rho_noise.astype("int16")
        + zdr_outlier.astype("int16")
        + phidp_chaotic.astype("int16")
        + velocity_chaotic.astype("int16")
        + spatially_incoherent.astype("int16")
        + wide_spectrum.astype("int16")
    )
    receiver_noise = (
        finite
        & high_ci
        & low_sqi
        & (
            (
                near_profile
                & (
                    bad_moment_score
                    >= config.noise_min_bad_moments_near_profile
                )
            )
            | (
                bad_moment_score
                >= config.noise_min_bad_moments_without_profile
            )
        )
    )
    receiver_noise &= ~radial_spoke

    current_stationary = (
        finite
        & low_ci
        & near_zero_velocity
        & spatially_coherent
        & (values >= 5.0)
    )
    learned_static_clutter = (
        current_stationary
        & learned_persistence
        & learned_static
        & learned_dbzh_compatible
        & ~upper_support
        & upper_context_qualified
    )
    transient_nonmeteorological = (
        current_stationary
        & low_rho_clutter
        & clutter_sqi
        & (phidp_rough | zdr_outlier | wide_spectrum)
        & ~upper_support
        & upper_context_qualified
    )
    temporally_stationary_clutter = (
        transient_nonmeteorological
        & temporal_persistence
        & (learned_persistence | (low_rho_noise & phidp_rough))
    )
    static_clutter = learned_static_clutter | temporally_stationary_clutter
    anomalous_propagation = transient_nonmeteorological & ~static_clutter

    isolated_speckle = (
        finite
        & spatially_incoherent
        & _threshold(sqi, finite, maximum=0.30)
        & (high_ci | low_rho_clutter | zdr_outlier)
    )
    isolated_speckle &= ~(
        radial_spoke
        | receiver_noise
        | static_clutter
        | anomalous_propagation
    )

    protected = finite & (
        upper_support
        | (
            spatially_coherent
            & ~low_sqi
            & ~low_ci
        )
    )
    nuisance = np.zeros(shape, dtype="uint16")
    nuisance[radial_spoke] |= int(NuisanceFlag.RADIAL_INTERFERENCE)
    nuisance[receiver_noise] |= int(NuisanceFlag.RECEIVER_NOISE)
    nuisance[static_clutter] |= int(NuisanceFlag.STATIC_CLUTTER)
    nuisance[anomalous_propagation] |= int(
        NuisanceFlag.ANOMALOUS_PROPAGATION
    )
    nuisance[isolated_speckle] |= int(NuisanceFlag.ISOLATED_SPECKLE)
    remove = finite & (nuisance != 0) & ~protected
    nuisance[~remove] = 0

    confidence = np.zeros(shape, dtype="float32")
    confidence[radial_spoke] = 0.99
    confidence[receiver_noise] = np.maximum(
        confidence[receiver_noise],
        np.minimum(
            0.90 + 0.02 * bad_moment_score[receiver_noise],
            0.99,
        ),
    )
    confidence[static_clutter] = np.maximum(
        confidence[static_clutter],
        0.98,
    )
    confidence[anomalous_propagation] = np.maximum(
        confidence[anomalous_propagation],
        0.94,
    )
    confidence[isolated_speckle] = np.maximum(
        confidence[isolated_speckle],
        0.92,
    )
    confidence[~remove] = 0.0

    counts = {
        "finite": int(finite.sum()),
        "removed": int(remove.sum()),
        "protected": int(protected.sum()),
        "receiver_noise": int(
            ((nuisance & int(NuisanceFlag.RECEIVER_NOISE)) != 0).sum()
        ),
        "static_clutter": int(
            ((nuisance & int(NuisanceFlag.STATIC_CLUTTER)) != 0).sum()
        ),
        "anomalous_propagation": int(
            (
                (nuisance & int(NuisanceFlag.ANOMALOUS_PROPAGATION))
                != 0
            ).sum()
        ),
        "radial_interference": int(
            (
                (nuisance & int(NuisanceFlag.RADIAL_INTERFERENCE))
                != 0
            ).sum()
        ),
        "isolated_speckle": int(
            ((nuisance & int(NuisanceFlag.ISOLATED_SPECKLE)) != 0).sum()
        ),
    }
    return EvidenceResult(
        remove_mask=remove,
        nuisance_mask=nuisance,
        evidence_mask=evidence,
        confidence=confidence,
        protected_mask=protected,
        noise_profile=profile,
        counts=counts,
        metadata={
            "pulse": str(pulse).lower(),
            "shape": [int(shape[0]), int(shape[1])],
            "available_companions": sorted(fields),
            "context": {
                "temporal": bool(
                    context.previous_dbzh is not None
                    or context.next_dbzh is not None
                ),
                "upper_elevation": context.upper_elevation_dbzh is not None,
                "upper_elevation_required": bool(
                    context.upper_elevation_required
                ),
                "learned_background": bool(
                    context.background_persistent_frequency is not None
                    and context.background_near_zero_vrad_frequency is not None
                    and context.background_conditioned_sample_count is not None
                    and context.background_dbzh_p90 is not None
                ),
            },
            "policy": (
                "high-confidence nuisance mechanisms only; contradictory or "
                "insufficient evidence is retained"
            ),
        },
    )


def _normalise_fields(
    fields: dict[str, Any],
    shape: tuple[int, int],
) -> dict[str, Any]:
    np = require_numpy()
    output = {}
    for raw_quantity, raw_values in fields.items():
        quantity = normalized_quantity(raw_quantity)
        values = np.asarray(raw_values, dtype="float32")
        if not quantity or values.shape != shape:
            continue
        output.setdefault(quantity, values)
    return output


def _field(fields: dict[str, Any], candidates: tuple[str, ...]) -> Any | None:
    for candidate in candidates:
        if candidate in fields:
            return fields[candidate]
    return None


def _threshold(
    values: Any | None,
    base: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> Any:
    np = require_numpy()
    result = np.zeros(np.asarray(base).shape, dtype=bool)
    if values is None:
        return result
    array = np.asarray(values, dtype="float32")
    result = np.asarray(base, dtype=bool) & np.isfinite(array)
    if minimum is not None:
        result &= array >= float(minimum)
    if maximum is not None:
        result &= array <= float(maximum)
    return result


def _outside(
    values: Any | None,
    base: Any,
    minimum: float,
    maximum: float,
) -> Any:
    np = require_numpy()
    if values is None:
        return np.zeros(np.asarray(base).shape, dtype=bool)
    array = np.asarray(values, dtype="float32")
    return (
        np.asarray(base, dtype=bool)
        & np.isfinite(array)
        & ((array <= float(minimum)) | (array >= float(maximum)))
    )


def _at_least(values: Any | None, base: Any, threshold: float) -> Any:
    return _threshold(values, base, minimum=threshold)


def _absolute_at_most(values: Any | None, base: Any, threshold: float) -> Any:
    np = require_numpy()
    if values is None:
        return np.zeros(np.asarray(base).shape, dtype=bool)
    array = np.asarray(values, dtype="float32")
    return (
        np.asarray(base, dtype=bool)
        & np.isfinite(array)
        & (np.abs(array) <= float(threshold))
    )


def _local_texture(values: Any | None, *, angular: bool = False) -> Any | None:
    np = require_numpy()
    if values is None:
        return None
    array = np.asarray(values, dtype="float32")
    if array.ndim != 2:
        return None
    differences = []
    for neighbour in _four_neighbours(array):
        difference = np.abs(array - neighbour)
        if angular:
            difference = np.minimum(
                np.mod(difference, 360.0),
                360.0 - np.mod(difference, 360.0),
            )
        difference[~np.isfinite(array) | ~np.isfinite(neighbour)] = np.nan
        differences.append(difference)
    stack = np.stack(differences)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        texture = np.nanpercentile(stack, 75.0, axis=0)
    texture[np.isfinite(stack).sum(axis=0) < 2] = np.nan
    return texture.astype("float32")


def _neighbour_support(values: Any, *, tolerance: float) -> tuple[Any, Any]:
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    similar = np.zeros(array.shape, dtype="int16")
    finite_count = np.zeros(array.shape, dtype="int16")
    for neighbour in _eight_neighbours(array):
        valid = np.isfinite(array) & np.isfinite(neighbour)
        finite_count += valid.astype("int16")
        similar += (
            valid & (np.abs(array - neighbour) <= float(tolerance))
        ).astype("int16")
    return similar, finite_count


def _four_neighbours(values: Any) -> list[Any]:
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    left = np.full_like(array, np.nan)
    right = np.full_like(array, np.nan)
    left[:, 1:] = array[:, :-1]
    right[:, :-1] = array[:, 1:]
    return [
        np.roll(array, 1, axis=0),
        np.roll(array, -1, axis=0),
        left,
        right,
    ]


def _eight_neighbours(values: Any) -> list[Any]:
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    neighbours = []
    for ray_shift in (-1, 0, 1):
        rolled = np.roll(array, ray_shift, axis=0)
        for gate_shift in (-1, 0, 1):
            if ray_shift == 0 and gate_shift == 0:
                continue
            shifted = np.full_like(array, np.nan)
            if gate_shift == -1:
                shifted[:, :-1] = rolled[:, 1:]
            elif gate_shift == 1:
                shifted[:, 1:] = rolled[:, :-1]
            else:
                shifted[:] = rolled
            neighbours.append(shifted)
    return neighbours


def _evidence_noise_profile(
    values: Any,
    noise_seeds: Any,
    *,
    percentile: float,
    window_bins: int,
) -> Any:
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    seeds = np.asarray(noise_seeds, dtype=bool)
    profile = np.full(array.shape[1], np.nan, dtype="float32")
    fallback = np.full(array.shape[1], np.nan, dtype="float32")
    for gate in range(array.shape[1]):
        column = array[:, gate]
        seed_values = column[seeds[:, gate] & np.isfinite(column)]
        finite_values = column[np.isfinite(column)]
        if seed_values.size >= 5:
            profile[gate] = float(
                np.nanpercentile(seed_values, float(percentile))
            )
        if finite_values.size >= 5:
            fallback[gate] = float(np.nanpercentile(finite_values, 10.0))
    profile = _fill_profile(profile)
    fallback = _fill_profile(fallback)
    profile = np.where(np.isfinite(profile), profile, fallback)
    return _rolling_median(profile, window_bins)


def _fill_profile(values: Any) -> Any:
    np = require_numpy()
    profile = np.asarray(values, dtype="float32").copy()
    valid = np.isfinite(profile)
    if not valid.any():
        return profile
    indices = np.arange(profile.size)
    return np.interp(indices, indices[valid], profile[valid]).astype("float32")


def _rolling_median(values: Any, window_bins: int) -> Any:
    np = require_numpy()
    profile = np.asarray(values, dtype="float32")
    window = max(1, int(window_bins))
    if window % 2 == 0:
        window += 1
    if window == 1 or profile.size == 0:
        return profile.copy()
    radius = window // 2
    result = np.full(profile.shape, np.nan, dtype="float32")
    for index in range(profile.size):
        start = max(0, index - radius)
        stop = min(profile.size, index + radius + 1)
        finite = profile[start:stop]
        finite = finite[np.isfinite(finite)]
        if finite.size:
            result[index] = float(np.median(finite))
    return _fill_profile(result)


def _radial_spoke_rays(
    candidates: Any,
    *,
    minimum_gate_fraction: float,
    minimum_ray_fraction: float,
    minimum_excess: float,
) -> Any:
    np = require_numpy()
    values = np.asarray(candidates, dtype=bool)
    start = min(
        values.shape[1] - 1,
        max(0, int(round(values.shape[1] * minimum_gate_fraction))),
    )
    fractions = values[:, start:].mean(axis=1)
    baselines = np.zeros(fractions.shape, dtype="float32")
    for offset in range(-3, 4):
        if offset == 0:
            continue
        baselines += np.roll(fractions, offset)
    baselines /= 6.0
    return (
        (fractions >= float(minimum_ray_fraction))
        & (fractions >= baselines + float(minimum_excess))
    )


def _temporal_persistence(
    values: Any,
    context: EvidenceContext,
    *,
    tolerance: float,
) -> Any:
    np = require_numpy()
    current = np.asarray(values, dtype="float32")
    supports = []
    for candidate in (context.previous_dbzh, context.next_dbzh):
        if candidate is None:
            continue
        array = np.asarray(candidate, dtype="float32")
        if array.shape != current.shape:
            raise ValueError("temporal DBZH context shape mismatch")
        supports.append(
            np.isfinite(current)
            & np.isfinite(array)
            & (np.abs(current - array) <= float(tolerance))
        )
    if not supports:
        return np.zeros(current.shape, dtype=bool)
    result = supports[0]
    for support in supports[1:]:
        result &= support
    return result


def _upper_elevation_support(
    values: Any,
    upper: Any | None,
    *,
    tolerance: float,
) -> Any:
    np = require_numpy()
    current = np.asarray(values, dtype="float32")
    if upper is None:
        return np.zeros(current.shape, dtype=bool)
    array = np.asarray(upper, dtype="float32")
    if array.shape != current.shape:
        raise ValueError("upper-elevation DBZH context shape mismatch")
    return (
        np.isfinite(current)
        & np.isfinite(array)
        & (np.abs(current - array) <= float(tolerance))
    )


def _context_threshold(
    values: Any | None,
    shape: tuple[int, int],
    threshold: float,
) -> Any:
    np = require_numpy()
    if values is None:
        return np.zeros(shape, dtype=bool)
    array = np.asarray(values, dtype="float32")
    if array.shape != shape:
        raise ValueError("learned-background context shape mismatch")
    return np.isfinite(array) & (array >= float(threshold))


def _context_ceiling(
    values: Any,
    ceiling: Any | None,
    *,
    margin: float,
) -> Any:
    np = require_numpy()
    current = np.asarray(values, dtype="float32")
    if ceiling is None:
        return np.zeros(current.shape, dtype=bool)
    learned = np.asarray(ceiling, dtype="float32")
    if learned.shape != current.shape:
        raise ValueError("learned DBZH context shape mismatch")
    return (
        np.isfinite(current)
        & np.isfinite(learned)
        & (current <= learned + float(margin))
    )


def _set_evidence(target: Any, mask: Any, flag: EvidenceFlag) -> None:
    np = require_numpy()
    target[np.asarray(mask, dtype=bool)] |= int(flag)
