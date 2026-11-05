"""Shared API parameter and representation helpers."""

from __future__ import annotations

import os
import time as time_module
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from fastapi import HTTPException
from ..catalog import CatalogItem
from ..dependencies import require_numpy
from ..export import ExportRequest
from ..preview import _scale_to_uint8

PLOT_METADATA_DOWNLOAD_LIMIT_BYTES = 512 * 1024 * 1024
LOCAL_DOWNLOAD_LIMIT_BYTES = 256 * 1024 * 1024


class QCQueryParameters:
    """Advanced QC controls shared by all gate-reading API routes."""

    def __init__(
        self,
        qc_receiver_noise_enabled: bool | None = None,
        qc_receiver_noise_margin_db: float | None = None,
        qc_receiver_noise_sqi_max: float | None = None,
        qc_receiver_noise_rhohv_max: float | None = None,
        qc_receiver_noise_phidp_texture_min_deg: float | None = None,
        qc_receiver_noise_velocity_texture_min_ms: float | None = None,
        qc_receiver_noise_min_bad_moments: int | None = None,
        qc_ambient_noise_ray_excess_db: float | None = None,
        qc_ci_enabled: bool | None = None,
        qc_ci_noise_min_db: float | None = None,
        qc_ci_clutter_max_db: float | None = None,
        qc_background_current_vrad_abs_max_ms: float | None = None,
        qc_background_learned_low_ci_frequency_min: float | None = None,
        qc_background_require_current_ci: bool | None = None,
        qc_background_require_current_vrad: bool | None = None,
        qc_background_require_training_diversity: bool | None = None,
        qc_background_min_training_dates: int | None = None,
        qc_background_min_training_span_days: int | None = None,
    ) -> None:
        values = locals()
        self.filters = {
            key: value
            for key, value in values.items()
            if key != "self" and value is not None
        }


def _elapsed_ms(start: float) -> float:
    return round((time_module.perf_counter() - start) * 1000.0, 2)


def _safe_download_filename(filename: object, fallback: str = "uk-wsr-download") -> str:
    """Return a single safe filename for local desktop downloads."""

    name = Path(str(filename or fallback)).name.strip()
    if not name or name in {".", ".."}:
        name = fallback
    safe = "".join(
        char if char.isalnum() or char in " ._-" else "_" for char in name
    ).strip()
    return safe or fallback


def _desktop_download_dir() -> Path:
    configured = os.environ.get("UK_WSR_VISUALIZER_DOWNLOAD_DIR")
    target = Path(configured).expanduser() if configured else Path.home() / "Downloads"
    target.mkdir(parents=True, exist_ok=True)
    return target.resolve()


def _unique_download_path(directory: Path, filename: object) -> Path:
    safe = _safe_download_filename(filename)
    candidate = directory / safe
    if not candidate.exists():
        return candidate
    path = Path(safe)
    stem = path.stem or "uk-wsr-download"
    suffix = path.suffix
    for index in range(1, 10000):
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise HTTPException(
        status_code=409, detail="could not choose a unique download filename"
    )


def _download_payload(
    path: Path, source_filename: str | None = None
) -> dict[str, object]:
    return {
        "ok": True,
        "filename": path.name,
        "path": str(path),
        "bytes": path.stat().st_size,
        "source_filename": source_filename or path.name,
        "is_directory": path.is_dir(),
    }


def _download_date_label(date: str) -> str:
    text = str(date or "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _export_download_folder_name(job_id: str, request: ExportRequest) -> str:
    parts = [
        "UK WSR Visualizer",
        request.radar,
        _download_date_label(request.date),
        request.pulse,
        request.time,
        request.quantity,
        request.dataset,
        request.format,
    ]
    name = " ".join(str(part) for part in parts if part)
    return _safe_download_filename(name, fallback=f"uk-wsr-export-{job_id[:8]}")


@contextmanager
def _timed_step(steps: list[dict[str, object]], name: str):
    start = time_module.perf_counter()
    try:
        yield
    finally:
        steps.append({"name": name, "elapsed_ms": _elapsed_ms(start)})


def _item_payload(item: CatalogItem) -> dict[str, object]:
    return {
        **asdict(item),
        "quantity_records": [asdict(record) for record in item.quantity_records],
    }


def _raw_volume_item_has_files(item: CatalogItem) -> bool:
    return item.source_type == "raw_volume_day" and bool(item.raw_volumes)


def _quantity_display_config(
    quantity: str, requested_palette: str
) -> dict[str, object]:
    """Return default palette and scale choices for common radar variables."""

    normalized = quantity.strip()
    upper = normalized.upper()
    lower = normalized.lower()
    palette = (
        requested_palette if requested_palette not in {"", "auto", "standard"} else ""
    )
    limits: tuple[float | None, float | None] = (None, None)
    mask_below_min = False

    if (
        upper
        in {"DBZ", "DBZH", "DBZV", "DBZHC", "DBZVC", "TH", "TV", "CZ", "DZ", "AZ", "Z"}
        or "reflectivity" in lower
    ):
        palette = palette or "homeyer"
        limits = (-30.0, 75.0)
        mask_below_min = True
    elif (
        upper in {"VRAD", "VRADH", "VRADV", "VEL", "VELH", "VELV", "V"}
        or "velocity" in lower
    ):
        palette = palette or "BuDRd18"
        limits = (-30.0, 30.0)
    elif (
        upper in {"WRAD", "WRADH", "WRADV", "WIDTH", "SW", "SWRAD"}
        or "spectrum_width" in lower
    ):
        palette = palette or "NWS_SPW"
        limits = (0.0, 10.0)
    elif upper in {"ZDR", "ZDRH", "ZDRV"} or "differential_reflectivity" in lower:
        palette = palette or "RefDiff"
        limits = (-1.0, 8.0)
    elif upper in {"RHOHV", "RHO", "CC", "SQIH"} or "cross_correlation" in lower:
        palette = palette or "RefDiff"
        limits = (0.5, 1.05)
    elif upper in {"PHIDP", "UPHIDP", "PHI"} or "differential_phase" in lower:
        palette = palette or "Wild25"
        limits = (-180.0, 180.0)
    elif upper in {"KDP", "KDPH", "KDPV"} or "specific_differential_phase" in lower:
        palette = palette or "Theodore16"
        limits = (-2.0, 5.0)
    elif upper in {"RATE", "RRATE", "RATE_H", "RATE_Z", "R"} or "rain_rate" in lower:
        palette = palette or "RRate11"
        limits = (0.0, 50.0)
    elif upper in {"SNR", "SNRH", "SNRV"} or "signal_to_noise" in lower:
        palette = palette or "Carbone17"
        limits = (-20.0, 30.0)
    else:
        palette = palette or "gray"
    return {
        "palette": palette,
        "scale_min": limits[0],
        "scale_max": limits[1],
        "mask_below_min": mask_below_min,
    }


def _scale_to_uint8_with_limits(data, scale_min: float | None, scale_max: float | None):
    """Scale a numeric array to image bytes using optional display limits."""

    if scale_min is None or scale_max is None:
        return _scale_to_uint8(data)
    np = require_numpy()
    array = np.asarray(data, dtype=float)
    array = np.where(np.isfinite(array), array, np.nan)
    valid = array[np.isfinite(array)]
    if valid.size == 0:
        return np.zeros(array.shape, dtype=np.uint8), {
            "valid_min": None,
            "valid_max": None,
            "scale_min": float(scale_min),
            "scale_max": float(scale_max),
        }
    if scale_max <= scale_min:
        scale_max = scale_min + 1.0
    scaled = (array - scale_min) / (scale_max - scale_min)
    scaled = np.clip(scaled, 0, 1)
    scaled = np.where(np.isfinite(scaled), scaled, 0)
    return (scaled * 255).astype(np.uint8), {
        "valid_min": float(np.nanmin(valid)),
        "valid_max": float(np.nanmax(valid)),
        "scale_min": float(scale_min),
        "scale_max": float(scale_max),
    }
