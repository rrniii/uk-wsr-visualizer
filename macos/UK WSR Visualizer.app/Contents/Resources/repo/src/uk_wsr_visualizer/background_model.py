"""Learned background/clutter statistics for UK WSR polar fields."""

from __future__ import annotations

import hashlib
import json
import warnings
from base64 import b64decode, b64encode
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .background_registry import (
    BACKGROUND_MODEL_QC_VERSION,
    eligible_registry_entries,
    load_background_model_registry,
)
from .dependencies import require_numpy

BACKGROUND_MODEL_SCHEMA = "uk_wsr_background_model"
BACKGROUND_MODEL_SCHEMA_VERSION = 1

REFLECTIVITY_CANDIDATES = ("DBZH", "TH", "DBZ", "DBZV", "DBZHC", "DBZVC", "CZ", "DZ", "AZ", "Z")
SQI_CANDIDATES = ("SQIH", "SQI", "QIND")
RHOHV_CANDIDATES = ("RHOHV", "RHO", "CC")
ZDR_CANDIDATES = ("ZDR", "ZDRH", "ZDRV")
VRAD_CANDIDATES = ("VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH", "VELV")
CI_CANDIDATES = ("CI", "APD", "CLUTTER_INDICATOR")

BACKGROUND_MODEL_ARRAY_NAMES = (
    "sample_count",
    "persistent_echo_frequency",
    "dbzh_p10",
    "dbzh_median",
    "dbzh_p90",
    "vrad_sample_count",
    "near_zero_vrad_frequency",
    "sqi_sample_count",
    "low_sqi_frequency",
    "rhohv_sample_count",
    "low_rhohv_frequency",
    "unstable_rhohv_frequency",
    "zdr_sample_count",
    "zdr_outlier_frequency",
    "unstable_zdr_frequency",
    "ci_sample_count",
    "low_ci_frequency",
    "high_ci_frequency",
)

DEFAULT_BACKGROUND_MODEL_MANIFEST = "manifest.json"


@dataclass(frozen=True)
class BackgroundModelBuildConfig:
    """Thresholds used when learning the persistent gate statistics."""

    echo_threshold_dbz: float = 0.0
    vrad_abs_max_ms: float = 1.0
    sqi_low: float = 0.45
    rhohv_low: float = 0.75
    rhohv_texture_threshold: float = 0.15
    zdr_min_db: float = -3.0
    zdr_max_db: float = 8.0
    zdr_texture_threshold_db: float = 2.0
    ci_low_max_db: float = 2.0
    ci_high_min_db: float = 6.0


@dataclass(frozen=True)
class BackgroundScan:
    """One polar scan plus optional companion fields used to learn a model."""

    values: Any
    metadata: Any | None = None
    companion_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BackgroundModel:
    """Portable learned background statistics for one radar/elevation/pulse/quantity grid."""

    key: dict[str, Any]
    shape: tuple[int, int]
    arrays: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    path: str | None = None
    array_hash: str | None = None

    def to_manifest(self, *, npz_path: Path | None = None) -> dict[str, Any]:
        np = require_numpy()
        arrays = {
            name: {
                "dtype": str(np.asarray(values).dtype),
                "shape": list(np.asarray(values).shape),
            }
            for name, values in sorted(self.arrays.items())
        }
        inline_arrays = {
            name: {
                "dtype": "float32",
                "shape": list(np.asarray(values).shape),
                "encoding": "base64",
                "byte_order": "little",
                "data": b64encode(_float32_array(values).astype("<f4", copy=False).tobytes(order="C")).decode("ascii"),
            }
            for name, values in sorted(self.arrays.items())
        }
        return {
            "schema": BACKGROUND_MODEL_SCHEMA,
            "schema_version": BACKGROUND_MODEL_SCHEMA_VERSION,
            "generated_at": self.metadata.get("generated_at")
            or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "key": dict(self.key),
            "shape": list(self.shape),
            "arrays": arrays,
            "inline_arrays": inline_arrays,
            "array_hash": self.array_hash or hash_arrays(self.arrays),
            "metadata": dict(self.metadata),
            "npz_path": npz_path.name if npz_path is not None else None,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "schema": BACKGROUND_MODEL_SCHEMA,
            "schema_version": BACKGROUND_MODEL_SCHEMA_VERSION,
            "key": dict(self.key),
            "shape": list(self.shape),
            "array_hash": self.array_hash or hash_arrays(self.arrays),
            "path": self.path,
            "source_count": self.metadata.get("source_count"),
            "source_date_count": self.metadata.get("source_date_count"),
            "training_span_days": self.metadata.get("training_span_days"),
        }


@dataclass(frozen=True)
class BackgroundModelApplication:
    """Result of applying a learned background model to one scan."""

    mask: Any
    model: dict[str, Any]
    evidence_counts: dict[str, int]
    qualified: bool = True
    reason: str | None = None


def background_key_from_metadata(metadata: Any | None, *, quantity: str | None = None) -> dict[str, Any]:
    """Build the stable key used to select a learned background model."""

    if metadata is None:
        return {"quantity": _normalise_quantity(quantity)}
    key = {
        "radar": getattr(metadata, "radar", None),
        "pulse": getattr(metadata, "pulse", None),
        "quantity": _normalise_quantity(quantity or getattr(metadata, "quantity", None)),
        "elevation_deg": _rounded(getattr(metadata, "elevation_deg", None), digits=3),
        "rstart_km": _rounded(getattr(metadata, "rstart_km", None), digits=6),
        "rscale_m": _rounded(getattr(metadata, "rscale_m", None), digits=6),
        "azimuth_rays": getattr(metadata, "nrays", None),
        "range_bins": getattr(metadata, "nbins", None),
    }
    return {name: value for name, value in key.items() if value not in ("", None)}


def build_background_model(
    scans: list[BackgroundScan],
    *,
    key: dict[str, Any] | None = None,
    config: BackgroundModelBuildConfig | None = None,
) -> BackgroundModel:
    """Learn polar azimuth x range background statistics from repeated scans."""

    if not scans:
        raise ValueError("at least one scan is required to build a background model")
    np = require_numpy()
    config = config or BackgroundModelBuildConfig()

    normalised: list[tuple[Any, dict[str, Any], Any | None]] = []
    shape: tuple[int, int] | None = None
    for scan in scans:
        values = np.asarray(scan.values, dtype="float32")
        if values.ndim != 2:
            raise ValueError("background model scans must be two-dimensional polar arrays")
        if shape is None:
            shape = tuple(values.shape)
        elif tuple(values.shape) != shape:
            raise ValueError(f"scan shape {values.shape} does not match first scan shape {shape}")
        normalised.append((values, _normalise_companion_fields(scan.companion_fields, tuple(values.shape)), scan.metadata))

    assert shape is not None
    stack = np.stack([values for values, _, _ in normalised]).astype("float32")
    finite = np.isfinite(stack)
    sample_count = finite.sum(axis=0).astype("float32")
    echo_count = (finite & (stack >= config.echo_threshold_dbz)).sum(axis=0).astype("float32")
    persistent_frequency = _safe_frequency(echo_count, sample_count)
    percentiles = _nanpercentiles(stack, (10.0, 50.0, 90.0))

    rows, columns = shape
    accumulator = _Accumulator.zeros((rows, columns))
    for values, companions, _ in normalised:
        velocity = _field(companions, VRAD_CANDIDATES)
        if velocity is not None:
            finite_velocity = np.isfinite(velocity)
            accumulator.vrad_sample_count += finite_velocity
            accumulator.near_zero_vrad_count += finite_velocity & (np.abs(velocity) <= config.vrad_abs_max_ms)

        sqi = _field(companions, SQI_CANDIDATES)
        if sqi is not None:
            finite_sqi = np.isfinite(sqi)
            accumulator.sqi_sample_count += finite_sqi
            accumulator.low_sqi_count += finite_sqi & (sqi < config.sqi_low)

        rhohv = _field(companions, RHOHV_CANDIDATES)
        if rhohv is not None:
            finite_rhohv = np.isfinite(rhohv)
            accumulator.rhohv_sample_count += finite_rhohv
            accumulator.low_rhohv_count += finite_rhohv & (rhohv < config.rhohv_low)
            rhohv_texture = local_texture_array(rhohv)
            accumulator.unstable_rhohv_count += finite_rhohv & np.isfinite(rhohv_texture) & (
                rhohv_texture >= config.rhohv_texture_threshold
            )

        zdr = _field(companions, ZDR_CANDIDATES)
        if zdr is not None:
            finite_zdr = np.isfinite(zdr)
            accumulator.zdr_sample_count += finite_zdr
            accumulator.zdr_outlier_count += finite_zdr & ((zdr < config.zdr_min_db) | (zdr > config.zdr_max_db))
            zdr_texture = local_texture_array(zdr)
            accumulator.unstable_zdr_count += finite_zdr & np.isfinite(zdr_texture) & (
                zdr_texture >= config.zdr_texture_threshold_db
            )

        ci = _field(companions, CI_CANDIDATES)
        if ci is not None:
            finite_ci = np.isfinite(ci)
            accumulator.ci_sample_count += finite_ci
            accumulator.low_ci_count += finite_ci & (ci <= config.ci_low_max_db)
            accumulator.high_ci_count += finite_ci & (ci >= config.ci_high_min_db)

    arrays = {
        "sample_count": sample_count,
        "persistent_echo_frequency": persistent_frequency,
        "dbzh_p10": percentiles[0],
        "dbzh_median": percentiles[1],
        "dbzh_p90": percentiles[2],
        "vrad_sample_count": accumulator.vrad_sample_count.astype("float32"),
        "near_zero_vrad_frequency": _safe_frequency(accumulator.near_zero_vrad_count, accumulator.vrad_sample_count),
        "sqi_sample_count": accumulator.sqi_sample_count.astype("float32"),
        "low_sqi_frequency": _safe_frequency(accumulator.low_sqi_count, accumulator.sqi_sample_count),
        "rhohv_sample_count": accumulator.rhohv_sample_count.astype("float32"),
        "low_rhohv_frequency": _safe_frequency(accumulator.low_rhohv_count, accumulator.rhohv_sample_count),
        "unstable_rhohv_frequency": _safe_frequency(accumulator.unstable_rhohv_count, accumulator.rhohv_sample_count),
        "zdr_sample_count": accumulator.zdr_sample_count.astype("float32"),
        "zdr_outlier_frequency": _safe_frequency(accumulator.zdr_outlier_count, accumulator.zdr_sample_count),
        "unstable_zdr_frequency": _safe_frequency(accumulator.unstable_zdr_count, accumulator.zdr_sample_count),
        "ci_sample_count": accumulator.ci_sample_count.astype("float32"),
        "low_ci_frequency": _safe_frequency(accumulator.low_ci_count, accumulator.ci_sample_count),
        "high_ci_frequency": _safe_frequency(accumulator.high_ci_count, accumulator.ci_sample_count),
    }
    first_metadata = next((metadata for _, _, metadata in normalised if metadata is not None), None)
    model_key = key or background_key_from_metadata(first_metadata)
    source_dates = sorted(
        {
            str(getattr(metadata, "date", "") or "")
            for _, _, metadata in normalised
            if metadata is not None and getattr(metadata, "date", None)
        }
    )
    training_span_days = _date_span_days(source_dates)
    metadata = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "qc_version": BACKGROUND_MODEL_QC_VERSION,
        "source_count": len(scans),
        "source_dates": source_dates,
        "source_date_count": len(source_dates),
        "source_start_date": source_dates[0] if source_dates else None,
        "source_end_date": source_dates[-1] if source_dates else None,
        "training_span_days": training_span_days,
        "build_config": asdict(config),
    }
    if first_metadata is not None:
        metadata["first_source"] = {
            "date": getattr(first_metadata, "date", None),
            "time": getattr(first_metadata, "time", None),
            "dataset": getattr(first_metadata, "dataset", None),
        }
    return BackgroundModel(key=model_key, shape=shape, arrays=arrays, metadata=metadata, array_hash=hash_arrays(arrays))


def save_background_model(model: BackgroundModel, output: str | Path) -> tuple[Path, Path]:
    """Save a learned model as compressed arrays plus a JSON manifest."""

    np = require_numpy()
    output_path = Path(output)
    if output_path.suffix == ".json":
        json_path = output_path
        npz_path = output_path.with_suffix(".npz")
    elif output_path.suffix == ".npz":
        npz_path = output_path
        json_path = output_path.with_suffix(".json")
    else:
        npz_path = output_path.with_suffix(".npz")
        json_path = output_path.with_suffix(".json")
    npz_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(npz_path, **{name: _float32_array(values) for name, values in model.arrays.items()})
    manifest = model.to_manifest(npz_path=npz_path)
    json_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return npz_path, json_path


def load_background_model(path: str | Path) -> BackgroundModel:
    """Load a learned model from its .npz arrays or JSON manifest."""

    np = require_numpy()
    source = Path(path)
    manifest: dict[str, Any] = {}
    if source.suffix == ".json":
        manifest = json.loads(source.read_text(encoding="utf-8"))
        npz_name = manifest.get("npz_path") or source.with_suffix(".npz").name
        npz_path = Path(npz_name)
        if not npz_path.is_absolute():
            npz_path = source.parent / npz_path
    else:
        npz_path = source
        json_path = source.with_suffix(".json")
        if json_path.exists():
            manifest = json.loads(json_path.read_text(encoding="utf-8"))

    if npz_path.exists():
        with np.load(npz_path) as loaded:
            arrays = {name: loaded[name].astype("float32") for name in loaded.files}
    else:
        arrays = _inline_arrays_from_manifest(manifest)
    if "sample_count" not in arrays:
        raise ValueError(f"{npz_path} is not a background model artifact")
    shape = tuple(int(value) for value in arrays["sample_count"].shape)
    key = dict(manifest.get("key") or {})
    metadata = dict(manifest.get("metadata") or {})
    return BackgroundModel(
        key=key,
        shape=shape,  # type: ignore[arg-type]
        arrays=arrays,
        metadata=metadata,
        path=str(npz_path),
        array_hash=manifest.get("array_hash") or hash_arrays(arrays),
    )


def default_background_model_path(
    metadata: Any | None,
    *,
    quantity: str | None = None,
    model_dir: str | Path | None = None,
) -> Path | None:
    """Return the packaged default model that matches the scan metadata, if any."""

    if metadata is None:
        return None
    resolved_model_dir = (
        Path(model_dir)
        if model_dir is not None
        else Path(__file__).resolve().parent / "models" / "background"
    )
    for candidate in _default_background_model_candidates(resolved_model_dir):
        if not _default_model_matches(candidate, metadata, quantity=quantity):
            continue
        path = _safe_default_model_path(resolved_model_dir, str(candidate["filename"]))
        if path is not None and path.exists():
            return path
    return None


def apply_background_model(
    model: BackgroundModel,
    gate_values: Any,
    companion_fields: dict[str, Any] | None,
    config: Any,
) -> BackgroundModelApplication:
    """Score gates against a learned background model and return a clutter mask."""

    np = require_numpy()
    gates = np.asarray(gate_values, dtype="float32")
    if gates.shape != model.shape:
        raise ValueError(f"gate shape {gates.shape} does not match background model shape {model.shape}")
    companions = _normalise_companion_fields(companion_fields or {}, model.shape)

    qualified, qualification_reason = background_model_qualification(model, config)
    if not qualified:
        return BackgroundModelApplication(
            mask=np.zeros(gates.shape, dtype=bool),
            model=model.summary(),
            evidence_counts={"model_qualified": 0, "masked": 0},
            qualified=False,
            reason=qualification_reason,
        )

    sample_count = _array(model, "sample_count")
    persistent = _array(model, "persistent_echo_frequency")
    p90 = _array(model, "dbzh_p90")
    min_samples = int(getattr(config, "background_min_samples", 20))
    persistent_min = float(getattr(config, "background_persistent_frequency_min", 0.60))
    static_frequency_min = float(getattr(config, "background_static_vrad_frequency_min", 0.40))
    dbzh_excess_max = float(getattr(config, "background_dbzh_excess_max_db", 8.0))
    score_threshold = int(getattr(config, "background_evidence_score_threshold", 2))
    current_velocity_abs_max = float(getattr(config, "background_current_vrad_abs_max_ms", 0.50))
    learned_low_ci_min = float(getattr(config, "background_learned_low_ci_frequency_min", 0.60))
    ci_max = float(getattr(config, "ci_clutter_max_db", 2.0))
    require_current_ci = bool(getattr(config, "background_require_current_ci", True))
    require_current_vrad = bool(getattr(config, "background_require_current_vrad", True))

    dbzh_guard = np.isfinite(p90) & (gates <= p90 + dbzh_excess_max)
    base = (
        np.isfinite(gates)
        & np.isfinite(sample_count)
        & (sample_count >= min_samples)
        & np.isfinite(persistent)
        & (persistent >= persistent_min)
        & dbzh_guard
    )
    evidence_counts: dict[str, int] = {
        "model_qualified": 1,
        "learned_persistent": int(base.sum()),
        "learned_static_vrad": 0,
        "current_static_vrad": 0,
        "learned_low_ci": 0,
        "current_low_ci": 0,
        "missing_required_ci": 0,
        "missing_required_vrad": 0,
    }

    learned_static = _array(model, "near_zero_vrad_frequency") >= static_frequency_min
    evidence_counts["learned_static_vrad"] = int((base & learned_static).sum())
    base &= learned_static

    learned_ci_samples = _array(model, "ci_sample_count")
    if np.any(learned_ci_samples > 0):
        learned_low_ci = (learned_ci_samples >= min_samples) & (
            _array(model, "low_ci_frequency") >= learned_low_ci_min
        )
        evidence_counts["learned_low_ci"] = int((base & learned_low_ci).sum())
        base &= learned_low_ci

    velocity = _field(companions, VRAD_CANDIDATES)
    if velocity is not None:
        current_static = np.isfinite(velocity) & (np.abs(velocity) <= current_velocity_abs_max)
        evidence_counts["current_static_vrad"] = int((base & current_static).sum())
        if require_current_vrad:
            base &= current_static
    elif require_current_vrad:
        evidence_counts["missing_required_vrad"] = int(base.sum())
        base &= False

    ci = _field(companions, CI_CANDIDATES)
    if ci is not None:
        current_low_ci = np.isfinite(ci) & (ci <= ci_max)
        evidence_counts["current_low_ci"] = int((base & current_low_ci).sum())
        if require_current_ci:
            base &= current_low_ci
    elif require_current_ci:
        evidence_counts["missing_required_ci"] = int(base.sum())
        base &= False

    if require_current_ci or require_current_vrad:
        mask = base
    else:
        score = learned_static.astype("int16")
        if velocity is not None:
            score += (np.isfinite(velocity) & (np.abs(velocity) <= current_velocity_abs_max)).astype("int16")
        if ci is not None:
            score += (np.isfinite(ci) & (ci <= ci_max)).astype("int16")
        mask = base & (score >= score_threshold)
    evidence_counts["masked"] = int(mask.sum())
    return BackgroundModelApplication(mask=mask, model=model.summary(), evidence_counts=evidence_counts)


def background_model_qualification(model: BackgroundModel, config: Any) -> tuple[bool, str | None]:
    """Require multi-date training before a learned map is allowed to remove gates."""

    if not bool(getattr(config, "background_require_training_diversity", True)):
        return True, None
    minimum_dates = int(getattr(config, "background_min_training_dates", 7))
    minimum_span = int(getattr(config, "background_min_training_span_days", 14))
    try:
        date_count = int(model.metadata.get("source_date_count") or 0)
        span_days = int(model.metadata.get("training_span_days") or 0)
    except (TypeError, ValueError):
        return False, "invalid_training_diversity_metadata"
    if date_count == 0 and isinstance(model.metadata.get("first_source"), dict):
        date_count = int(bool(model.metadata["first_source"].get("date")))
    if date_count < minimum_dates:
        return False, f"insufficient_training_dates:{date_count}<{minimum_dates}"
    if span_days < minimum_span:
        return False, f"insufficient_training_span_days:{span_days}<{minimum_span}"
    return True, None


def local_texture_array(values: Any | None, *, angular: bool = False) -> Any:
    """Compute 4-neighbour p75 texture for a whole polar array."""

    np = require_numpy()
    if values is None:
        return None
    array = np.asarray(values, dtype="float32")
    if array.ndim != 2:
        return np.full(array.shape, np.nan, dtype="float32")
    rows, columns = array.shape
    neighbours = []
    up = np.roll(array, 1, axis=0)
    down = np.roll(array, -1, axis=0)
    neighbours.extend([up, down])
    left = np.full_like(array, np.nan)
    left[:, 1:] = array[:, :-1]
    right = np.full_like(array, np.nan)
    right[:, :-1] = array[:, 1:]
    neighbours.extend([left, right])
    diffs = []
    for neighbour in neighbours:
        difference = np.abs(array - neighbour)
        if angular:
            difference = np.where(difference > 180.0, 360.0 - np.mod(difference, 360.0), difference)
        difference[~np.isfinite(array) | ~np.isfinite(neighbour)] = np.nan
        diffs.append(difference)
    stacked = np.stack(diffs)
    finite_count = np.isfinite(stacked).sum(axis=0)
    texture = _nanpercentile_small_stack(stacked, 75.0)
    texture[finite_count < 2] = np.nan
    if rows == 0 or columns == 0:
        return np.full(array.shape, np.nan, dtype="float32")
    return texture


@dataclass
class _Accumulator:
    vrad_sample_count: Any
    near_zero_vrad_count: Any
    sqi_sample_count: Any
    low_sqi_count: Any
    rhohv_sample_count: Any
    low_rhohv_count: Any
    unstable_rhohv_count: Any
    zdr_sample_count: Any
    zdr_outlier_count: Any
    unstable_zdr_count: Any
    ci_sample_count: Any
    low_ci_count: Any
    high_ci_count: Any

    @classmethod
    def zeros(cls, shape: tuple[int, int]) -> "_Accumulator":
        np = require_numpy()
        return cls(**{name: np.zeros(shape, dtype="float32") for name in cls.__dataclass_fields__})


def _safe_frequency(count: Any, sample_count: Any) -> Any:
    np = require_numpy()
    count_array = np.asarray(count, dtype="float32")
    sample_array = np.asarray(sample_count, dtype="float32")
    frequency = np.zeros(count_array.shape, dtype="float32")
    np.divide(count_array, sample_array, out=frequency, where=sample_array > 0)
    return frequency


def _nanpercentiles(stack: Any, percentiles: tuple[float, ...]) -> list[Any]:
    np = require_numpy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        result = np.nanpercentile(np.asarray(stack, dtype="float32"), percentiles, axis=0).astype("float32")
    return [result[index] for index in range(len(percentiles))]


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


def _normalise_quantity(quantity: str | None) -> str:
    return str(quantity or "").strip().upper()


def _normalise_companion_fields(fields: dict[str, Any], shape: tuple[int, int]) -> dict[str, Any]:
    np = require_numpy()
    out: dict[str, Any] = {}
    for quantity, values in fields.items():
        array = np.asarray(values, dtype="float32")
        if tuple(array.shape) == tuple(shape):
            out[_normalise_quantity(quantity)] = array
    return out


def _field(fields: dict[str, Any], candidates: tuple[str, ...]) -> Any | None:
    for candidate in candidates:
        value = fields.get(candidate)
        if value is not None:
            return value
    return None


def _default_background_model_candidates(model_dir: Path) -> tuple[dict[str, Any], ...]:
    manifest_path = model_dir / DEFAULT_BACKGROUND_MODEL_MANIFEST
    return eligible_registry_entries(load_background_model_registry(manifest_path))


def _safe_default_model_path(model_dir: Path, filename: str) -> Path | None:
    root = model_dir.resolve()
    candidate = (model_dir / filename).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _default_model_matches(candidate: dict[str, Any], metadata: Any, *, quantity: str | None) -> bool:
    actual_radar = _metadata_text(metadata, "radar").lower()
    actual_pulse = _metadata_text(metadata, "pulse").lower()
    actual_dataset = _normalise_dataset(_metadata_text(metadata, "dataset"))
    actual_quantity = _normalise_quantity(quantity or _metadata_text(metadata, "quantity"))
    actual_elevation = _metadata_float(metadata, "elevation_deg")

    if actual_radar != str(candidate.get("radar", "")).lower():
        return False
    if actual_pulse != str(candidate.get("pulse", "")).lower():
        return False
    if actual_quantity != _normalise_quantity(str(candidate.get("quantity", ""))):
        return False
    if actual_dataset != _normalise_dataset(str(candidate.get("dataset", ""))):
        return False
    expected_elevation = float(candidate.get("elevation_deg", "nan"))
    return actual_elevation is not None and abs(actual_elevation - expected_elevation) <= 0.05


def _metadata_text(metadata: Any, name: str) -> str:
    if isinstance(metadata, dict):
        value = metadata.get(name)
    else:
        value = getattr(metadata, name, None)
    return str(value or "").strip()


def _metadata_float(metadata: Any, name: str) -> float | None:
    if isinstance(metadata, dict):
        value = metadata.get(name)
    else:
        value = getattr(metadata, name, None)
    if value in ("", None):
        return None
    return float(value)


def _normalise_dataset(dataset: str) -> str:
    text = str(dataset or "").strip().lower()
    if text and text.isdigit():
        return f"dataset{text}"
    return text


def _array(model: BackgroundModel, name: str) -> Any:
    np = require_numpy()
    value = model.arrays.get(name)
    if value is None:
        return np.zeros(model.shape, dtype="float32")
    return np.asarray(value, dtype="float32")


def _float32_array(values: Any) -> Any:
    np = require_numpy()
    return np.asarray(values, dtype="float32")


def _inline_arrays_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    np = require_numpy()
    arrays: dict[str, Any] = {}
    inline = manifest.get("inline_arrays") or {}
    if not isinstance(inline, dict):
        return arrays
    for name, payload in inline.items():
        if not isinstance(payload, dict) or payload.get("encoding") != "base64":
            continue
        shape = tuple(int(value) for value in payload.get("shape", []))
        data = b64decode(str(payload.get("data", "")))
        dtype = str(payload.get("dtype") or "float32").lower()
        if dtype in {"float32", "<f4", "f4"}:
            array = np.frombuffer(data, dtype="<f4").astype("float32").reshape(shape)
        elif dtype == "uint8":
            array = np.frombuffer(data, dtype=np.uint8).astype("float32").reshape(shape)
            array = _decode_scaled_inline_array(array, payload)
        elif dtype in {"uint16", "<u2", "u2"}:
            array = np.frombuffer(data, dtype="<u2").astype("float32").reshape(shape)
            array = _decode_scaled_inline_array(array, payload)
        elif dtype in {"int16", "<i2", "i2"}:
            raw = np.frombuffer(data, dtype="<i2").reshape(shape)
            sentinel = payload.get("nan_sentinel")
            missing = raw == int(sentinel) if sentinel is not None else np.zeros(shape, dtype=bool)
            array = _decode_scaled_inline_array(raw.astype("float32"), payload)
            array[missing] = np.nan
        else:
            continue
        arrays[str(name)] = array
    return arrays


def _decode_scaled_inline_array(values: Any, payload: dict[str, Any]) -> Any:
    np = require_numpy()
    scale = float(payload.get("scale", 1.0))
    offset = float(payload.get("offset", 0.0))
    return np.asarray(values, dtype="float32") * scale + offset


def _rounded(value: Any, *, digits: int) -> float | None:
    if value in ("", None):
        return None
    return round(float(value), digits)


def _date_span_days(source_dates: list[str]) -> int:
    if len(source_dates) < 2:
        return 0
    parsed = []
    for value in source_dates:
        text = str(value).replace("-", "")
        try:
            parsed.append(datetime.strptime(text, "%Y%m%d").date())
        except ValueError:
            continue
    if len(parsed) < 2:
        return 0
    return (max(parsed) - min(parsed)).days


def hash_arrays(arrays: dict[str, Any]) -> str:
    """Hash model arrays in a deterministic order."""

    np = require_numpy()
    hasher = hashlib.sha256()
    for name in sorted(arrays):
        array = np.ascontiguousarray(np.asarray(arrays[name], dtype="float32"))
        hasher.update(name.encode("utf-8"))
        hasher.update(str(array.shape).encode("ascii"))
        hasher.update(array.tobytes())
    return hasher.hexdigest()
