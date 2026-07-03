"""Canonical gate-level QC masks for UK WSR polar fields."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntFlag
from typing import Any

from .dependencies import require_numpy

QC_VERSION = "qc-v1"


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


REFLECTIVITY_QUANTITIES = {"DBZ", "DBZH", "DBZV", "DBZHC", "DBZVC", "TH", "TV", "CZ", "DZ", "AZ", "Z"}
REFLECTIVITY_CANDIDATES = ("DBZH", "TH", "DBZ", "DBZV", "DBZHC", "DBZVC", "CZ", "DZ", "AZ", "Z")
SQI_CANDIDATES = ("SQIH", "SQI", "QIND")
RHOHV_CANDIDATES = ("RHOHV", "RHO", "CC")
ZDR_CANDIDATES = ("ZDR", "ZDRH", "ZDRV")
PHIDP_CANDIDATES = ("PHIDP", "UPHIDP", "PHI")
VRAD_CANDIDATES = ("VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH", "VELV")
WIDTH_CANDIDATES = ("WRADH", "WRAD", "WRADV", "WIDTH", "SW", "SWRAD")
COMPANION_FIELD_CANDIDATES = tuple(
    dict.fromkeys(
        REFLECTIVITY_CANDIDATES
        + SQI_CANDIDATES
        + RHOHV_CANDIDATES
        + ZDR_CANDIDATES
        + PHIDP_CANDIDATES
        + VRAD_CANDIDATES
        + WIDTH_CANDIDATES
    )
)


@dataclass(frozen=True)
class QCConfig:
    """Configuration for the canonical gate-mask builder."""

    mode: str = "off"
    operation: str = "mask"
    noise_floor_enabled: bool = False
    noise_floor_method: str = "estimated"
    noise_floor_margin_db: float = 3.0
    noise_floor_percentile: float = 10.0
    noise_floor_window_bins: int = 11
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
    static_clutter_enabled: bool = False
    static_clutter_dbz_min: float = 5.0
    static_clutter_vrad_abs_max_ms: float = 1.0
    static_clutter_min_neighbors: int = 3
    reflectivity_fallback_to_values: bool = True

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
            "config": self.config.to_dict(),
        }
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
    noise_enabled = _filter_bool(filters, "noise_floor_enabled") or mode not in {"", "off", "none"}
    companion_enabled = _filter_bool(filters, "qc_companion_enabled") or mode in {"vp_standard", "vp_strict"}
    static_enabled = _filter_bool(filters, "qc_static_clutter_enabled") or mode in {"vp_standard", "vp_strict"}
    if mode in {"", "none"}:
        mode = "off"
    if _filter_bool(filters, "noise_floor_enabled") and mode == "off":
        mode = "display_standard"
    margin = _filter_float(filters, "noise_floor_margin_db")
    if margin is None:
        margin = 6.0 if mode == "vp_standard" else 10.0 if mode == "vp_strict" else 3.0
    percentile = _filter_float(filters, "noise_floor_percentile")
    window_bins = _filter_float(filters, "noise_floor_window_bins")
    return QCConfig(
        mode=mode,
        operation=_filter_text(filters, "noise_floor_operation", "mask") if noise_enabled else "none",
        noise_floor_enabled=noise_enabled,
        noise_floor_method="estimated",
        noise_floor_margin_db=float(margin),
        noise_floor_percentile=10.0 if percentile is None else max(0.0, min(100.0, float(percentile))),
        noise_floor_window_bins=11 if window_bins is None else max(1, int(window_bins)),
        texture_enabled=True if "noise_floor_texture_enabled" not in filters else _filter_bool(filters, "noise_floor_texture_enabled"),
        texture_threshold_db=_filter_default(filters, "noise_floor_texture_db", 10.0, min_value=0.0),
        texture_near_margin_db=_filter_default(filters, "noise_floor_texture_near_margin_db", 20.0, min_value=0.0),
        texture_support_db=_filter_default(filters, "noise_floor_texture_support_db", 6.0, min_value=0.0),
        texture_max_dbz=_filter_default(filters, "noise_floor_texture_max_db", 30.0),
        texture_min_similar_neighbors=max(
            0, int(_filter_default(filters, "noise_floor_texture_min_similar_neighbors", 1.0))
        ),
        companion_qc_enabled=companion_enabled,
        static_clutter_enabled=static_enabled,
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

    if config.noise_floor_enabled and gate_values is not None:
        profile = _estimated_noise_floor_profile(
            _masked_profile_values(gate_values, mask),
            config.noise_floor_percentile,
            config.noise_floor_window_bins,
        )
        floor_profile = _json_profile(profile)
        threshold = np.broadcast_to(profile[np.newaxis, :] + config.noise_floor_margin_db, gate_values.shape)
        candidates = _candidates(mask, output) & np.isfinite(gate_values) & np.isfinite(threshold)
        floor_mask = candidates & (gate_values <= threshold)
        mask[floor_mask] |= int(QCMaskFlag.NOISE_FLOOR)

        if config.static_clutter_enabled:
            static_mask = _static_clutter_mask(gate_values, companion_arrays, config)
            mask[_candidates(mask, output) & static_mask] |= int(QCMaskFlag.STATIC_CLUTTER)

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
    rows, columns = values.shape
    texture = np.full(values.shape, np.nan, dtype="float32")
    similar = np.zeros(values.shape, dtype="int16")
    for row in range(rows):
        for column in range(columns):
            value = values[row, column]
            if not np.isfinite(value):
                continue
            differences: list[float] = []
            for neighbour_row, neighbour_column in (
                ((row - 1) % rows, column),
                ((row + 1) % rows, column),
                (row, column - 1),
                (row, column + 1),
            ):
                if neighbour_column < 0 or neighbour_column >= columns:
                    continue
                neighbour = values[neighbour_row, neighbour_column]
                if not np.isfinite(neighbour):
                    continue
                difference = abs(float(value) - float(neighbour))
                differences.append(difference)
                if difference <= support_db:
                    similar[row, column] += 1
            if len(differences) >= 2:
                texture[row, column] = float(np.nanpercentile(np.asarray(differences, dtype="float32"), 75))
    return texture, similar


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


def _static_clutter_mask(gate_values: Any, companion_fields: dict[str, Any], config: QCConfig) -> Any:
    np = require_numpy()
    velocity = _field(companion_fields, VRAD_CANDIDATES)
    static = np.zeros(np.asarray(gate_values).shape, dtype=bool)
    if velocity is None:
        return static
    rows, columns = static.shape
    candidate = np.isfinite(gate_values) & np.isfinite(velocity) & (gate_values >= config.static_clutter_dbz_min) & (
        np.abs(velocity) <= config.static_clutter_vrad_abs_max_ms
    )
    for row in range(rows):
        for column in range(columns):
            count = 0
            for row_offset in (-1, 0, 1):
                neighbour_row = (row + row_offset) % rows
                for column_offset in (-1, 0, 1):
                    neighbour_column = column + column_offset
                    if 0 <= neighbour_column < columns and candidate[neighbour_row, neighbour_column]:
                        count += 1
            static[row, column] = count >= max(1, config.static_clutter_min_neighbors)
    return static


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

    for row in range(rows):
        for column in range(columns):
            if not base_candidates[row, column] or not np.isfinite(gate_values[row, column]):
                continue
            dbzh = float(gate_values[row, column])
            floor_threshold = float(threshold[row, column])
            near_noise_floor = dbzh <= floor_threshold + config.near_noise_margin_db if np.isfinite(floor_threshold) else False
            score = 0
            dualpol_score = 0
            velocity_score = 0

            texture = _local_texture(gate_values, row, column)
            similar = _similar_neighbour_count(gate_values, row, column, tolerance=config.texture_support_db)
            if texture is not None:
                if texture >= config.texture_threshold_db and similar <= config.texture_min_similar_neighbors and dbzh <= min(
                    floor_threshold + config.texture_near_margin_db, config.texture_max_dbz
                ):
                    dualpol_mask[row, column] = True
                    continue
                if texture >= 18.0 and similar <= 1:
                    score += 1
                    dualpol_score += 1

            value = _value_at(sqi, row, column)
            if value is not None:
                if value < config.sqi_strong:
                    score += 3
                    dualpol_score += 3
                elif value < config.sqi_medium:
                    score += 2
                    dualpol_score += 2
                elif value < config.sqi_weak:
                    score += 1
                    dualpol_score += 1

            value = _value_at(rhohv, row, column)
            if value is not None:
                if value < config.rhohv_strong:
                    score += 2
                    dualpol_score += 2
                elif value < config.rhohv_weak:
                    score += 1
                    dualpol_score += 1

            value = _value_at(zdr, row, column)
            if value is not None and (value < config.zdr_min_db or value > config.zdr_max_db):
                score += 1
                dualpol_score += 1

            phidp_texture = _local_texture(phidp, row, column, angular=True)
            if phidp_texture is not None:
                if phidp_texture > config.phidp_texture_strong_deg:
                    score += 2
                    dualpol_score += 2
                elif phidp_texture > config.phidp_texture_medium_deg:
                    score += 1
                    dualpol_score += 1

            velocity_texture = _local_texture(velocity, row, column)
            if velocity_texture is not None:
                if velocity_texture > config.velocity_texture_strong_ms:
                    score += 2
                    velocity_score += 2
                elif velocity_texture > config.velocity_texture_medium_ms:
                    score += 1
                    velocity_score += 1

            value = _value_at(width, row, column)
            if value is not None and value > config.spectrum_width_max_ms:
                score += 1
                velocity_score += 1

            suppress = (near_noise_floor and score >= config.near_noise_score_threshold) or score >= config.score_threshold
            if suppress and dualpol_score:
                dualpol_mask[row, column] = True
            if suppress and velocity_score:
                velocity_mask[row, column] = True
    return dualpol_mask, velocity_mask


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
