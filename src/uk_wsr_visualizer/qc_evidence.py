"""Conservative multi-evidence nuisance classification for UK WSR sweeps."""

from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass, field
from enum import IntFlag
from typing import Any

from .background_model_v3 import BACKGROUND_MODEL_V3_STATISTICS_VERSION
from .dependencies import require_numpy
from .qc import (
    AMBIENT_NOISE_H_CANDIDATES,
    AMBIENT_NOISE_V_CANDIDATES,
    CI_CANDIDATES,
    PHIDP_CANDIDATES,
    RHOHV_CANDIDATES,
    SQI_CANDIDATES,
    VRAD_CANDIDATES,
    WIDTH_CANDIDATES,
    ZDR_CANDIDATES,
    normalized_quantity,
)
from .receiver_noise_model import (
    ReceiverNoiseModelConfig,
    fit_fixed_slope_receiver_noise,
    fit_range_corrected_receiver_noise,
)

EVIDENCE_VERSION = "qc-v3-candidate-6"


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
    AMBIENT_NOISE_RAY_OUTLIER = 262144
    TEMPORAL_STATIC_VELOCITY = 524288
    PHYSICAL_NOISE_RANGE_LAW = 1048576
    POLARIMETRIC_NOISE_FAMILY = 2097152
    DOPPLER_NOISE_FAMILY = 4194304
    SPATIAL_NOISE_FAMILY = 8388608
    COHERENT_DOPPLER_FLOW = 16777216
    TEMPORAL_FLOW_CONSISTENCY = 33554432
    LEARNED_DATE_COVERAGE = 67108864
    LEARNED_SEASON_COVERAGE = 134217728
    LEARNED_TIME_COVERAGE = 268435456
    LEARNED_STATIC_DATE_FREQUENCY = 536870912
    RECEIVER_CROSS_SCAN_CONTEXT = 1073741824
    FIXED_SLOPE_NOISE_RIDGE = 2147483648


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
    sqi_noise_max: float = 0.05
    sqi_clutter_max: float = 0.65
    rhohv_noise_max: float = 0.20
    rhohv_clutter_max: float = 0.85
    rhohv_strong_clutter_max: float = 0.70
    zdr_min_db: float = -3.0
    zdr_max_db: float = 8.0
    phidp_texture_min_deg: float = 30.0
    phidp_noise_texture_min_deg: float = 60.0
    velocity_texture_min_ms: float = 9.0
    near_zero_velocity_max_ms: float = 0.50
    spectrum_width_max_ms: float = 8.0
    similar_dbzh_tolerance_db: float = 4.0
    coherent_neighbour_min: int = 2
    isolated_neighbour_max: int = 1
    coherent_velocity_tolerance_ms: float = 2.0
    coherent_velocity_neighbour_min: int = 4
    coherent_velocity_min_speed_ms: float = 1.0
    temporal_velocity_consistency_ms: float = 2.0
    noise_min_independent_families: int = 2
    receiver_noise_model: ReceiverNoiseModelConfig = field(
        default_factory=ReceiverNoiseModelConfig
    )
    lp_receiver_fixed_slope_mode_enabled: bool = True
    ambient_noise_ray_excess_db: float = 3.0
    isolated_speckle_enabled: bool = False
    interference_min_gate_fraction: float = 0.06
    interference_ray_fraction_min: float = 0.22
    interference_ray_excess_min: float = 0.10
    interference_strong_coherent_protection_dbzh: float = 20.0
    anomalous_propagation_max_elevation_deg: float = 2.0
    background_distinct_date_min: int = 8
    background_static_date_frequency_min: float = 0.875
    background_required_season_count: int = 4
    background_required_time_bucket_count: int = 2
    background_static_dbzh_p90_excess_max_db: float = 3.0
    background_static_dbzh_median_excess_max_db: float = 3.0
    background_static_dbzh_interquantile_range_max_db: float = 6.0
    temporal_dbzh_tolerance_db: float = 2.0
    learned_clutter_temporal_dbzh_tolerance_db: float = 0.5
    temporal_velocity_max_ms: float = 0.50
    temporal_advection_max_ray_shift: int = 2
    temporal_advection_max_gate_shift: int = 2
    temporal_advection_minimum_improvement_db: float = 0.50
    learned_clutter_min_current_evidence_families: int = 2
    coherent_signal_sqi_min: float = 0.75
    coherent_signal_rhohv_min: float = 0.90
    upper_elevation_dbzh_tolerance_db: float = 8.0


@dataclass(frozen=True)
class EvidenceContext:
    """Optional independent support; absent arrays always fail open."""

    previous_dbzh: Any | None = None
    next_dbzh: Any | None = None
    previous_vrad: Any | None = None
    next_vrad: Any | None = None
    temporal_context_required: bool = False
    upper_elevation_dbzh: Any | None = None
    upper_elevation_required: bool = False
    elevation_deg: float | None = None
    receiver_noise_cross_scan_required: bool = False
    background_statistics_version: str | None = None
    background_distinct_date_count: Any | None = None
    background_static_echo_date_frequency: Any | None = None
    background_static_echo_season_count: Any | None = None
    background_static_echo_time_bucket_count: Any | None = None
    background_static_dbzh_p10: Any | None = None
    background_static_dbzh_median: Any | None = None
    background_static_dbzh_p90: Any | None = None
    learned_background_allowed: bool = True


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
    rstart_km: float | None = None,
    rscale_m: float | None = None,
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
    strong_low_rho_clutter = _threshold(
        rhohv,
        finite,
        maximum=config.rhohv_strong_clutter_max,
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
    high_sqi = _threshold(
        sqi,
        finite,
        minimum=config.coherent_signal_sqi_min,
    )
    high_rhohv = _threshold(
        rhohv,
        finite,
        minimum=config.coherent_signal_rhohv_min,
    )
    quality_coherent_signal = (
        spatially_coherent & (high_sqi | high_rhohv)
    )

    receiver_fit_independent_support = (
        low_rho_noise
        | zdr_outlier
        | phidp_chaotic
        | velocity_rough
        | wide_spectrum
        | spatially_incoherent
    )
    receiver_fit_seeds = high_ci & low_sqi
    receiver_fit_seed_policy = "high_ci_low_sqi"
    if str(pulse).strip().lower() == "lp":
        receiver_fit_seeds &= receiver_fit_independent_support
        receiver_fit_seed_policy = (
            "high_ci_low_sqi_plus_independent_noise_symptom"
        )
    profile, physical_noise_range_law, receiver_model_metadata = (
        _receiver_noise_support(
            values,
            receiver_fit_seeds,
            pulse=pulse,
            rstart_km=rstart_km,
            rscale_m=rscale_m,
            config=config.receiver_noise_model,
            lp_fixed_slope_mode_enabled=(
                config.lp_receiver_fixed_slope_mode_enabled
            ),
        )
    )
    receiver_model_metadata["seed_policy"] = receiver_fit_seed_policy
    receiver_model_metadata["fit_seed_gate_count"] = int(
        receiver_fit_seeds.sum()
    )
    fixed_slope_noise_ridge = bool(
        receiver_model_metadata.get("qualified")
        and receiver_model_metadata.get("fit_strategy")
        == "fixed_slope_mode"
    )
    coherent_doppler_flow = _coherent_doppler_flow(
        velocity,
        finite,
        tolerance=config.coherent_velocity_tolerance_ms,
        minimum_neighbours=config.coherent_velocity_neighbour_min,
        minimum_speed=config.coherent_velocity_min_speed_ms,
    )
    ambient_noise_outlier = _ambient_noise_outlier(
        fields,
        shape,
        excess_db=config.ambient_noise_ray_excess_db,
    )

    temporal_persistence = _temporal_persistence(
        values,
        context,
        tolerance=config.temporal_dbzh_tolerance_db,
    )
    temporal_velocity_consistency = _temporal_velocity_consistency(
        velocity,
        context,
        shape,
        tolerance=config.temporal_velocity_consistency_ms,
    )
    temporal_flow_consistency = (
        temporal_persistence
        & temporal_velocity_consistency
        & spatially_coherent
    )
    temporal_context_count = sum(
        candidate is not None
        for candidate in (
            context.previous_dbzh,
            context.next_dbzh,
        )
    )
    temporal_context_complete = temporal_context_count == 2
    temporal_static_velocity = _temporal_static_velocity(
        context,
        shape,
        maximum=config.temporal_velocity_max_ms,
    )
    temporal_velocity_context_count = sum(
        candidate is not None
        for candidate in (
            context.previous_vrad,
            context.next_vrad,
        )
    )
    temporal_velocity_context_complete = (
        temporal_velocity_context_count == 2
    )
    upper_cross_scan_coverage = _finite_context_coverage(
        context.upper_elevation_dbzh,
        shape,
        label="upper-elevation DBZH",
    )
    temporal_cross_scan_coverage = _complete_context_coverage(
        (
            (context.previous_dbzh, "previous DBZH"),
            (context.next_dbzh, "next DBZH"),
            (context.previous_vrad, "previous VRAD"),
            (context.next_vrad, "next VRAD"),
        ),
        shape,
    )
    receiver_cross_scan_context = (
        upper_cross_scan_coverage | temporal_cross_scan_coverage
    )
    learned_temporal_support = (
        _temporal_persistence(
            values,
            context,
            tolerance=(
                config.learned_clutter_temporal_dbzh_tolerance_db
            ),
        )
        & temporal_static_velocity
        if (
            temporal_context_complete
            and temporal_velocity_context_complete
        )
        else np.zeros(shape, dtype=bool)
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
    learned_statistics_qualified = (
        context.background_statistics_version
        == BACKGROUND_MODEL_V3_STATISTICS_VERSION
    )
    learned_background_available = bool(
        learned_statistics_qualified
        and context.background_distinct_date_count is not None
        and context.background_static_echo_date_frequency is not None
        and context.background_static_echo_season_count is not None
        and context.background_static_echo_time_bucket_count is not None
        and context.background_static_dbzh_p10 is not None
        and context.background_static_dbzh_median is not None
        and context.background_static_dbzh_p90 is not None
    )
    if learned_statistics_qualified:
        learned_date_coverage = _context_threshold(
            context.background_distinct_date_count,
            shape,
            float(config.background_distinct_date_min),
        )
        learned_static_date_frequency = _context_threshold(
            context.background_static_echo_date_frequency,
            shape,
            config.background_static_date_frequency_min,
        )
        learned_season_coverage = _context_threshold(
            context.background_static_echo_season_count,
            shape,
            float(config.background_required_season_count),
        )
        learned_time_coverage = _context_threshold(
            context.background_static_echo_time_bucket_count,
            shape,
            float(config.background_required_time_bucket_count),
        )
        learned_dbzh_compatible = (
            _context_ceiling(
                values,
                context.background_static_dbzh_p90,
                margin=config.background_static_dbzh_p90_excess_max_db,
            )
            & _context_ceiling(
                values,
                context.background_static_dbzh_median,
                margin=(
                    config.background_static_dbzh_median_excess_max_db
                ),
            )
            & _context_interval_width_max(
                context.background_static_dbzh_p10,
                context.background_static_dbzh_p90,
                shape,
                maximum=(
                    config.background_static_dbzh_interquantile_range_max_db
                ),
            )
        )
    else:
        learned_date_coverage = np.zeros(shape, dtype=bool)
        learned_static_date_frequency = np.zeros(shape, dtype=bool)
        learned_season_coverage = np.zeros(shape, dtype=bool)
        learned_time_coverage = np.zeros(shape, dtype=bool)
        learned_dbzh_compatible = np.zeros(shape, dtype=bool)

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
        physical_noise_range_law,
        EvidenceFlag.PHYSICAL_NOISE_RANGE_LAW,
    )
    _set_evidence(
        evidence,
        learned_date_coverage,
        EvidenceFlag.LEARNED_DATE_COVERAGE,
    )
    _set_evidence(
        evidence,
        learned_static_date_frequency,
        EvidenceFlag.LEARNED_STATIC_DATE_FREQUENCY,
    )
    _set_evidence(
        evidence,
        learned_season_coverage,
        EvidenceFlag.LEARNED_SEASON_COVERAGE,
    )
    _set_evidence(
        evidence,
        learned_time_coverage,
        EvidenceFlag.LEARNED_TIME_COVERAGE,
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
    _set_evidence(
        evidence,
        ambient_noise_outlier,
        EvidenceFlag.AMBIENT_NOISE_RAY_OUTLIER,
    )
    _set_evidence(
        evidence,
        temporal_static_velocity,
        EvidenceFlag.TEMPORAL_STATIC_VELOCITY,
    )
    _set_evidence(
        evidence,
        coherent_doppler_flow,
        EvidenceFlag.COHERENT_DOPPLER_FLOW,
    )
    _set_evidence(
        evidence,
        temporal_flow_consistency,
        EvidenceFlag.TEMPORAL_FLOW_CONSISTENCY,
    )
    _set_evidence(
        evidence,
        receiver_cross_scan_context,
        EvidenceFlag.RECEIVER_CROSS_SCAN_CONTEXT,
    )
    _set_evidence(
        evidence,
        physical_noise_range_law & fixed_slope_noise_ridge,
        EvidenceFlag.FIXED_SLOPE_NOISE_RIDGE,
    )

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
    radial_signal_protected = (
        coherent_doppler_flow
        | temporal_flow_consistency
        | upper_support
        | quality_coherent_signal
        | (
            spatially_coherent
            & (
                values
                >= float(
                    config.interference_strong_coherent_protection_dbzh
                )
            )
        )
    )
    radial_spoke &= ~radial_signal_protected
    _set_evidence(evidence, radial_spoke, EvidenceFlag.RADIAL_SPOKE)

    polarimetric_noise_family = (
        low_rho_noise | zdr_outlier | phidp_chaotic
    )
    doppler_noise_family = velocity_rough | wide_spectrum
    spatial_noise_family = spatially_incoherent
    hardware_noise_family = ambient_noise_outlier
    independent_family_score = (
        polarimetric_noise_family.astype("int16")
        + doppler_noise_family.astype("int16")
        + spatial_noise_family.astype("int16")
        + hardware_noise_family.astype("int16")
    )
    _set_evidence(
        evidence,
        polarimetric_noise_family,
        EvidenceFlag.POLARIMETRIC_NOISE_FAMILY,
    )
    _set_evidence(
        evidence,
        doppler_noise_family,
        EvidenceFlag.DOPPLER_NOISE_FAMILY,
    )
    _set_evidence(
        evidence,
        spatial_noise_family,
        EvidenceFlag.SPATIAL_NOISE_FAMILY,
    )

    receiver_signal_protected = (
        coherent_doppler_flow | temporal_flow_consistency | upper_support
    )
    receiver_noise_candidate = (
        finite
        & high_ci
        & low_sqi
        & physical_noise_range_law
        & (
            independent_family_score
            >= config.noise_min_independent_families
        )
        & ~receiver_signal_protected
        & ~radial_spoke
    )
    receiver_noise_internal_context_required = (
        fixed_slope_noise_ridge
    )
    if receiver_noise_internal_context_required:
        receiver_noise_context_qualified = (
            temporal_cross_scan_coverage
        )
    elif context.receiver_noise_cross_scan_required:
        receiver_noise_context_qualified = receiver_cross_scan_context
    else:
        receiver_noise_context_qualified = np.ones(shape, dtype=bool)
    receiver_noise_context_fail_open = (
        receiver_noise_candidate & ~receiver_noise_context_qualified
    )
    receiver_noise = (
        receiver_noise_candidate & receiver_noise_context_qualified
    )

    current_stationary = (
        finite
        & low_ci
        & near_zero_velocity
        & spatially_coherent
        & (values >= 5.0)
    )
    learned_background_prior = (
        current_stationary
        & learned_date_coverage
        & learned_static_date_frequency
        & learned_season_coverage
        & learned_time_coverage
        & learned_dbzh_compatible
        & learned_background_available
        & context.temporal_context_required
        & context.learned_background_allowed
        & ~upper_support
        & upper_context_qualified
    )
    temporal_advection_support = _temporal_advection_support(
        values,
        context,
        learned_background_prior,
        tolerance=config.temporal_dbzh_tolerance_db,
        maximum_ray_shift=config.temporal_advection_max_ray_shift,
        maximum_gate_shift=config.temporal_advection_max_gate_shift,
        minimum_improvement=(
            config.temporal_advection_minimum_improvement_db
        ),
    )
    learned_static_prior = (
        learned_background_prior & learned_temporal_support
    )
    clutter_quality_family = clutter_sqi
    clutter_polarimetric_family = (
        low_rho_clutter | phidp_rough | zdr_outlier
    )
    clutter_doppler_family = velocity_rough | wide_spectrum
    current_clutter_evidence_score = (
        clutter_quality_family.astype("int16")
        + clutter_polarimetric_family.astype("int16")
        + clutter_doppler_family.astype("int16")
    )
    current_clutter_evidence = (
        low_rho_clutter
        | (
            current_clutter_evidence_score
            >= int(config.learned_clutter_min_current_evidence_families)
        )
    )
    transient_current_nuisance_evidence = (
        strong_low_rho_clutter
        | (
            current_clutter_evidence_score
            >= int(config.learned_clutter_min_current_evidence_families)
        )
    )
    learned_signal_protected = (
        upper_support
        | coherent_doppler_flow
        | temporal_advection_support
    )
    learned_static_clutter = (
        learned_static_prior
        & current_clutter_evidence
        & ~learned_signal_protected
    )
    learned_transient_nonmeteorological = (
        learned_static_prior
        & current_clutter_evidence
        & clutter_polarimetric_family
        & clutter_doppler_family
        & ~learned_signal_protected
    )
    temporal_transient = (
        ~temporal_persistence
        if temporal_context_complete
        else np.zeros(shape, dtype=bool)
    )
    try:
        elevation_deg = (
            float(context.elevation_deg)
            if context.elevation_deg is not None
            else None
        )
    except (TypeError, ValueError):
        elevation_deg = None
    ap_geometry_qualified = bool(
        elevation_deg is not None
        and np.isfinite(elevation_deg)
        and elevation_deg
        <= float(config.anomalous_propagation_max_elevation_deg)
    )
    independent_anomalous_propagation_candidate = (
        current_stationary
        & transient_current_nuisance_evidence
        & clutter_polarimetric_family
        & temporal_transient
        & ap_geometry_qualified
        & ~upper_support
        & upper_context_qualified
        & ~learned_signal_protected
    )
    anomalous_propagation = (
        learned_static_clutter
        & learned_transient_nonmeteorological
    )
    static_clutter = learned_static_clutter & ~anomalous_propagation

    isolated_speckle = (
        config.isolated_speckle_enabled
        & finite
        & spatially_incoherent
        & high_ci
        & low_sqi
        & physical_noise_range_law
        & (
            independent_family_score
            >= config.noise_min_independent_families
        )
    )
    isolated_speckle &= ~(
        radial_spoke
        | receiver_noise
        | static_clutter
        | anomalous_propagation
    )

    general_protected = finite & (
        upper_support
        | coherent_doppler_flow
        | temporal_advection_support
        | (
            spatially_coherent
            & ~low_sqi
            & ~low_ci
        )
    )
    protected = general_protected
    nuisance = np.zeros(shape, dtype="uint16")
    nuisance[radial_spoke] |= int(NuisanceFlag.RADIAL_INTERFERENCE)
    nuisance[receiver_noise] |= int(NuisanceFlag.RECEIVER_NOISE)
    nuisance[static_clutter] |= int(NuisanceFlag.STATIC_CLUTTER)
    nuisance[anomalous_propagation] |= int(
        NuisanceFlag.ANOMALOUS_PROPAGATION
    )
    nuisance[isolated_speckle] |= int(NuisanceFlag.ISOLATED_SPECKLE)
    remove = finite & (nuisance != 0) & ~general_protected
    nuisance[~remove] = 0

    confidence = np.zeros(shape, dtype="float32")
    confidence[radial_spoke] = 0.99
    confidence[receiver_noise] = np.maximum(
        confidence[receiver_noise],
        np.minimum(
            0.93 + 0.015 * independent_family_score[receiver_noise],
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
        "physical_noise_compatible": int(
            physical_noise_range_law.sum()
        ),
        "coherent_doppler_flow_protected": int(
            coherent_doppler_flow.sum()
        ),
        "temporal_flow_protected": int(
            temporal_flow_consistency.sum()
        ),
        "receiver_noise_candidate": int(receiver_noise_candidate.sum()),
        "receiver_noise_cross_scan_context": int(
            receiver_cross_scan_context.sum()
        ),
        "receiver_noise_context_fail_open": int(
            receiver_noise_context_fail_open.sum()
        ),
        "fixed_slope_receiver_candidate": int(
            receiver_noise_candidate.sum()
            if fixed_slope_noise_ridge
            else 0
        ),
        "learned_static_prior": int(learned_static_prior.sum()),
        "current_clutter_evidence": int(
            current_clutter_evidence.sum()
        ),
        "learned_static_amplitude_stability": int(
            learned_temporal_support.sum()
        ),
        "temporal_advection_protected": int(
            temporal_advection_support.sum()
        ),
        "quality_coherent_signal_protected": int(
            quality_coherent_signal.sum()
        ),
        "radial_interference_signal_protected": int(
            radial_signal_protected.sum()
        ),
        "independent_anomalous_propagation_candidate": int(
            independent_anomalous_propagation_candidate.sum()
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
            "geometry": {
                "rstart_km": receiver_model_metadata.get("rstart_km"),
                "rscale_m": receiver_model_metadata.get("rscale_m"),
            },
            "receiver_noise_model": receiver_model_metadata,
            "receiver_noise_evidence_families": {
                "minimum_required": int(
                    config.noise_min_independent_families
                ),
                "polarimetric_gate_count": int(
                    polarimetric_noise_family.sum()
                ),
                "doppler_gate_count": int(
                    doppler_noise_family.sum()
                ),
                "spatial_gate_count": int(
                    spatial_noise_family.sum()
                ),
                "hardware_gate_count": int(
                    hardware_noise_family.sum()
                ),
            },
            "context": {
                "temporal": temporal_context_count > 0,
                "temporal_context_count": temporal_context_count,
                "temporal_context_complete": temporal_context_complete,
                "temporal_context_required": bool(
                    context.temporal_context_required
                ),
                "temporal_velocity_context_count": (
                    temporal_velocity_context_count
                ),
                "temporal_velocity_context_complete": (
                    temporal_velocity_context_complete
                ),
                "upper_elevation": context.upper_elevation_dbzh is not None,
                "elevation_deg": elevation_deg,
                "anomalous_propagation_geometry_qualified": (
                    ap_geometry_qualified
                ),
                "learned_clutter_temporal_dbzh_tolerance_db": float(
                    config.learned_clutter_temporal_dbzh_tolerance_db
                ),
                "independent_anomalous_propagation_policy": (
                    "diagnostic-only; removal requires learned background support"
                ),
                "upper_elevation_required": bool(
                    context.upper_elevation_required
                ),
                "receiver_noise_cross_scan_required": bool(
                    context.receiver_noise_cross_scan_required
                ),
                "receiver_noise_internal_context_required": bool(
                    receiver_noise_internal_context_required
                ),
                "receiver_noise_internal_context_policy": (
                    "complete_previous_next_dbzh_vrad"
                    if receiver_noise_internal_context_required
                    else None
                ),
                "receiver_noise_cross_scan_available": bool(
                    receiver_cross_scan_context.any()
                ),
                "receiver_noise_cross_scan_gate_count": int(
                    receiver_cross_scan_context.sum()
                ),
                "receiver_noise_context_fail_open_gate_count": int(
                    receiver_noise_context_fail_open.sum()
                ),
                "learned_background": learned_background_available,
                "learned_background_statistics_version": (
                    context.background_statistics_version
                ),
                "learned_background_statistics_qualified": (
                    learned_statistics_qualified
                ),
                "learned_background_allowed": bool(
                    context.learned_background_allowed
                ),
            },
            "policy": (
                "mechanism-specific physical support plus independent "
                "evidence families; the learned map is a prior rather "
                "than a deletion rule, and coherent temporal, Doppler, "
                "quality, or upper-elevation evidence protects the echo; "
                "contradictory, correlated-only, or insufficient evidence "
                "is retained"
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


def _finite_context_coverage(
    candidate: Any | None,
    shape: tuple[int, int],
    *,
    label: str,
) -> Any:
    np = require_numpy()
    if candidate is None:
        return np.zeros(shape, dtype=bool)
    values = np.asarray(candidate, dtype="float32")
    if values.shape != shape:
        raise ValueError(f"{label} context shape mismatch")
    return np.isfinite(values)


def _complete_context_coverage(
    candidates: tuple[tuple[Any | None, str], ...],
    shape: tuple[int, int],
) -> Any:
    np = require_numpy()
    coverage = np.ones(shape, dtype=bool)
    for candidate, label in candidates:
        if candidate is None:
            return np.zeros(shape, dtype=bool)
        coverage &= _finite_context_coverage(
            candidate,
            shape,
            label=label,
        )
    return coverage


def _receiver_noise_support(
    values: Any,
    seeds: Any,
    *,
    pulse: str,
    rstart_km: float | None,
    rscale_m: float | None,
    config: ReceiverNoiseModelConfig,
    lp_fixed_slope_mode_enabled: bool,
) -> tuple[Any, Any, dict[str, Any]]:
    np = require_numpy()
    shape = np.asarray(values).shape
    empty_profile = np.full(shape[1], np.nan, dtype="float32")
    empty_mask = np.zeros(shape, dtype=bool)
    try:
        start = float(rstart_km) if rstart_km is not None else None
        scale = float(rscale_m) if rscale_m is not None else None
    except (TypeError, ValueError):
        start = scale = None
    if (
        start is None
        or scale is None
        or not np.isfinite(start)
        or not np.isfinite(scale)
        or start < 0.0
        or scale <= 0.0
    ):
        return (
            empty_profile,
            empty_mask,
            {
                "status": "missing_or_invalid_geometry",
                "qualified": False,
                "configuration": asdict(config),
                "rstart_km": start,
                "rscale_m": scale,
            },
        )
    try:
        free_slope_model = fit_range_corrected_receiver_noise(
            values,
            seeds,
            rstart_km=start,
            rscale_m=scale,
            config=config,
        )
    except (TypeError, ValueError) as exc:
        return (
            empty_profile,
            empty_mask,
            {
                "status": "invalid_receiver_model_input",
                "qualified": False,
                "error": f"{type(exc).__name__}: {exc}",
                "configuration": asdict(config),
                "rstart_km": start,
                "rscale_m": scale,
            },
        )
    fixed_slope_model = None
    fixed_slope_error = None
    fixed_slope_attempted = bool(
        lp_fixed_slope_mode_enabled
        and str(pulse).strip().lower() == "lp"
    )
    if fixed_slope_attempted:
        try:
            fixed_slope_model = fit_fixed_slope_receiver_noise(
                values,
                seeds,
                rstart_km=start,
                rscale_m=scale,
                config=config,
            )
        except (TypeError, ValueError) as exc:
            fixed_slope_error = f"{type(exc).__name__}: {exc}"
    model = (
        fixed_slope_model
        if fixed_slope_model is not None and fixed_slope_model.qualified
        else free_slope_model
    )
    compatible = np.asarray(model.compatible_mask, dtype=bool)
    metadata = {
        "status": model.status,
        "qualified": bool(model.qualified),
        "fit_strategy": model.fit_strategy,
        "configuration": asdict(config),
        "rstart_km": start,
        "rscale_m": scale,
        "free_slope_status": free_slope_model.status,
        "free_slope_qualified": bool(free_slope_model.qualified),
        "fixed_slope_attempted": fixed_slope_attempted,
        "fixed_slope_status": (
            fixed_slope_model.status
            if fixed_slope_model is not None
            else None
        ),
        "fixed_slope_qualified": bool(
            fixed_slope_model is not None
            and fixed_slope_model.qualified
        ),
        "fixed_slope_error": fixed_slope_error,
        "seed_count": int(model.seed_count),
        "supported_bin_count": int(model.supported_bin_count),
        "supported_span_km": float(model.supported_span_km),
        "consistent_bin_fraction": float(
            model.consistent_bin_fraction
        ),
        "fit_median_error_db": model.fit_median_error_db,
        "range_slope_db_per_decade": (
            model.range_slope_db_per_decade
        ),
        "range_intercept_db": model.range_intercept_db,
        "residual_location_db": model.residual_location_db,
        "residual_scale_db": model.residual_scale_db,
        "lower_residual_db": model.lower_residual_db,
        "upper_residual_db": model.upper_residual_db,
        "compatible_gate_count": int(compatible.sum()),
    }
    return (
        np.asarray(model.floor_profile_dbzh, dtype="float32"),
        compatible,
        metadata,
    )


def _coherent_doppler_flow(
    velocity: Any | None,
    base: Any,
    *,
    tolerance: float,
    minimum_neighbours: int,
    minimum_speed: float,
) -> Any:
    np = require_numpy()
    shape = np.asarray(base).shape
    if velocity is None:
        return np.zeros(shape, dtype=bool)
    values = np.asarray(velocity, dtype="float32")
    similar, _ = _neighbour_support(values, tolerance=tolerance)
    return (
        np.asarray(base, dtype=bool)
        & np.isfinite(values)
        & (np.abs(values) >= float(minimum_speed))
        & (similar >= max(1, int(minimum_neighbours)))
    )


def _temporal_velocity_consistency(
    velocity: Any | None,
    context: EvidenceContext,
    shape: tuple[int, int],
    *,
    tolerance: float,
) -> Any:
    np = require_numpy()
    if (
        velocity is None
        or context.previous_vrad is None
        or context.next_vrad is None
    ):
        return np.zeros(shape, dtype=bool)
    current = np.asarray(velocity, dtype="float32")
    previous = np.asarray(context.previous_vrad, dtype="float32")
    following = np.asarray(context.next_vrad, dtype="float32")
    for array in (current, previous, following):
        if array.shape != shape:
            raise ValueError("temporal VRAD context shape mismatch")
    limit = float(tolerance)
    return (
        np.isfinite(current)
        & np.isfinite(previous)
        & np.isfinite(following)
        & (np.abs(current - previous) <= limit)
        & (np.abs(current - following) <= limit)
        & (np.abs(previous - following) <= limit)
    )


def _ambient_noise_outlier(
    fields: dict[str, Any],
    shape: tuple[int, int],
    *,
    excess_db: float,
) -> Any:
    np = require_numpy()
    combined = np.zeros(shape, dtype=bool)
    for candidates in (
        AMBIENT_NOISE_H_CANDIDATES,
        AMBIENT_NOISE_V_CANDIDATES,
    ):
        values = _field(fields, candidates)
        if values is None:
            continue
        array = np.asarray(values, dtype="float32")
        finite = array[np.isfinite(array)]
        if finite.size == 0:
            continue
        scan_median = float(np.nanmedian(finite))
        if scan_median <= -20.0:
            continue
        combined |= (
            np.isfinite(array)
            & (array >= scan_median + float(excess_db))
        )
    return combined


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


def _temporal_advection_support(
    values: Any,
    context: EvidenceContext,
    candidate_mask: Any,
    *,
    tolerance: float,
    maximum_ray_shift: int,
    maximum_gate_shift: int,
    minimum_improvement: float,
) -> Any:
    """Protect candidates better explained by coherent scan-to-scan motion."""

    np = require_numpy()
    current = np.asarray(values, dtype="float32")
    candidates = np.asarray(candidate_mask, dtype=bool)
    if candidates.shape != current.shape:
        raise ValueError("temporal advection candidate shape mismatch")
    if (
        context.previous_dbzh is None
        or context.next_dbzh is None
        or not candidates.any()
    ):
        return np.zeros(current.shape, dtype=bool)
    previous = np.asarray(context.previous_dbzh, dtype="float32")
    following = np.asarray(context.next_dbzh, dtype="float32")
    if previous.shape != current.shape or following.shape != current.shape:
        raise ValueError("temporal DBZH context shape mismatch")

    rows, gates = np.nonzero(candidates & np.isfinite(current))
    if rows.size == 0:
        return np.zeros(current.shape, dtype=bool)
    current_values = current[rows, gates]
    previous_same = previous[rows, gates]
    following_same = following[rows, gates]
    exact_error = np.maximum(
        np.abs(current_values - previous_same),
        np.abs(current_values - following_same),
    )
    exact_error[
        ~np.isfinite(previous_same) | ~np.isfinite(following_same)
    ] = np.inf
    best_shifted_error = np.full(rows.shape, np.inf, dtype="float32")
    ray_limit = max(0, int(maximum_ray_shift))
    gate_limit = max(0, int(maximum_gate_shift))
    nrays, nbins = current.shape
    for ray_shift in range(-ray_limit, ray_limit + 1):
        for gate_shift in range(-gate_limit, gate_limit + 1):
            if ray_shift == 0 and gate_shift == 0:
                continue
            previous_gates = gates - gate_shift
            following_gates = gates + gate_shift
            valid = (
                (previous_gates >= 0)
                & (previous_gates < nbins)
                & (following_gates >= 0)
                & (following_gates < nbins)
            )
            if not valid.any():
                continue
            selected = np.flatnonzero(valid)
            previous_rows = (rows[selected] - ray_shift) % nrays
            following_rows = (rows[selected] + ray_shift) % nrays
            previous_values = previous[
                previous_rows,
                previous_gates[selected],
            ]
            following_values = following[
                following_rows,
                following_gates[selected],
            ]
            finite = (
                np.isfinite(previous_values)
                & np.isfinite(following_values)
            )
            if not finite.any():
                continue
            selected = selected[finite]
            shifted_error = np.maximum(
                np.abs(current_values[selected] - previous_values[finite]),
                np.abs(current_values[selected] - following_values[finite]),
            )
            best_shifted_error[selected] = np.minimum(
                best_shifted_error[selected],
                shifted_error,
            )

    supported = (
        np.isfinite(best_shifted_error)
        & (best_shifted_error <= float(tolerance))
        & (
            best_shifted_error + float(minimum_improvement)
            <= exact_error
        )
    )
    output = np.zeros(current.shape, dtype=bool)
    output[rows[supported], gates[supported]] = True
    return output


def _temporal_static_velocity(
    context: EvidenceContext,
    shape: tuple[int, int],
    *,
    maximum: float,
) -> Any:
    np = require_numpy()
    supports = []
    for candidate in (context.previous_vrad, context.next_vrad):
        if candidate is None:
            continue
        array = np.asarray(candidate, dtype="float32")
        if array.shape != shape:
            raise ValueError("temporal VRAD context shape mismatch")
        supports.append(
            np.isfinite(array)
            & (np.abs(array) <= float(maximum))
        )
    if not supports:
        return np.zeros(shape, dtype=bool)
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


def _context_interval_width_max(
    lower: Any | None,
    upper: Any | None,
    shape: tuple[int, int],
    *,
    maximum: float,
) -> Any:
    np = require_numpy()
    if lower is None or upper is None:
        return np.zeros(shape, dtype=bool)
    low = np.asarray(lower, dtype="float32")
    high = np.asarray(upper, dtype="float32")
    if low.shape != shape or high.shape != shape:
        raise ValueError("learned DBZH context shape mismatch")
    return (
        np.isfinite(low)
        & np.isfinite(high)
        & (high >= low)
        & ((high - low) <= float(maximum))
    )


def _set_evidence(target: Any, mask: Any, flag: EvidenceFlag) -> None:
    np = require_numpy()
    target[np.asarray(mask, dtype=bool)] |= int(flag)
