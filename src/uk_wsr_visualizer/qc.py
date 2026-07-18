"""Canonical gate-level QC masks for UK WSR polar fields."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntFlag
from typing import Any

from .dependencies import require_numpy

QC_VERSION = "qc-v2"


class QCMaskFlag(IntFlag):
    """Gate-level QC mask flags stored in a uint16 bitmask."""

    NO_DATA = 1
    USER_DOMAIN = 2
    NOISE_FLOOR = 4
    TEXTURE_SPECKLE = 8
    STATIC_CLUTTER = 16
    DUALPOL_QC = 32
    VELOCITY_QC = 64
    BLOCKAGE = 128
    AP_RISK = 256
    VP_DOMAIN = 512
    BACKGROUND_CLUTTER = 1024
    RECEIVER_NOISE = 2048


REFLECTIVITY_QUANTITIES = {"DBZ", "DBZH", "DBZV", "DBZHC", "DBZVC", "TH", "TV", "CZ", "DZ", "AZ", "Z"}
REFLECTIVITY_CANDIDATES = ("DBZH", "TH", "DBZ", "DBZV", "DBZHC", "DBZVC", "CZ", "DZ", "AZ", "Z")
SQI_CANDIDATES = ("SQIH", "SQI", "QIND")
RHOHV_CANDIDATES = ("RHOHV", "RHO", "CC")
ZDR_CANDIDATES = ("ZDR", "ZDRH", "ZDRV")
PHIDP_CANDIDATES = ("PHIDP", "UPHIDP", "PHI")
VRAD_CANDIDATES = ("VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH", "VELV")
WIDTH_CANDIDATES = ("WRADH", "WRAD", "WRADV", "WIDTH", "SW", "SWRAD")
CI_CANDIDATES = ("CI", "APD", "CLUTTER_INDICATOR")
AMBIENT_NOISE_H_CANDIDATES = ("LONG_RANGE_NOISE_DBC_H", "AMBIENT_NOISE_DBC_H")
AMBIENT_NOISE_V_CANDIDATES = ("LONG_RANGE_NOISE_DBC_V", "AMBIENT_NOISE_DBC_V")
COMPANION_FIELD_CANDIDATES = tuple(
    dict.fromkeys(
        REFLECTIVITY_CANDIDATES
        + SQI_CANDIDATES
        + RHOHV_CANDIDATES
        + ZDR_CANDIDATES
        + PHIDP_CANDIDATES
        + VRAD_CANDIDATES
        + WIDTH_CANDIDATES
        + CI_CANDIDATES
        + AMBIENT_NOISE_H_CANDIDATES
        + AMBIENT_NOISE_V_CANDIDATES
    )
)


@dataclass(frozen=True)
class QCConfig:
    """Configuration for the canonical gate-mask builder."""

    mode: str = "off"
    operation: str = "mask"
    noise_floor_enabled: bool = False
    noise_floor_method: str = "estimated"
    noise_floor_margin_db: float = 0.0
    noise_floor_hard_mask: bool = True
    noise_floor_percentile: float = 10.0
    noise_floor_window_bins: int = 11
    receiver_noise_enabled: bool = False
    receiver_noise_margin_db: float = 0.25
    receiver_noise_sqi_max: float = 0.05
    receiver_noise_rhohv_max: float = 0.20
    receiver_noise_phidp_texture_min_deg: float = 60.0
    receiver_noise_velocity_texture_min_ms: float = 18.0
    receiver_noise_min_bad_moments: int = 3
    ambient_noise_ray_excess_db: float = 3.0
    ci_enabled: bool = True
    ci_noise_min_db: float = 6.0
    ci_clutter_max_db: float = 2.0
    texture_enabled: bool = True
    texture_threshold_db: float = 10.0
    texture_near_margin_db: float = 20.0
    texture_support_db: float = 6.0
    texture_max_dbz: float = 30.0
    texture_min_similar_neighbors: int = 1
    companion_qc_enabled: bool = False
    sqi_strong: float = 0.20
    sqi_medium: float = 0.45
    sqi_weak: float = 0.65
    rhohv_strong: float = 0.55
    rhohv_weak: float = 0.75
    zdr_min_db: float = -3.0
    zdr_max_db: float = 8.0
    phidp_texture_medium_deg: float = 30.0
    phidp_texture_strong_deg: float = 60.0
    velocity_texture_medium_ms: float = 9.0
    velocity_texture_strong_ms: float = 18.0
    spectrum_width_max_ms: float = 8.0
    near_noise_margin_db: float = 6.0
    near_noise_score_threshold: int = 3
    score_threshold: int = 4
    companion_qc_near_noise_only: bool = False
    rhohv_low_is_noise_evidence: bool = True
    static_clutter_enabled: bool = False
    static_clutter_dbz_min: float = 5.0
    static_clutter_vrad_abs_max_ms: float = 1.0
    static_clutter_min_neighbors: int = 3
    background_model_enabled: bool = False
    background_model_path: str | None = None
    background_persistent_frequency_min: float = 0.95
    background_min_samples: int = 40
    background_static_vrad_frequency_min: float = 0.80
    background_low_sqi_frequency_min: float = 0.40
    background_dbzh_excess_max_db: float = 3.0
    background_evidence_score_threshold: int = 3
    background_current_vrad_abs_max_ms: float = 0.50
    background_learned_low_ci_frequency_min: float = 0.60
    background_require_current_ci: bool = True
    background_require_current_vrad: bool = True
    background_require_training_diversity: bool = True
    background_min_training_dates: int = 7
    background_min_training_span_days: int = 14
    reflectivity_fallback_to_values: bool = True

    def __post_init__(self) -> None:
        if self.mode == "signal_preserving":
            object.__setattr__(self, "noise_floor_hard_mask", False)
            object.__setattr__(self, "companion_qc_near_noise_only", True)
            object.__setattr__(self, "rhohv_low_is_noise_evidence", False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QCMaskResult:
    """Cleaned field and gate-level QC bitmask."""

    values: Any
    mask: Any
    config: QCConfig
    finite_before: int
    finite_after: int
    floor_profile: list[float | None] = field(default_factory=list)
    flag_counts: dict[str, int] = field(default_factory=dict)
    source_quantity: str | None = None
    companion_quantities: list[str] = field(default_factory=list)
    background_model: dict[str, Any] = field(default_factory=dict)
    evidence_counts: dict[str, int] = field(default_factory=dict)
    noise_metadata: dict[str, Any] = field(default_factory=dict)
    version: str = QC_VERSION

    @property
    def masked_count(self) -> int:
        return max(0, self.finite_before - self.finite_after)

    def to_dict(self, *, include_profile: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": self.version,
            "enabled": self.config.mode != "off" or any(self.flag_counts.values()),
            "mode": self.config.mode,
            "operation": self.config.operation,
            "finite_before": self.finite_before,
            "finite_after": self.finite_after,
            "masked_count": self.masked_count,
            "flag_counts": dict(self.flag_counts),
            "source_quantity": self.source_quantity,
            "companion_quantities": list(self.companion_quantities),
            "evidence_counts": dict(self.evidence_counts),
            "noise_metadata": dict(self.noise_metadata),
            "config": self.config.to_dict(),
        }
        if self.background_model:
            payload["background_model"] = dict(self.background_model)
        if include_profile:
            payload["floor_profile"] = list(self.floor_profile)
        return payload


def normalized_quantity(quantity: str | None) -> str:
    return str(quantity or "").strip().upper()


def is_reflectivity_quantity(quantity: str | None) -> bool:
    key = normalized_quantity(quantity)
    return key in REFLECTIVITY_QUANTITIES or "REFLECTIVITY" in str(quantity or "").lower()


def qc_config_from_filters(filters: dict[str, Any] | None) -> QCConfig:
    filters = filters or {}
    mode = _filter_text(filters, "qc_mode", "off")
    signal_preserving_modes = {"signal_preserving"}
    noise_enabled = _filter_bool(filters, "noise_floor_enabled") or mode not in {"", "off", "none"}
    companion_enabled = _filter_bool(filters, "qc_companion_enabled") or mode in {
        "vp_standard",
        "vp_strict",
    }
    static_enabled = _filter_bool(filters, "qc_static_clutter_enabled") or mode in {"vp_standard", "vp_strict"}
    if mode in {"", "none"}:
        mode = "off"
    if _filter_bool(filters, "noise_floor_enabled") and mode == "off":
        mode = "display_standard"
    is_signal_preserving = mode in signal_preserving_modes
    receiver_noise_enabled = (
        _filter_bool(filters, "qc_receiver_noise_enabled")
        if "qc_receiver_noise_enabled" in filters
        else is_signal_preserving
    )
    ci_enabled = _filter_bool(filters, "qc_ci_enabled") if "qc_ci_enabled" in filters else True
    background_path = filters.get("qc_background_model_path") or filters.get("background_model_path")
    background_flag_present = "qc_background_model_enabled" in filters
    background_enabled = (
        _filter_bool(filters, "qc_background_model_enabled")
        if background_flag_present
        else mode in signal_preserving_modes
    ) or bool(background_path)
    margin = _filter_float(filters, "noise_floor_margin_db")
    if margin is None:
        margin = 0.0 if mode in signal_preserving_modes else 6.0 if mode == "vp_standard" else 10.0 if mode == "vp_strict" else 3.0
    percentile = _filter_float(filters, "noise_floor_percentile")
    window_bins = _filter_float(filters, "noise_floor_window_bins")
    texture_enabled_default = not is_signal_preserving
    persistent_default = 0.95 if is_signal_preserving else 0.60
    min_samples_default = 40.0 if is_signal_preserving else 20.0
    static_frequency_default = 0.80 if is_signal_preserving else 0.40
    dbzh_excess_default = 3.0 if is_signal_preserving else 8.0
    evidence_threshold_default = 3.0 if is_signal_preserving else 2.0
    return QCConfig(
        mode=mode,
        operation=_filter_text(filters, "noise_floor_operation", "mask") if noise_enabled else "none",
        noise_floor_enabled=noise_enabled,
        noise_floor_method="estimated",
        noise_floor_margin_db=float(margin),
        noise_floor_hard_mask=not is_signal_preserving,
        noise_floor_percentile=10.0 if percentile is None else max(0.0, min(100.0, float(percentile))),
        noise_floor_window_bins=11 if window_bins is None else max(1, int(window_bins)),
        receiver_noise_enabled=receiver_noise_enabled,
        receiver_noise_margin_db=_filter_default(filters, "qc_receiver_noise_margin_db", 0.25, min_value=0.0),
        receiver_noise_sqi_max=_filter_default(filters, "qc_receiver_noise_sqi_max", 0.05, min_value=0.0),
        receiver_noise_rhohv_max=_filter_default(filters, "qc_receiver_noise_rhohv_max", 0.20),
        receiver_noise_phidp_texture_min_deg=_filter_default(
            filters, "qc_receiver_noise_phidp_texture_min_deg", 60.0, min_value=0.0
        ),
        receiver_noise_velocity_texture_min_ms=_filter_default(
            filters, "qc_receiver_noise_velocity_texture_min_ms", 18.0, min_value=0.0
        ),
        receiver_noise_min_bad_moments=max(
            1, int(_filter_default(filters, "qc_receiver_noise_min_bad_moments", 3.0, min_value=1.0))
        ),
        ambient_noise_ray_excess_db=_filter_default(
            filters, "qc_ambient_noise_ray_excess_db", 3.0, min_value=0.0
        ),
        ci_enabled=ci_enabled,
        ci_noise_min_db=_filter_default(filters, "qc_ci_noise_min_db", 6.0, min_value=0.0),
        ci_clutter_max_db=_filter_default(filters, "qc_ci_clutter_max_db", 2.0, min_value=0.0),
        texture_enabled=(
            texture_enabled_default
            if "noise_floor_texture_enabled" not in filters
            else _filter_bool(filters, "noise_floor_texture_enabled")
        ),
        texture_threshold_db=_filter_default(filters, "noise_floor_texture_db", 10.0, min_value=0.0),
        texture_near_margin_db=_filter_default(filters, "noise_floor_texture_near_margin_db", 20.0, min_value=0.0),
        texture_support_db=_filter_default(filters, "noise_floor_texture_support_db", 6.0, min_value=0.0),
        texture_max_dbz=_filter_default(filters, "noise_floor_texture_max_db", 30.0),
        texture_min_similar_neighbors=max(
            0, int(_filter_default(filters, "noise_floor_texture_min_similar_neighbors", 1.0))
        ),
        companion_qc_enabled=companion_enabled,
        companion_qc_near_noise_only=is_signal_preserving,
        rhohv_low_is_noise_evidence=not is_signal_preserving,
        static_clutter_enabled=static_enabled,
        background_model_enabled=background_enabled,
        background_model_path=str(background_path) if background_path not in ("", None, "NONE") else None,
        background_persistent_frequency_min=_filter_default(
            filters, "qc_background_persistent_frequency_min", persistent_default, min_value=0.0
        ),
        background_min_samples=max(
            1, int(_filter_default(filters, "qc_background_min_samples", min_samples_default, min_value=1.0))
        ),
        background_static_vrad_frequency_min=_filter_default(
            filters, "qc_background_static_vrad_frequency_min", static_frequency_default, min_value=0.0
        ),
        background_low_sqi_frequency_min=_filter_default(
            filters, "qc_background_low_sqi_frequency_min", 0.40, min_value=0.0
        ),
        background_dbzh_excess_max_db=_filter_default(
            filters, "qc_background_dbzh_excess_max_db", dbzh_excess_default, min_value=0.0
        ),
        background_evidence_score_threshold=max(
            1,
            int(
                _filter_default(
                    filters, "qc_background_evidence_score_threshold", evidence_threshold_default, min_value=1.0
                )
            ),
        ),
        background_current_vrad_abs_max_ms=_filter_default(
            filters, "qc_background_current_vrad_abs_max_ms", 0.50, min_value=0.0
        ),
        background_learned_low_ci_frequency_min=_filter_default(
            filters, "qc_background_learned_low_ci_frequency_min", 0.60, min_value=0.0
        ),
        background_require_current_ci=(
            _filter_bool(filters, "qc_background_require_current_ci")
            if "qc_background_require_current_ci" in filters
            else is_signal_preserving
        ),
        background_require_current_vrad=(
            _filter_bool(filters, "qc_background_require_current_vrad")
            if "qc_background_require_current_vrad" in filters
            else is_signal_preserving
        ),
        background_require_training_diversity=(
            _filter_bool(filters, "qc_background_require_training_diversity")
            if "qc_background_require_training_diversity" in filters
            else is_signal_preserving
        ),
        background_min_training_dates=max(
            1, int(_filter_default(filters, "qc_background_min_training_dates", 7.0, min_value=1.0))
        ),
        background_min_training_span_days=max(
            1, int(_filter_default(filters, "qc_background_min_training_span_days", 14.0, min_value=1.0))
        ),
    )


def build_qc_mask(
    values: Any,
    metadata: Any | None = None,
    *,
    companion_fields: dict[str, Any] | None = None,
    config: QCConfig | None = None,
    domain_mask: Any | None = None,
) -> QCMaskResult:
    """Build a deterministic QC bitmask and cleaned copy of a polar field."""

    np = require_numpy()
    config = config or QCConfig()
    data = np.asarray(values, dtype="float32")
    output = data.copy()
    mask = np.zeros(output.shape, dtype="uint16")
    finite_input = np.isfinite(output)
    mask[~finite_input] |= int(QCMaskFlag.NO_DATA)
    if domain_mask is not None:
        mask[np.asarray(domain_mask, dtype=bool)] |= int(QCMaskFlag.USER_DOMAIN)

    companion_arrays = _normalise_companion_fields(companion_fields, output.shape)
    source_quantity, gate_values = _reflectivity_gate_values(output, metadata, companion_arrays, config)
    companion_quantities = sorted(companion_arrays)
    floor_profile: list[float | None] = []
    background_model_info: dict[str, Any] = {}
    background_model_applied = False
    evidence_counts: dict[str, int] = {}
    noise_metadata = _noise_metadata(metadata, companion_arrays, config)

    def apply_background(base_candidates: Any) -> None:
        nonlocal background_model_applied, background_model_info
        if background_model_applied or not config.background_model_enabled:
            return
        background_model_applied = True
        if gate_values is None:
            background_model_info = {"enabled": True, "applied": False, "reason": "missing_reflectivity_gate_values"}
            return
        from .background_model import apply_background_model, default_background_model_path, load_background_model

        model_path = config.background_model_path or default_background_model_path(metadata, quantity=source_quantity)
        if not model_path:
            background_model_info = {"enabled": True, "applied": False, "reason": "no_matching_default_model"}
            return
        try:
            model = load_background_model(model_path)
            application = apply_background_model(model, gate_values, companion_arrays, config)
        except ValueError as exc:
            background_model_info = {"enabled": True, "applied": False, "reason": str(exc)}
            return
        if not application.qualified:
            background_model_info = {
                "enabled": True,
                "applied": False,
                "reason": application.reason or "model_not_qualified",
                "model": application.model,
                "evidence_counts": dict(application.evidence_counts),
            }
            return
        background_mask = base_candidates & application.mask
        mask[background_mask] |= int(QCMaskFlag.BACKGROUND_CLUTTER)
        background_model_info = {
            "enabled": True,
            "applied": True,
            "masked_count": int(background_mask.sum()),
            "model": application.model,
            "evidence_counts": dict(application.evidence_counts),
        }

    if config.noise_floor_enabled and gate_values is not None:
        profile = _estimated_noise_floor_profile(
            _masked_profile_values(gate_values, mask),
            config.noise_floor_percentile,
            config.noise_floor_window_bins,
        )
        floor_profile = _json_profile(profile)
        threshold = np.broadcast_to(profile[np.newaxis, :] + config.noise_floor_margin_db, gate_values.shape)
        candidates = _candidates(mask, output) & np.isfinite(gate_values) & np.isfinite(threshold)
        if config.noise_floor_hard_mask:
            floor_mask = candidates & (gate_values <= threshold)
            mask[floor_mask] |= int(QCMaskFlag.NOISE_FLOOR)

        if config.receiver_noise_enabled:
            receiver_mask, receiver_evidence = _receiver_noise_mask(
                gate_values,
                threshold,
                companion_arrays,
                config,
                base_candidates=_candidates(mask, output),
            )
            mask[receiver_mask] |= int(QCMaskFlag.RECEIVER_NOISE)
            evidence_counts.update(receiver_evidence)

        if config.static_clutter_enabled:
            static_mask = _static_clutter_mask(gate_values, companion_arrays, config)
            mask[_candidates(mask, output) & static_mask] |= int(QCMaskFlag.STATIC_CLUTTER)

        apply_background(_candidates(mask, output))

        if config.texture_enabled:
            texture, similar = _local_texture_and_support(gate_values, support_db=config.texture_support_db)
            texture_mask = (
                _candidates(mask, output)
                & np.isfinite(gate_values)
                & np.isfinite(texture)
                & (gate_values <= threshold + config.texture_near_margin_db)
                & (gate_values <= config.texture_max_dbz)
                & (texture >= config.texture_threshold_db)
                & (similar <= config.texture_min_similar_neighbors)
            )
            mask[texture_mask] |= int(QCMaskFlag.TEXTURE_SPECKLE)

        if config.companion_qc_enabled:
            dualpol_mask, velocity_mask = _companion_quality_masks(
                gate_values,
                threshold,
                companion_arrays,
                config,
                base_candidates=_candidates(mask, output),
            )
            mask[dualpol_mask] |= int(QCMaskFlag.DUALPOL_QC)
            mask[velocity_mask] |= int(QCMaskFlag.VELOCITY_QC)

    if config.background_model_enabled and not background_model_applied:
        apply_background(_candidates(mask, output))

    output[mask != 0] = np.nan
    finite_before = int(finite_input.sum())
    finite_after = int(np.isfinite(output).sum())
    return QCMaskResult(
        values=output,
        mask=mask,
        config=config,
        finite_before=finite_before,
        finite_after=finite_after,
        floor_profile=floor_profile,
        flag_counts=_flag_counts(mask),
        source_quantity=source_quantity,
        companion_quantities=companion_quantities,
        background_model=background_model_info,
        evidence_counts=evidence_counts,
        noise_metadata=noise_metadata,
    )


def _filter_float(filters: dict[str, Any], key: str) -> float | None:
    value = filters.get(key)
    if value in ("", None, "NONE"):
        return None
    return float(value)


def _filter_default(filters: dict[str, Any], key: str, default: float, *, min_value: float | None = None) -> float:
    value = _filter_float(filters, key)
    if value is None:
        return default
    if min_value is not None:
        return max(min_value, float(value))
    return float(value)


def _filter_bool(filters: dict[str, Any], key: str) -> bool:
    value = filters.get(key)
    if isinstance(value, bool):
        return value
    if value in ("", None, "NONE"):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _filter_text(filters: dict[str, Any], key: str, default: str) -> str:
    value = filters.get(key)
    if value in ("", None, "NONE"):
        return default
    return str(value).strip().lower()


def _normalise_companion_fields(fields: dict[str, Any] | None, shape: tuple[int, ...]) -> dict[str, Any]:
    np = require_numpy()
    out: dict[str, Any] = {}
    for quantity, values in (fields or {}).items():
        array = np.asarray(values, dtype="float32")
        if array.shape == shape:
            out[normalized_quantity(quantity)] = array
    return out


def _reflectivity_gate_values(
    values: Any,
    metadata: Any | None,
    companion_fields: dict[str, Any],
    config: QCConfig,
) -> tuple[str | None, Any | None]:
    quantity = normalized_quantity(getattr(metadata, "quantity", ""))
    if is_reflectivity_quantity(quantity):
        return quantity or None, values
    for candidate in REFLECTIVITY_CANDIDATES:
        if candidate in companion_fields:
            return candidate, companion_fields[candidate]
    if config.reflectivity_fallback_to_values:
        return quantity or None, values
    return None, None


def _candidates(mask: Any, values: Any) -> Any:
    np = require_numpy()
    return (np.asarray(mask) == 0) & np.isfinite(values)


def _masked_profile_values(values: Any, mask: Any) -> Any:
    np = require_numpy()
    profile_values = np.asarray(values, dtype="float32").copy()
    profile_values[np.asarray(mask) != 0] = np.nan
    return profile_values


def _rolling_nanmedian(values: Any, window_bins: int) -> Any:
    np = require_numpy()
    profile = np.asarray(values, dtype="float32")
    if profile.size == 0:
        return profile
    window = max(1, int(window_bins))
    if window % 2 == 0:
        window += 1
    if window == 1:
        return profile
    half = window // 2
    smoothed = np.full(profile.shape, np.nan, dtype="float32")
    for index in range(profile.size):
        left = max(0, index - half)
        right = min(profile.size, index + half + 1)
        segment = profile[left:right]
        if np.isfinite(segment).any():
            smoothed[index] = float(np.nanmedian(segment))
    return smoothed


def _fill_nan_profile(profile: Any) -> Any:
    np = require_numpy()
    values = np.asarray(profile, dtype="float32")
    if values.size == 0 or np.isfinite(values).all():
        return values
    valid = np.isfinite(values)
    if not valid.any():
        return np.zeros(values.shape, dtype="float32")
    indices = np.arange(values.size)
    return np.interp(indices, indices[valid], values[valid]).astype("float32")


def _estimated_noise_floor_profile(data: Any, percentile: float, window_bins: int) -> Any:
    np = require_numpy()
    values = np.asarray(data, dtype="float32")
    profile = np.full(values.shape[1], np.nan, dtype="float32")
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return profile
    global_min = float(np.nanmin(finite))
    for column in range(values.shape[1]):
        column_values = values[:, column]
        column_values = column_values[np.isfinite(column_values)]
        if column_values.size == 0:
            continue
        above_floor = column_values[column_values > global_min + 1.0e-3]
        if above_floor.size >= max(3, column_values.size // 20):
            column_values = above_floor
        profile[column] = float(np.nanpercentile(column_values, percentile))
    return _fill_nan_profile(_rolling_nanmedian(profile, window_bins))


def _local_texture_and_support(data: Any, support_db: float) -> tuple[Any, Any]:
    np = require_numpy()
    values = np.asarray(data, dtype="float32")
    if values.ndim != 2:
        return np.full(values.shape, np.nan, dtype="float32"), np.zeros(values.shape, dtype="int16")
    neighbours = _four_neighbour_arrays(values)
    diffs = []
    for neighbour in neighbours:
        difference = np.abs(values - neighbour)
        difference[~np.isfinite(values) | ~np.isfinite(neighbour)] = np.nan
        diffs.append(difference)
    stacked = np.stack(diffs)
    finite_count = np.isfinite(stacked).sum(axis=0)
    texture = _nanpercentile_small_stack(stacked, 75.0)
    texture[finite_count < 2] = np.nan
    similar = (np.isfinite(stacked) & (stacked <= float(support_db))).sum(axis=0).astype("int16")
    return texture.astype("float32"), similar


def _local_texture(values: Any | None, row: int, column: int, *, angular: bool = False) -> float | None:
    if values is None:
        return None
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    rows, columns = array.shape
    value = array[row, column]
    if not np.isfinite(value):
        return None
    differences: list[float] = []
    for neighbour_row, neighbour_column in (
        ((row - 1) % rows, column),
        ((row + 1) % rows, column),
        (row, max(0, column - 1)),
        (row, min(columns - 1, column + 1)),
    ):
        if neighbour_row == row and neighbour_column == column:
            continue
        neighbour = array[neighbour_row, neighbour_column]
        if not np.isfinite(neighbour):
            continue
        difference = abs(float(value) - float(neighbour))
        if angular and difference > 180.0:
            difference = 360.0 - (difference % 360.0)
        differences.append(difference)
    if len(differences) < 2:
        return None
    return float(np.nanpercentile(np.asarray(differences, dtype="float32"), 75))


def _similar_neighbour_count(values: Any, row: int, column: int, tolerance: float) -> int:
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    rows, columns = array.shape
    value = array[row, column]
    if not np.isfinite(value):
        return 0
    count = 0
    for neighbour_row, neighbour_column in (
        ((row - 1) % rows, column),
        ((row + 1) % rows, column),
        (row, max(0, column - 1)),
        (row, min(columns - 1, column + 1)),
    ):
        if neighbour_row == row and neighbour_column == column:
            continue
        neighbour = array[neighbour_row, neighbour_column]
        if np.isfinite(neighbour) and abs(float(neighbour) - float(value)) <= tolerance:
            count += 1
    return count


def _field(fields: dict[str, Any], candidates: tuple[str, ...]) -> Any | None:
    for candidate in candidates:
        if candidate in fields:
            return fields[candidate]
    return None


def _receiver_noise_mask(
    gate_values: Any,
    threshold: Any,
    companion_fields: dict[str, Any],
    config: QCConfig,
    *,
    base_candidates: Any,
) -> tuple[Any, dict[str, int]]:
    """Return only gates with converging evidence of incoherent receiver noise."""

    np = require_numpy()
    gates = np.asarray(gate_values, dtype="float32")
    base = np.asarray(base_candidates, dtype=bool) & np.isfinite(gates)
    empty = np.zeros(gates.shape, dtype=bool)
    ci = _field(companion_fields, CI_CANDIDATES)
    sqi = _field(companion_fields, SQI_CANDIDATES)
    evidence: dict[str, int] = {
        "receiver_noise_ci_available": int(ci is not None),
        "receiver_noise_sqi_available": int(sqi is not None),
        "receiver_noise_high_ci": 0,
        "receiver_noise_near_floor": 0,
        "receiver_noise_low_sqi": 0,
        "receiver_noise_bad_moment_candidates": 0,
        "receiver_noise_masked": 0,
        "atmospheric_or_unknown_protected": int(base.sum()),
    }
    if not config.ci_enabled or ci is None or sqi is None:
        return empty, evidence

    ci_array = np.asarray(ci, dtype="float32")
    sqi_array = np.asarray(sqi, dtype="float32")
    with np.errstate(invalid="ignore"):
        high_ci = base & np.isfinite(ci_array) & (ci_array >= config.ci_noise_min_db)
        near_floor = base & np.isfinite(threshold) & (gates <= threshold + config.receiver_noise_margin_db)
        low_sqi = base & np.isfinite(sqi_array) & (sqi_array <= config.receiver_noise_sqi_max)
    evidence["receiver_noise_high_ci"] = int(high_ci.sum())
    evidence["receiver_noise_near_floor"] = int(near_floor.sum())
    evidence["receiver_noise_low_sqi"] = int(low_sqi.sum())

    bad_moment_score = np.zeros(gates.shape, dtype="int16")
    phidp_texture = _local_texture_array(_field(companion_fields, PHIDP_CANDIDATES), angular=True)
    if phidp_texture is not None:
        bad_moment_score += (
            np.isfinite(phidp_texture) & (phidp_texture >= config.receiver_noise_phidp_texture_min_deg)
        ).astype("int16")

    velocity_texture = _local_texture_array(_field(companion_fields, VRAD_CANDIDATES))
    if velocity_texture is not None:
        bad_moment_score += (
            np.isfinite(velocity_texture) & (velocity_texture >= config.receiver_noise_velocity_texture_min_ms)
        ).astype("int16")

    rhohv = _field(companion_fields, RHOHV_CANDIDATES)
    if rhohv is not None:
        rhohv_array = np.asarray(rhohv, dtype="float32")
        bad_moment_score += (
            np.isfinite(rhohv_array) & (rhohv_array <= config.receiver_noise_rhohv_max)
        ).astype("int16")

    zdr = _field(companion_fields, ZDR_CANDIDATES)
    if zdr is not None:
        zdr_array = np.asarray(zdr, dtype="float32")
        bad_moment_score += (
            np.isfinite(zdr_array) & ((zdr_array <= config.zdr_min_db) | (zdr_array >= config.zdr_max_db))
        ).astype("int16")

    ambient_outlier = _ambient_noise_outlier(companion_fields, gates.shape, config.ambient_noise_ray_excess_db)
    if ambient_outlier is not None:
        bad_moment_score += ambient_outlier.astype("int16")

    candidate = high_ci & near_floor & low_sqi
    evidence["receiver_noise_bad_moment_candidates"] = int(
        (candidate & (bad_moment_score >= config.receiver_noise_min_bad_moments)).sum()
    )
    receiver_noise = candidate & (bad_moment_score >= config.receiver_noise_min_bad_moments)
    evidence["receiver_noise_masked"] = int(receiver_noise.sum())
    evidence["atmospheric_or_unknown_protected"] = int((base & ~receiver_noise).sum())
    return receiver_noise, evidence


def _ambient_noise_outlier(fields: dict[str, Any], shape: tuple[int, ...], excess_db: float) -> Any | None:
    np = require_numpy()
    combined = np.zeros(shape, dtype=bool)
    available = False
    for candidates in (AMBIENT_NOISE_H_CANDIDATES, AMBIENT_NOISE_V_CANDIDATES):
        values = _field(fields, candidates)
        if values is None:
            continue
        array = np.asarray(values, dtype="float32")
        finite_values = array[np.isfinite(array)]
        if finite_values.size == 0:
            continue
        median = float(np.nanmedian(finite_values))
        # UK short-pulse files use -32 dBc when no far-range estimate is available.
        if median <= -20.0:
            continue
        available = True
        combined |= np.isfinite(array) & (array >= median + float(excess_db))
    return combined if available else None


def _noise_metadata(metadata: Any | None, companion_fields: dict[str, Any], config: QCConfig) -> dict[str, Any]:
    np = require_numpy()
    attrs = getattr(metadata, "attrs", {}) if metadata is not None else {}
    if not isinstance(attrs, dict):
        attrs = {}
    receiver_h = attrs.get("uk_wsr:receiver_noise_figure_h_db")
    receiver_v = attrs.get("uk_wsr:receiver_noise_figure_v_db")
    payload: dict[str, Any] = {}
    if receiver_h is not None or receiver_v is not None:
        payload["receiver_noise_figure"] = {
            "h_db": float(receiver_h) if receiver_h is not None else None,
            "v_db": float(receiver_v) if receiver_v is not None else None,
            "role": "calibration_only",
            "usable_as_dbzh_floor": False,
        }

    long_range: dict[str, Any] = {}
    for label, candidates in (
        ("h", AMBIENT_NOISE_H_CANDIDATES),
        ("v", AMBIENT_NOISE_V_CANDIDATES),
    ):
        values = _field(companion_fields, candidates)
        if values is None:
            continue
        array = np.asarray(values, dtype="float32")
        if array.ndim == 2 and array.shape[1] > 0:
            array = array[:, 0]
        finite = array[np.isfinite(array)]
        if finite.size == 0:
            continue
        median = float(np.nanmedian(finite))
        available = median > -20.0
        long_range[label] = {
            "available": available,
            "unit": "dBc",
            "minimum": float(np.nanmin(finite)),
            "median": median,
            "maximum": float(np.nanmax(finite)),
            "outlier_ray_count": int((finite >= median + config.ambient_noise_ray_excess_db).sum()) if available else 0,
        }
    if long_range:
        payload["long_range_ambient_noise"] = long_range
    return payload


def _static_clutter_mask(gate_values: Any, companion_fields: dict[str, Any], config: QCConfig) -> Any:
    np = require_numpy()
    velocity = _field(companion_fields, VRAD_CANDIDATES)
    static = np.zeros(np.asarray(gate_values).shape, dtype=bool)
    if velocity is None:
        return static
    candidate = np.isfinite(gate_values) & np.isfinite(velocity) & (gate_values >= config.static_clutter_dbz_min) & (
        np.abs(velocity) <= config.static_clutter_vrad_abs_max_ms
    )
    if config.ci_enabled:
        ci = _field(companion_fields, CI_CANDIDATES)
        if ci is None:
            return static
        ci_array = np.asarray(ci, dtype="float32")
        candidate &= np.isfinite(ci_array) & (ci_array <= config.ci_clutter_max_db)
    return _neighbour_count_3x3(candidate) >= max(1, config.static_clutter_min_neighbors)


def _companion_quality_masks(
    gate_values: Any,
    threshold: Any,
    companion_fields: dict[str, Any],
    config: QCConfig,
    *,
    base_candidates: Any,
) -> tuple[Any, Any]:
    np = require_numpy()
    rows, columns = np.asarray(gate_values).shape
    dualpol_mask = np.zeros((rows, columns), dtype=bool)
    velocity_mask = np.zeros((rows, columns), dtype=bool)
    sqi = _field(companion_fields, SQI_CANDIDATES)
    rhohv = _field(companion_fields, RHOHV_CANDIDATES)
    zdr = _field(companion_fields, ZDR_CANDIDATES)
    phidp = _field(companion_fields, PHIDP_CANDIDATES)
    velocity = _field(companion_fields, VRAD_CANDIDATES)
    width = _field(companion_fields, WIDTH_CANDIDATES)

    base = np.asarray(base_candidates, dtype=bool) & np.isfinite(gate_values)
    with np.errstate(invalid="ignore"):
        near_noise_floor = base & np.isfinite(threshold) & (gate_values <= threshold + config.near_noise_margin_db)

    score = np.zeros((rows, columns), dtype="int16")
    dualpol_score = np.zeros((rows, columns), dtype="int16")
    velocity_score = np.zeros((rows, columns), dtype="int16")

    texture, similar = _local_texture_and_support(gate_values, support_db=config.texture_support_db)
    with np.errstate(invalid="ignore"):
        immediate_texture = (
            base
            & np.isfinite(texture)
            & (texture >= config.texture_threshold_db)
            & (similar <= config.texture_min_similar_neighbors)
            & np.isfinite(threshold)
            & (gate_values <= threshold + config.texture_near_margin_db)
            & (gate_values <= config.texture_max_dbz)
        )
        weak_texture = base & np.isfinite(texture) & (texture >= 18.0) & (similar <= 1)
    dualpol_mask |= immediate_texture
    score += weak_texture.astype("int16")
    dualpol_score += weak_texture.astype("int16")

    if sqi is not None:
        sqi_array = np.asarray(sqi, dtype="float32")
        finite = base & np.isfinite(sqi_array)
        strong = finite & (sqi_array < config.sqi_strong)
        medium = finite & ~strong & (sqi_array < config.sqi_medium)
        weak = finite & ~strong & ~medium & (sqi_array < config.sqi_weak)
        sqi_score = strong.astype("int16") * 3 + medium.astype("int16") * 2 + weak.astype("int16")
        score += sqi_score
        dualpol_score += sqi_score

    if rhohv is not None and config.rhohv_low_is_noise_evidence:
        rhohv_array = np.asarray(rhohv, dtype="float32")
        finite = base & np.isfinite(rhohv_array)
        strong = finite & (rhohv_array < config.rhohv_strong)
        weak = finite & ~strong & (rhohv_array < config.rhohv_weak)
        rhohv_score = strong.astype("int16") * 2 + weak.astype("int16")
        score += rhohv_score
        dualpol_score += rhohv_score

    if zdr is not None:
        zdr_array = np.asarray(zdr, dtype="float32")
        outlier = base & np.isfinite(zdr_array) & ((zdr_array < config.zdr_min_db) | (zdr_array > config.zdr_max_db))
        score += outlier.astype("int16")
        dualpol_score += outlier.astype("int16")

    phidp_texture = _local_texture_array(phidp, angular=True)
    if phidp_texture is not None:
        strong = base & np.isfinite(phidp_texture) & (phidp_texture > config.phidp_texture_strong_deg)
        medium = base & np.isfinite(phidp_texture) & ~strong & (phidp_texture > config.phidp_texture_medium_deg)
        phidp_score = strong.astype("int16") * 2 + medium.astype("int16")
        score += phidp_score
        dualpol_score += phidp_score

    velocity_texture = _local_texture_array(velocity)
    if velocity_texture is not None:
        strong = base & np.isfinite(velocity_texture) & (velocity_texture > config.velocity_texture_strong_ms)
        medium = base & np.isfinite(velocity_texture) & ~strong & (velocity_texture > config.velocity_texture_medium_ms)
        texture_score = strong.astype("int16") * 2 + medium.astype("int16")
        score += texture_score
        velocity_score += texture_score

    if width is not None:
        width_array = np.asarray(width, dtype="float32")
        wide = base & np.isfinite(width_array) & (width_array > config.spectrum_width_max_ms)
        score += wide.astype("int16")
        velocity_score += wide.astype("int16")

    if config.companion_qc_near_noise_only:
        suppress = near_noise_floor & (score >= config.near_noise_score_threshold)
    else:
        suppress = (near_noise_floor & (score >= config.near_noise_score_threshold)) | (score >= config.score_threshold)
    dualpol_mask |= suppress & (dualpol_score > 0)
    velocity_mask |= suppress & (velocity_score > 0)
    return dualpol_mask, velocity_mask


def _four_neighbour_arrays(values: Any) -> list[Any]:
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    up = np.roll(array, 1, axis=0)
    down = np.roll(array, -1, axis=0)
    left = np.full_like(array, np.nan)
    left[:, 1:] = array[:, :-1]
    right = np.full_like(array, np.nan)
    right[:, :-1] = array[:, 1:]
    return [up, down, left, right]


def _local_texture_array(values: Any | None, *, angular: bool = False) -> Any | None:
    np = require_numpy()
    if values is None:
        return None
    array = np.asarray(values, dtype="float32")
    if array.ndim != 2:
        return np.full(array.shape, np.nan, dtype="float32")
    diffs = []
    for neighbour in _four_neighbour_arrays(array):
        difference = np.abs(array - neighbour)
        if angular:
            difference = np.where(difference > 180.0, 360.0 - np.mod(difference, 360.0), difference)
        difference[~np.isfinite(array) | ~np.isfinite(neighbour)] = np.nan
        diffs.append(difference)
    stacked = np.stack(diffs)
    finite_count = np.isfinite(stacked).sum(axis=0)
    texture = _nanpercentile_small_stack(stacked, 75.0)
    texture[finite_count < 2] = np.nan
    return texture.astype("float32")


def _neighbour_count_3x3(candidate: Any) -> Any:
    np = require_numpy()
    base = np.asarray(candidate, dtype=bool)
    count = np.zeros(base.shape, dtype="int16")
    for row_offset in (-1, 0, 1):
        rows = np.roll(base, row_offset, axis=0)
        for column_offset in (-1, 0, 1):
            if column_offset == -1:
                shifted = np.zeros_like(base)
                shifted[:, :-1] = rows[:, 1:]
            elif column_offset == 1:
                shifted = np.zeros_like(base)
                shifted[:, 1:] = rows[:, :-1]
            else:
                shifted = rows
            count += shifted.astype("int16")
    return count


def _nanpercentile_small_stack(stack: Any, percentile: float) -> Any:
    np = require_numpy()
    values = np.asarray(stack, dtype="float32")
    finite = np.isfinite(values)
    count = finite.sum(axis=0)
    ordered = np.sort(np.where(finite, values, np.inf), axis=0)
    max_index = max(0, values.shape[0] - 1)
    position = (np.maximum(count, 1) - 1).astype("float32") * (float(percentile) / 100.0)
    lower_index = np.clip(np.floor(position).astype("int16"), 0, max_index)
    upper_index = np.clip(np.ceil(position).astype("int16"), 0, max_index)
    lower = np.take_along_axis(ordered, lower_index[np.newaxis, ...], axis=0)[0]
    upper = np.take_along_axis(ordered, upper_index[np.newaxis, ...], axis=0)[0]
    fraction = position - np.floor(position)
    with np.errstate(invalid="ignore"):
        result = lower + (upper - lower) * fraction
    result[count == 0] = np.nan
    return result.astype("float32")


def _value_at(values: Any | None, row: int, column: int) -> float | None:
    if values is None:
        return None
    np = require_numpy()
    value = np.asarray(values, dtype="float32")[row, column]
    return float(value) if np.isfinite(value) else None


def _json_profile(values: Any) -> list[float | None]:
    np = require_numpy()
    out: list[float | None] = []
    for value in np.asarray(values, dtype="float32").tolist():
        out.append(float(value) if np.isfinite(value) else None)
    return out


def _flag_counts(mask: Any) -> dict[str, int]:
    np = require_numpy()
    array = np.asarray(mask, dtype="uint16")
    return {flag.name: int((array & int(flag) != 0).sum()) for flag in QCMaskFlag}
