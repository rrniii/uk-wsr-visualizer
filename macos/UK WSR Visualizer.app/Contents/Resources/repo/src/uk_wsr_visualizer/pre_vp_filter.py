"""In-memory pre-VP masking for UKMO NIMROD / BioDAR PVOL workflows.

The source HDF5 files are never modified by this module.  Masks are built from
decoded ODIM arrays and applied to in-memory field arrays immediately before a
vertical profile workflow consumes them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .dependencies import require_h5py, require_numpy
from .export_types import FieldSelection
from .geospatial import (
    _apply_odim_data_scaling,
    _attrs,
    _dataset_matches,
    _dataset_name_from_path,
    _estimated_noise_floor_profile,
    _quantity_from_group,
)

DBZH_ALIASES = ("DBZH", "DBZ", "TH", "DBZHC", "DBZVC")
VRAD_ALIASES = ("VRADH", "VRADDH", "VRAD", "VRADV", "VRADDV")
SQI_ALIASES = ("SQIH", "SQI")
NCP_ALIASES = ("NCPH", "NCP")
CI_ALIASES = ("CI",)


@dataclass(frozen=True)
class PreVpFilterSettings:
    """Resolved pre-VP filter settings."""

    preset: str = "current_ci_le4"
    enabled: bool = True
    label: str = "Recommended conservative mask: current + CI <= 4"
    sqi_threshold: float = 0.25
    ncp_threshold: float = 0.25
    noise_floor_quantile: float = 0.05
    noise_floor_margin_db: float = 3.0
    clutter_dbz_min: float = 5.0
    clutter_vrad_abs_max: float = 1.0
    clutter_persistence_min: float = 0.35
    clutter_min_gates: int = 20
    ci_enabled: bool = True
    ci_threshold: float = 4.0
    ci_bad_condition: str = "<="
    mask_action: str = "set_nan"


@dataclass(frozen=True)
class PreVpComponentDiagnostic:
    """Gate counts for a single mask component."""

    name: str
    available: bool
    masked_count: int = 0
    masked_fraction: float = 0.0
    message: str = ""


@dataclass(frozen=True)
class PreVpFilterDiagnostics:
    """Audit summary for a pre-VP mask run."""

    status: str
    preset: str
    label: str
    total_gates: int
    masked_gate_count: int
    masked_fraction: float
    finite_dbzh_before: int
    finite_dbzh_after: int
    fields_masked: list[str]
    settings: dict[str, Any]
    components: dict[str, dict[str, Any]]
    warnings: list[str]
    eta_retained_relative_to_baseline: float | None = None
    dens_retained_relative_to_baseline: float | None = None


@dataclass(frozen=True)
class PreVpFilterResult:
    """Masked in-memory fields and diagnostics."""

    fields: dict[str, Any]
    mask: Any
    diagnostics: PreVpFilterDiagnostics


PRE_VP_PRESETS: dict[str, PreVpFilterSettings] = {
    "off": PreVpFilterSettings(
        preset="off",
        enabled=False,
        label="Off / baseline",
        ci_enabled=False,
    ),
    "current_combined": PreVpFilterSettings(
        preset="current_combined",
        enabled=True,
        label="Current combined",
        ci_enabled=False,
    ),
    "current_ci_le4": PreVpFilterSettings(),
    "aggressive_ci_le4": PreVpFilterSettings(
        preset="aggressive_ci_le4",
        enabled=True,
        label="Aggressive sensitivity: CI <= 4",
        sqi_threshold=0.30,
        ncp_threshold=0.30,
        noise_floor_quantile=0.10,
        noise_floor_margin_db=4.0,
        clutter_persistence_min=0.30,
    ),
    "custom": PreVpFilterSettings(
        preset="custom",
        enabled=True,
        label="Custom",
    ),
}


def preset_payload() -> dict[str, Any]:
    """Return serialisable preset metadata for the desktop app."""

    return {
        "default": "current_ci_le4",
        "advanced_warning": "Validation found CI >= 6 or CI >= 7 too destructive for default production use.",
        "presets": {key: asdict(value) for key, value in PRE_VP_PRESETS.items()},
    }


def resolve_pre_vp_settings(
    preset: str | None = "current_ci_le4",
    *,
    enabled: bool | None = None,
    overrides: dict[str, Any] | None = None,
) -> PreVpFilterSettings:
    """Resolve a preset plus user overrides into concrete filter settings."""

    key = str(preset or "current_ci_le4")
    base = PRE_VP_PRESETS.get(key, PRE_VP_PRESETS["current_ci_le4"])
    data = asdict(base)
    data["preset"] = key if key in PRE_VP_PRESETS else "current_ci_le4"
    if enabled is not None:
        data["enabled"] = bool(enabled)
    for name, value in (overrides or {}).items():
        if value in ("", None):
            continue
        if name in data:
            data[name] = value
    data["sqi_threshold"] = _clamp_float(data["sqi_threshold"], 0.0, 1.0)
    data["ncp_threshold"] = _clamp_float(data["ncp_threshold"], 0.0, 1.0)
    data["noise_floor_quantile"] = _clamp_float(data["noise_floor_quantile"], 0.01, 0.20)
    data["noise_floor_margin_db"] = _clamp_float(data["noise_floor_margin_db"], 0.0, 10.0)
    data["clutter_dbz_min"] = _clamp_float(data["clutter_dbz_min"], -10.0, 30.0)
    data["clutter_vrad_abs_max"] = _clamp_float(data["clutter_vrad_abs_max"], 0.0, 3.0)
    data["clutter_persistence_min"] = _clamp_float(data["clutter_persistence_min"], 0.0, 1.0)
    data["clutter_min_gates"] = max(1, min(int(float(data["clutter_min_gates"])), 100))
    data["ci_threshold"] = _clamp_float(data["ci_threshold"], 0.0, 7.0)
    data["ci_bad_condition"] = ">=" if str(data["ci_bad_condition"]).strip() == ">=" else "<="
    data["ci_enabled"] = bool(data["ci_enabled"])
    data["enabled"] = bool(data["enabled"]) and data["preset"] != "off"
    data["mask_action"] = "set_nan"
    return PreVpFilterSettings(**data)


def _clamp_float(value: Any, lower: float, upper: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = lower
    return max(lower, min(parsed, upper))


def _component(name: str, available: bool, mask: Any | None, total_gates: int, message: str = "") -> PreVpComponentDiagnostic:
    np = require_numpy()
    count = int(np.asarray(mask, dtype=bool).sum()) if available and mask is not None else 0
    fraction = count / total_gates if total_gates else 0.0
    return PreVpComponentDiagnostic(name=name, available=available, masked_count=count, masked_fraction=fraction, message=message)


def _first_field(fields: dict[str, Any], aliases: tuple[str, ...]) -> tuple[str, Any] | tuple[None, None]:
    by_upper = {name.upper(): name for name in fields}
    for alias in aliases:
        actual = by_upper.get(alias)
        if actual is not None:
            return actual, fields[actual]
    return None, None


def _same_shape_fields(fields: dict[str, Any], shape: tuple[int, ...]) -> dict[str, Any]:
    return {name: values for name, values in fields.items() if getattr(values, "shape", None) == shape}


def apply_pre_vp_filter(fields: dict[str, Any], settings: PreVpFilterSettings | None = None) -> PreVpFilterResult:
    """Apply the resolved pre-VP mask to every same-shaped VP input field."""

    np = require_numpy()
    settings = settings or PRE_VP_PRESETS["current_ci_le4"]
    dbzh_name, dbzh = _first_field(fields, DBZH_ALIASES)
    if dbzh is None:
        raise ValueError("missing input: DBZH/DBZ/TH field is required for pre-VP masking")
    dbzh_array = np.asarray(dbzh, dtype="float32")
    if dbzh_array.ndim != 2:
        raise ValueError("missing input: DBZH field must be a two-dimensional polar sweep")
    total_gates = int(dbzh_array.size)
    same_shape = _same_shape_fields(fields, dbzh_array.shape)
    finite_before = int(np.isfinite(dbzh_array).sum())
    warnings: list[str] = []

    if not settings.enabled:
        empty = np.zeros(dbzh_array.shape, dtype=bool)
        return PreVpFilterResult(
            fields={name: np.asarray(values, dtype="float32").copy() for name, values in fields.items()},
            mask=empty,
            diagnostics=_diagnostics(
                "success",
                settings,
                total_gates,
                0,
                finite_before,
                finite_before,
                list(same_shape),
                {},
                warnings,
            ),
        )

    component_masks: dict[str, Any] = {}
    component_diagnostics: dict[str, PreVpComponentDiagnostic] = {}

    sqi_name, sqi = _first_field(fields, SQI_ALIASES)
    if sqi is None:
        warnings.append("SQI missing, skipped SQI component")
        component_diagnostics["sqi"] = _component("sqi", False, None, total_gates, "SQI missing, skipped SQI component")
    else:
        mask = np.isfinite(sqi) & (np.asarray(sqi, dtype="float32") < settings.sqi_threshold)
        component_masks["sqi"] = mask
        component_diagnostics["sqi"] = _component("sqi", True, mask, total_gates, f"{sqi_name} < {settings.sqi_threshold:g}")

    ncp_name, ncp = _first_field(fields, NCP_ALIASES)
    if ncp is None:
        warnings.append("NCP missing, skipped NCP component")
        component_diagnostics["ncp"] = _component("ncp", False, None, total_gates, "NCP missing, skipped NCP component")
    else:
        mask = np.isfinite(ncp) & (np.asarray(ncp, dtype="float32") < settings.ncp_threshold)
        component_masks["ncp"] = mask
        component_diagnostics["ncp"] = _component("ncp", True, mask, total_gates, f"{ncp_name} < {settings.ncp_threshold:g}")

    floor = _estimated_noise_floor_profile(dbzh_array, settings.noise_floor_quantile * 100.0, 11)
    noise_threshold = floor[np.newaxis, :] + settings.noise_floor_margin_db
    noise_mask = np.isfinite(dbzh_array) & (dbzh_array <= noise_threshold)
    component_masks["noise_floor"] = noise_mask
    component_diagnostics["noise_floor"] = _component(
        "noise_floor",
        True,
        noise_mask,
        total_gates,
        f"estimated {settings.noise_floor_quantile:g} quantile + {settings.noise_floor_margin_db:g} dB",
    )

    vrad_name, vrad = _first_field(fields, VRAD_ALIASES)
    if vrad is None:
        warnings.append("VRAD missing, skipped static clutter component")
        component_diagnostics["static_clutter"] = _component(
            "static_clutter",
            False,
            None,
            total_gates,
            "VRAD missing, skipped static clutter component",
        )
    else:
        vrad_array = np.asarray(vrad, dtype="float32")
        candidate = (
            np.isfinite(dbzh_array)
            & np.isfinite(vrad_array)
            & (dbzh_array >= settings.clutter_dbz_min)
            & (np.abs(vrad_array) <= settings.clutter_vrad_abs_max)
        )
        gate_counts = candidate.sum(axis=0)
        persistence = gate_counts / max(candidate.shape[0], 1)
        persistent_range = (persistence >= settings.clutter_persistence_min) & (gate_counts >= settings.clutter_min_gates)
        mask = candidate & persistent_range[np.newaxis, :]
        component_masks["static_clutter"] = mask
        component_diagnostics["static_clutter"] = _component(
            "static_clutter",
            True,
            mask,
            total_gates,
            f"DBZH >= {settings.clutter_dbz_min:g} and |{vrad_name}| <= {settings.clutter_vrad_abs_max:g}",
        )

    ci_name, ci = _first_field(fields, CI_ALIASES)
    if not settings.ci_enabled:
        component_diagnostics["ci"] = _component("ci", False, None, total_gates, "CI disabled for this preset")
    elif ci is None:
        warnings.append("CI missing, skipped CI component")
        component_diagnostics["ci"] = _component("ci", False, None, total_gates, "CI missing, skipped CI component")
    else:
        ci_array = np.asarray(ci, dtype="float32")
        if settings.ci_bad_condition == ">=":
            mask = np.isfinite(ci_array) & (ci_array >= settings.ci_threshold)
            if settings.ci_threshold >= 6:
                warnings.append("Validation found this setting too destructive for default production use.")
        else:
            mask = np.isfinite(ci_array) & (ci_array <= settings.ci_threshold)
        component_masks["ci"] = mask
        component_diagnostics["ci"] = _component("ci", True, mask, total_gates, f"{ci_name} {settings.ci_bad_condition} {settings.ci_threshold:g}")

    combined = np.zeros(dbzh_array.shape, dtype=bool)
    for mask in component_masks.values():
        combined |= np.asarray(mask, dtype=bool)

    masked_fields: dict[str, Any] = {}
    for name, values in fields.items():
        array = np.asarray(values, dtype="float32").copy()
        if array.shape == combined.shape:
            array[combined] = np.nan
        masked_fields[name] = array
    finite_after = int(np.isfinite(masked_fields[str(dbzh_name)]).sum())
    masked_count = int(combined.sum())
    return PreVpFilterResult(
        fields=masked_fields,
        mask=combined,
        diagnostics=_diagnostics(
            "success",
            settings,
            total_gates,
            masked_count,
            finite_before,
            finite_after,
            list(same_shape),
            component_diagnostics,
            warnings,
        ),
    )


def _diagnostics(
    status: str,
    settings: PreVpFilterSettings,
    total_gates: int,
    masked_count: int,
    finite_before: int,
    finite_after: int,
    fields_masked: list[str],
    components: dict[str, PreVpComponentDiagnostic],
    warnings: list[str],
) -> PreVpFilterDiagnostics:
    return PreVpFilterDiagnostics(
        status=status,
        preset=settings.preset,
        label=settings.label,
        total_gates=total_gates,
        masked_gate_count=masked_count,
        masked_fraction=masked_count / total_gates if total_gates else 0.0,
        finite_dbzh_before=finite_before,
        finite_dbzh_after=finite_after,
        fields_masked=sorted(fields_masked),
        settings=asdict(settings),
        components={key: asdict(value) for key, value in components.items()},
        warnings=warnings,
    )


def load_sweep_fields(source: Path, selection: FieldSelection) -> tuple[dict[str, Any], dict[str, Any]]:
    """Decode all ODIM data/quality fields for one sweep/dataset."""

    h5py = require_h5py()
    with h5py.File(source, "r") as h5:
        dataset_name = _resolve_dataset_name(h5, selection)
        if "/" in dataset_name:
            dataset_group = h5[dataset_name]
        elif selection.pulse and selection.time and selection.pulse in h5 and selection.time in h5[selection.pulse]:
            dataset_group = h5[f"{selection.pulse}/{selection.time}/{dataset_name}"]
        else:
            dataset_group = h5[dataset_name]
        fields: dict[str, Any] = {}
        groups: dict[str, str] = {}
        for name, group in dataset_group.items():
            if not (str(name).startswith("data") or str(name).startswith("quality")):
                continue
            if not hasattr(group, "get") or "data" not in group:
                continue
            quantity = _quantity_from_group(group)
            if not quantity:
                continue
            fields[quantity] = _apply_odim_data_scaling(group["data"][()], _attrs(group.get("what")))
            groups[quantity] = str(name)
        metadata = {
            "dataset": dataset_group.name.strip("/").split("/")[-1],
            "dataset_path": dataset_group.name,
            "field_groups": groups,
            "quantities": sorted(fields),
        }
        return fields, metadata


def _resolve_dataset_name(h5: Any, selection: FieldSelection) -> str:
    if selection.dataset:
        wanted = selection.dataset if str(selection.dataset).startswith("dataset") else f"dataset{selection.dataset}"
        if wanted in h5:
            return wanted
        path = f"{selection.pulse}/{selection.time}/{wanted}"
        if selection.pulse and selection.time and path in h5:
            return path
    candidates: list[str] = []
    if selection.pulse and selection.time and selection.pulse in h5 and selection.time in h5[selection.pulse]:
        prefix = f"{selection.pulse}/{selection.time}/"
        candidates = [prefix + name for name in h5[f"{selection.pulse}/{selection.time}"] if str(name).startswith("dataset")]
    else:
        candidates = [name for name in h5 if str(name).startswith("dataset")]
    for candidate in sorted(candidates):
        dataset_name = _dataset_name_from_path(candidate)
        if _dataset_matches(dataset_name, selection.dataset):
            return candidate
    raise ValueError(
        f"missing input: no dataset found for pulse={selection.pulse}, time={selection.time}, dataset={selection.dataset or 'auto'}"
    )


def preview_filter_results(fields: dict[str, Any], settings: PreVpFilterSettings | None = None) -> dict[str, PreVpFilterResult]:
    """Return raw/current/recommended/aggressive mask results for the preview UI."""

    return {
        "raw": apply_pre_vp_filter(fields, PRE_VP_PRESETS["off"]),
        "current_combined": apply_pre_vp_filter(fields, PRE_VP_PRESETS["current_combined"]),
        "current_ci_le4": apply_pre_vp_filter(fields, PRE_VP_PRESETS["current_ci_le4"]),
        "aggressive_ci_le4": apply_pre_vp_filter(fields, PRE_VP_PRESETS["aggressive_ci_le4"]),
        "selected": apply_pre_vp_filter(fields, settings or PRE_VP_PRESETS["current_ci_le4"]),
    }
