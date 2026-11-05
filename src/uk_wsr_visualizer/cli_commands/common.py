"""Shared CLI settings and filter arguments."""

from __future__ import annotations

import argparse
from pathlib import Path
from ..config import Settings


def _settings(args: argparse.Namespace) -> Settings:
    base = Settings.from_env()
    catalog_path = (
        Path(args.catalog) if getattr(args, "catalog", None) else base.catalog_path
    )
    data_dir = catalog_path.parent

    def arg_path(name: str, default: Path) -> Path:
        value = getattr(args, name, None)
        return Path(value) if value is not None else default

    def arg_value(name: str, default: str) -> str:
        value = getattr(args, name, None)
        return str(value) if value is not None else default

    return Settings(
        aggregate_base=arg_path("aggregate_base", base.aggregate_base),
        data_dir=data_dir,
        catalog_path=catalog_path,
        preview_dir=arg_path("preview_dir", base.preview_dir),
        tile_dir=arg_path("tile_dir", base.tile_dir),
        export_dir=arg_path("export_dir", base.export_dir),
        session_dir=arg_path("session_dir", base.session_dir),
        object_store_manifest_path=arg_path(
            "object_store_manifest", base.object_store_manifest_path
        ),
        object_store_external_base=arg_value(
            "object_store_base", base.object_store_external_base
        ),
        object_store_internal_base=base.object_store_internal_base,
    )


def _filter_args(args: argparse.Namespace) -> dict[str, object]:
    names = (
        "min_range_km",
        "max_range_km",
        "min_azimuth_deg",
        "max_azimuth_deg",
        "min_value",
        "max_value",
        "cappi_height_m",
        "qc_mode",
        "noise_floor_enabled",
        "noise_floor_method",
        "noise_floor_margin_db",
        "noise_floor_operation",
        "noise_floor_percentile",
        "noise_floor_window_bins",
        "qc_receiver_noise_enabled",
        "qc_receiver_noise_margin_db",
        "qc_receiver_noise_min_bad_moments",
        "qc_ci_enabled",
        "qc_ci_noise_min_db",
        "qc_ci_clutter_max_db",
        "noise_floor_texture_enabled",
        "noise_floor_texture_db",
        "noise_floor_texture_near_margin_db",
        "noise_floor_texture_support_db",
        "noise_floor_texture_max_db",
        "noise_floor_texture_min_similar_neighbors",
        "qc_companion_enabled",
        "qc_static_clutter_enabled",
        "qc_background_model_enabled",
        "qc_background_model_path",
        "qc_background_persistent_frequency_min",
        "qc_background_min_samples",
        "qc_background_static_vrad_frequency_min",
        "qc_background_low_sqi_frequency_min",
        "qc_background_dbzh_excess_max_db",
        "qc_background_evidence_score_threshold",
        "qc_background_current_vrad_abs_max_ms",
        "qc_background_require_training_diversity",
        "qc_background_min_training_dates",
        "qc_background_min_training_span_days",
    )
    filters = {
        name: getattr(args, name)
        for name in names
        if getattr(args, name, None) is not None
    }
    if getattr(args, "palette_stops", None):
        filters["palette_stops"] = args.palette_stops
    return filters


def _split_csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return list(default)
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return parts or list(default)


def _add_filter_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--min-range-km", dest="min_range_km", type=float)
    parser.add_argument("--max-range-km", dest="max_range_km", type=float)
    parser.add_argument("--min-azimuth-deg", dest="min_azimuth_deg", type=float)
    parser.add_argument("--max-azimuth-deg", dest="max_azimuth_deg", type=float)
    parser.add_argument("--min-value", dest="min_value", type=float)
    parser.add_argument("--max-value", dest="max_value", type=float)
    parser.add_argument("--cappi-height-m", dest="cappi_height_m", type=float)
    parser.add_argument("--palette-stops", dest="palette_stops")
    parser.add_argument(
        "--qc-mode",
        dest="qc_mode",
        choices=(
            "off",
            "display_standard",
            "signal_preserving",
            "vp_standard",
            "vp_strict",
        ),
    )
    parser.add_argument(
        "--noise-floor-enabled",
        dest="noise_floor_enabled",
        action="store_true",
        default=None,
    )
    parser.add_argument("--noise-floor-method", dest="noise_floor_method", default=None)
    parser.add_argument(
        "--noise-floor-margin-db", dest="noise_floor_margin_db", type=float
    )
    parser.add_argument(
        "--noise-floor-operation",
        dest="noise_floor_operation",
        choices=("mask",),
        default=None,
    )
    parser.add_argument(
        "--noise-floor-percentile", dest="noise_floor_percentile", type=float
    )
    parser.add_argument(
        "--noise-floor-window-bins", dest="noise_floor_window_bins", type=int
    )
    parser.add_argument(
        "--qc-receiver-noise-enabled",
        dest="qc_receiver_noise_enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--qc-receiver-noise-margin-db", dest="qc_receiver_noise_margin_db", type=float
    )
    parser.add_argument(
        "--qc-receiver-noise-min-bad-moments",
        dest="qc_receiver_noise_min_bad_moments",
        type=int,
    )
    parser.add_argument(
        "--qc-ci-enabled",
        dest="qc_ci_enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--qc-ci-noise-min-db", dest="qc_ci_noise_min_db", type=float)
    parser.add_argument(
        "--qc-ci-clutter-max-db", dest="qc_ci_clutter_max_db", type=float
    )
    parser.add_argument(
        "--noise-floor-texture-enabled",
        dest="noise_floor_texture_enabled",
        action="store_true",
        default=None,
    )
    parser.add_argument(
        "--noise-floor-texture-db", dest="noise_floor_texture_db", type=float
    )
    parser.add_argument(
        "--noise-floor-texture-near-margin-db",
        dest="noise_floor_texture_near_margin_db",
        type=float,
    )
    parser.add_argument(
        "--noise-floor-texture-support-db",
        dest="noise_floor_texture_support_db",
        type=float,
    )
    parser.add_argument(
        "--noise-floor-texture-max-db", dest="noise_floor_texture_max_db", type=float
    )
    parser.add_argument(
        "--noise-floor-texture-min-similar-neighbors",
        dest="noise_floor_texture_min_similar_neighbors",
        type=int,
    )
    parser.add_argument(
        "--qc-companion-enabled",
        dest="qc_companion_enabled",
        action="store_true",
        default=None,
    )
    parser.add_argument(
        "--qc-static-clutter-enabled",
        dest="qc_static_clutter_enabled",
        action="store_true",
        default=None,
    )
    parser.add_argument(
        "--qc-background-model-enabled",
        dest="qc_background_model_enabled",
        action="store_true",
        default=None,
    )
    parser.add_argument("--qc-background-model", dest="qc_background_model_path")
    parser.add_argument(
        "--qc-background-persistent-frequency-min",
        dest="qc_background_persistent_frequency_min",
        type=float,
    )
    parser.add_argument(
        "--qc-background-min-samples", dest="qc_background_min_samples", type=int
    )
    parser.add_argument(
        "--qc-background-static-vrad-frequency-min",
        dest="qc_background_static_vrad_frequency_min",
        type=float,
    )
    parser.add_argument(
        "--qc-background-low-sqi-frequency-min",
        dest="qc_background_low_sqi_frequency_min",
        type=float,
    )
    parser.add_argument(
        "--qc-background-dbzh-excess-max-db",
        dest="qc_background_dbzh_excess_max_db",
        type=float,
    )
    parser.add_argument(
        "--qc-background-evidence-score-threshold",
        dest="qc_background_evidence_score_threshold",
        type=int,
    )
    parser.add_argument(
        "--qc-background-current-vrad-abs-max-ms",
        dest="qc_background_current_vrad_abs_max_ms",
        type=float,
    )
    parser.add_argument(
        "--qc-background-require-training-diversity",
        dest="qc_background_require_training_diversity",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--qc-background-min-training-dates",
        dest="qc_background_min_training_dates",
        type=int,
    )
    parser.add_argument(
        "--qc-background-min-training-span-days",
        dest="qc_background_min_training_span_days",
        type=int,
    )
