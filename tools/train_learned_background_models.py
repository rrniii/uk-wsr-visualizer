#!/usr/bin/env python3
"""Train and validate learned background models from public UKMO PVOL files."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from uk_wsr_visualizer.background_model import (
    BackgroundModel,
    BackgroundModelBuildConfig,
    BackgroundScan,
    apply_background_model,
    background_model_qualification,
    build_background_model,
    encode_quantized_background_array,
    hash_arrays,
)
from uk_wsr_visualizer.background_registry import (
    BACKGROUND_MODEL_QC_VERSION,
    audit_background_model_registry,
)
from uk_wsr_visualizer.geospatial import FieldSelection, read_polar_field_with_companions
from uk_wsr_visualizer.qc import QCConfig, QCMaskFlag

PUBLIC_BASE = "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public"
ROOT_CATALOG_URL = f"{PUBLIC_BASE}/ukmo-nimrod/catalog/pvol/catalog.json"
DEFAULT_PULSES = ("lp", "sp")
RUNTIME_BACKGROUND_ARRAY_NAMES = (
    "sample_count",
    "persistent_echo_frequency",
    "dbzh_p90",
    "near_zero_vrad_frequency",
    "low_ci_vrad_sample_count",
    "low_ci_near_zero_vrad_frequency",
    "low_sqi_frequency",
    "low_rhohv_frequency",
    "unstable_rhohv_frequency",
    "zdr_outlier_frequency",
    "unstable_zdr_frequency",
    "ci_sample_count",
    "low_ci_sample_count",
    "low_ci_frequency",
    "high_ci_frequency",
    "low_ci_persistent_echo_frequency",
)


@dataclass(frozen=True)
class ModelTarget:
    dataset: str
    elevation_deg: float | None
    shape: tuple[int, int]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-catalog", type=Path, default=Path("/tmp/uk_wsr_pvol_catalog.json"))
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/uk_wsr_background_all_radars"))
    parser.add_argument("--date", help="YYYYMMDD. Defaults to each radar's latest catalog date.")
    parser.add_argument("--radar", action="append", help="Radar slug to process. Repeatable. Defaults to all.")
    parser.add_argument(
        "--pulse",
        dest="pulses",
        action="append",
        help="Pulse to process. Repeat for multiple pulses. Defaults to lp and sp.",
    )
    parser.add_argument("--quantity", default="DBZH")
    parser.add_argument(
        "--dataset",
        dest="datasets",
        action="append",
        help="Dataset/sweep to process, e.g. dataset1 or 1. Repeatable. Defaults to all DBZH sweeps.",
    )
    parser.add_argument("--start-time", default="1200", help="Prefer scans at or after HHMM for the split.")
    parser.add_argument("--train-count", type=int, default=50)
    parser.add_argument("--validation-count", type=int, default=20)
    parser.add_argument(
        "--package-dir",
        type=Path,
        default=Path("src/uk_wsr_visualizer/models/background"),
        help="Directory for packaged desktop background-model JSON and manifest outputs.",
    )
    parser.add_argument(
        "--ios-dir",
        type=Path,
        default=Path("ios/UKWSRVisualizer/BackgroundModels"),
        help="Directory for iOS-bundled background-model JSON outputs.",
    )
    parser.add_argument(
        "--report-root",
        type=Path,
        default=Path("reports/learned_background_validation_all_radars_all_sweeps"),
    )
    parser.add_argument(
        "--compact-output",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write compact runtime JSON models containing only arrays used by desktop/iOS masking.",
    )
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    args = parser.parse_args()

    ensure_root_catalog(args.root_catalog)
    root = json.loads(args.root_catalog.read_text(encoding="utf-8"))
    wanted = set(args.radar or [])
    radars = [radar for radar in root.get("radars", []) if not wanted or radar.get("radar") in wanted]
    if not radars:
        raise SystemExit("no radars matched")

    package_dir = args.package_dir
    ios_dir = args.ios_dir
    report_root = args.report_root
    package_dir.mkdir(parents=True, exist_ok=True)
    ios_dir.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    pulses = tuple(args.pulses or DEFAULT_PULSES)
    for radar_info in radars:
        radar = str(radar_info["radar"])
        date = args.date or str(radar_info["last_date"])
        for pulse in pulses:
            try:
                pulse_summaries = process_radar_pulse(
                    radar=radar,
                    date=date,
                    pulse=pulse,
                    quantity=args.quantity,
                    requested_datasets=args.datasets,
                    start_time=args.start_time,
                    train_count=args.train_count,
                    validation_count=args.validation_count,
                    cache_dir=args.cache_dir,
                    package_dir=package_dir,
                    ios_dir=ios_dir,
                    report_root=report_root,
                    skip_existing=args.skip_existing,
                    compact_output=args.compact_output,
                )
                summaries.extend(pulse_summaries)
                for summary in pulse_summaries:
                    print(
                        json.dumps(
                            {
                                "radar": radar,
                                "pulse": summary["pulse"],
                                "dataset": summary["dataset"],
                                "elevation_deg": summary["model_key"].get("elevation_deg"),
                                "status": summary["status"],
                                "validation_file_count": summary.get("validation_file_count"),
                                "mean_masked_percent": round(
                                    100.0 * summary.get("aggregate", {}).get("background_masked_fraction_mean", 0.0),
                                    2,
                                ),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
            except Exception as exc:  # noqa: BLE001 - batch mode records per-target failures.
                error = {"radar": radar, "date": date, "pulse": pulse, "error": f"{type(exc).__name__}: {exc}"}
                errors.append(error)
                print(json.dumps(error, sort_keys=True), flush=True)
                if not args.keep_going:
                    raise

    write_model_manifest(package_dir, summaries)
    write_all_radar_report(report_root, summaries, errors)
    return 1 if errors else 0


def ensure_root_catalog(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    download(ROOT_CATALOG_URL, path)


def process_radar_pulse(
    *,
    radar: str,
    date: str,
    pulse: str,
    quantity: str,
    requested_datasets: list[str] | None,
    start_time: str,
    train_count: int,
    validation_count: int,
    cache_dir: Path,
    package_dir: Path,
    ios_dir: Path,
    report_root: Path,
    skip_existing: bool,
    compact_output: bool,
) -> list[dict[str, Any]]:
    day_catalog = load_day_catalog(radar, date, cache_dir)
    selected = select_files(day_catalog, pulse=pulse, start_time=start_time, total=train_count + validation_count)
    effective_train_count = train_count
    if len(selected) < train_count + validation_count:
        effective_train_count = len(selected) - validation_count
    train_entries = selected[:effective_train_count]
    validation_entries = selected[effective_train_count : effective_train_count + validation_count]
    if len(train_entries) < 20 or len(validation_entries) < validation_count:
        raise ValueError(
            f"{radar} {date} has {len(train_entries)} train and {len(validation_entries)} validation files; "
            f"wanted at least 20/{validation_count}"
        )

    radar_cache = cache_dir / radar / date / pulse
    radar_cache.mkdir(parents=True, exist_ok=True)
    for entry in selected:
        download(entry["object_url"], radar_cache / entry["filename"], expected_size=entry.get("size_bytes"))

    targets = discover_model_targets(
        radar_cache / selected[0]["filename"],
        quantity=quantity,
        requested_datasets=requested_datasets,
    )
    if not targets:
        wanted = ", ".join(requested_datasets or ["all"])
        raise ValueError(f"{radar} {date} {pulse} has no {quantity.upper()} sweeps for dataset={wanted}")

    summaries: list[dict[str, Any]] = []
    for target in targets:
        summaries.append(
            process_model_target(
                radar=radar,
                date=date,
                pulse=pulse,
                quantity=quantity,
                target=target,
                train_entries=train_entries,
                validation_entries=validation_entries,
                radar_cache=radar_cache,
                package_dir=package_dir,
                ios_dir=ios_dir,
                report_root=report_root,
                skip_existing=skip_existing,
                compact_output=compact_output,
            )
        )
    return summaries


def process_model_target(
    *,
    radar: str,
    date: str,
    pulse: str,
    quantity: str,
    target: ModelTarget,
    train_entries: list[dict[str, Any]],
    validation_entries: list[dict[str, Any]],
    radar_cache: Path,
    package_dir: Path,
    ios_dir: Path,
    report_root: Path,
    skip_existing: bool,
    compact_output: bool,
) -> dict[str, Any]:
    safe_radar = safe_name(radar)
    dataset = target.dataset
    filename = f"{safe_radar}_{pulse}_{quantity.lower()}_{dataset}_{date}.json"
    model_path = package_dir / filename
    report_dir = report_root / safe_radar / pulse / dataset
    summary_path = report_dir / "summary.json"

    if skip_existing and model_path.exists() and summary_path.exists():
        ios_dir.mkdir(parents=True, exist_ok=True)
        copy_file(model_path, ios_dir / filename)
        return json.loads(summary_path.read_text(encoding="utf-8"))

    scans: list[BackgroundScan] = []
    for entry in train_entries:
        data, metadata, companion_fields = read_entry(
            radar=radar,
            date=date,
            entry=entry,
            dataset=dataset,
            quantity=quantity,
            radar_cache=radar_cache,
        )
        scans.append(BackgroundScan(values=data, metadata=metadata, companion_fields=companion_fields))

    key = {
        "radar": radar,
        "pulse": pulse,
        "quantity": quantity.upper(),
        "dataset": dataset,
        "elevation_deg": rounded_optional(getattr(scans[0].metadata, "elevation_deg")),
        "season_bucket": season_bucket(date),
        "time_of_day_bucket": time_bucket(train_entries),
        "training_date": date,
    }
    build_config = BackgroundModelBuildConfig()
    model = build_background_model(scans, key=key, config=build_config)
    write_inline_model(
        model,
        model_path,
        array_names=RUNTIME_BACKGROUND_ARRAY_NAMES if compact_output else None,
    )
    copy_file(model_path, ios_dir / filename)

    report_dir.mkdir(parents=True, exist_ok=True)
    mask_dir = report_dir / "masks"
    plot_dir = report_dir / "plots"
    mask_dir.mkdir(parents=True, exist_ok=True)
    plot_dir.mkdir(parents=True, exist_ok=True)
    write_model_plots(model, plot_dir)
    summary = validate_model(
        model=model,
        model_path=model_path,
        radar=radar,
        date=date,
        pulse=pulse,
        quantity=quantity,
        target=target,
        train_entries=train_entries,
        validation_entries=validation_entries,
        radar_cache=radar_cache,
        mask_dir=mask_dir,
        plot_dir=plot_dir,
        build_config=build_config,
    )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    write_radar_readme(report_dir, summary)
    return summary


def load_day_catalog(radar: str, date: str, cache_dir: Path) -> dict[str, Any]:
    year, month, day = date[:4], date[4:6], date[6:8]
    path = cache_dir / radar / f"{date}_catalog.json"
    if not path.exists():
        url = f"{PUBLIC_BASE}/ukmo-nimrod/catalog/pvol/{radar}/{year}/{month}/{day}/catalog.json"
        download(url, path)
    return json.loads(path.read_text(encoding="utf-8"))


def select_files(catalog: dict[str, Any], *, pulse: str, start_time: str, total: int) -> list[dict[str, Any]]:
    files = sorted((entry for entry in catalog.get("files", []) if entry.get("pulse") == pulse), key=lambda entry: entry["time"])
    preferred = [entry for entry in files if str(entry.get("time", "")) >= start_time]
    if len(preferred) >= total:
        return preferred[:total]
    if len(files) >= total:
        return files[:total]
    return files


def read_entry(
    *,
    radar: str,
    date: str,
    entry: dict[str, Any],
    dataset: str,
    quantity: str,
    radar_cache: Path,
) -> tuple[Any, Any, dict[str, Any]]:
    return read_polar_field_with_companions(
        radar_cache / entry["filename"],
        radar,
        date,
        FieldSelection(pulse=entry["pulse"], time=entry["time"], quantity=quantity, dataset=dataset),
    )


def discover_model_targets(
    source: Path,
    *,
    quantity: str,
    requested_datasets: list[str] | None,
) -> list[ModelTarget]:
    """Discover all matching quantity sweeps in one representative PVOL file."""

    import h5py

    wanted_quantity = str(quantity or "").strip().upper()
    wanted_datasets = {_normalise_dataset_name(dataset) for dataset in requested_datasets or []}
    targets: dict[str, ModelTarget] = {}

    with h5py.File(source, "r") as h5:
        def visit(name: str, obj: Any) -> None:
            if not isinstance(obj, h5py.Group) or "data" not in obj:
                return
            actual_quantity = _group_quantity(obj)
            if actual_quantity != wanted_quantity:
                return
            dataset_path, dataset_name = _dataset_path_from_group_name(name)
            if not dataset_name:
                return
            normalised_dataset = _normalise_dataset_name(dataset_name)
            if wanted_datasets and normalised_dataset not in wanted_datasets:
                return
            if normalised_dataset in targets:
                return
            elevation = None
            where = h5.get(f"{dataset_path}/where")
            if where is not None and "elangle" in where.attrs:
                elevation = float(where.attrs["elangle"])
            shape = tuple(int(value) for value in obj["data"].shape)
            if len(shape) != 2:
                return
            targets[normalised_dataset] = ModelTarget(
                dataset=normalised_dataset,
                elevation_deg=elevation,
                shape=(shape[0], shape[1]),
            )

        h5.visititems(visit)

    return sorted(targets.values(), key=lambda target: (_dataset_sort_value(target.dataset), target.dataset))


def write_inline_model(model: BackgroundModel, path: Path, *, array_names: tuple[str, ...] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if array_names is None:
        manifest = model.to_manifest(npz_path=None)
    else:
        manifest = compact_quantized_manifest(model, array_names=array_names)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def compact_quantized_manifest(model: BackgroundModel, *, array_names: tuple[str, ...]) -> dict[str, Any]:
    arrays = {name: np.asarray(model.arrays[name], dtype="float32") for name in array_names if name in model.arrays}
    metadata = dict(model.metadata)
    metadata["packaged_array_names"] = sorted(arrays)
    metadata["packaged_encoding"] = "quantized_inline"
    return {
        "schema": "uk_wsr_background_model",
        "schema_version": 1,
        "generated_at": metadata.get("generated_at") or now_utc(),
        "key": dict(model.key),
        "shape": list(model.shape),
        "arrays": {
            name: {
                "dtype": "float32",
                "shape": list(values.shape),
            }
            for name, values in sorted(arrays.items())
        },
        "inline_arrays": {
            name: encode_quantized_background_array(name, values)
            for name, values in sorted(arrays.items())
        },
        "array_hash": hash_arrays(arrays),
        "metadata": metadata,
        "npz_path": None,
    }


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def validate_model(
    *,
    model: BackgroundModel,
    model_path: Path,
    radar: str,
    date: str,
    pulse: str,
    quantity: str,
    target: ModelTarget,
    train_entries: list[dict[str, Any]],
    validation_entries: list[dict[str, Any]],
    radar_cache: Path,
    mask_dir: Path,
    plot_dir: Path,
    build_config: BackgroundModelBuildConfig,
) -> dict[str, Any]:
    dataset = target.dataset
    config = QCConfig(
        mode="signal_preserving",
        operation="mask",
        noise_floor_enabled=False,
        noise_floor_hard_mask=False,
        receiver_noise_enabled=False,
        texture_enabled=False,
        companion_qc_enabled=False,
        static_clutter_enabled=False,
        background_model_enabled=True,
        background_persistent_frequency_min=0.95,
        background_min_samples=40,
        background_static_vrad_frequency_min=0.80,
        background_dbzh_excess_max_db=3.0,
        background_evidence_score_threshold=3,
        background_current_vrad_abs_max_ms=0.50,
        background_learned_low_ci_frequency_min=0.60,
        background_require_current_ci=True,
        background_require_current_vrad=True,
        background_require_training_diversity=True,
        background_min_training_dates=7,
        background_min_training_span_days=14,
    )
    model_qualified, qualification_reason = background_model_qualification(model, config)
    summary: dict[str, Any] = {
        "status": "same_day_diagnostic_quarantined" if not model_qualified else "qualification_pending",
        "qc_version": BACKGROUND_MODEL_QC_VERSION,
        "radar": radar,
        "date": date,
        "pulse": pulse,
        "quantity": quantity.upper(),
        "dataset": dataset,
        "elevation_deg": target.elevation_deg,
        "model_path": str(model_path),
        "model_json_sha256": sha256(model_path.read_bytes()).hexdigest(),
        "model_key": model.key,
        "model_shape": list(model.shape),
        "training_file_count": len(train_entries),
        "validation_file_count": len(validation_entries),
        "validation_design": "same_day_within_sequence",
        "validation_dates": [],
        "validation_date_count": 0,
        "model_qualified": model_qualified,
        "qualification_reason": qualification_reason,
        "training_times": [entry["time"] for entry in train_entries],
        "validation_times": [entry["time"] for entry in validation_entries],
        "config": config.to_dict(),
        "build_config": asdict(build_config),
        "validation": [],
    }
    example_images: list[Path] = []
    example_captions: list[str] = []
    example_indices = {0, max(0, len(validation_entries) // 2), max(0, len(validation_entries) - 1)}

    for index, entry in enumerate(validation_entries):
        data, metadata, companions = read_entry(
            radar=radar,
            date=date,
            entry=entry,
            dataset=dataset,
            quantity=quantity,
            radar_cache=radar_cache,
        )
        data = np.asarray(data, dtype="float32")
        application = apply_background_model(model, data, companions, config)
        mask = np.zeros(data.shape, dtype="uint16")
        mask[~np.isfinite(data)] |= int(QCMaskFlag.NO_DATA)
        mask[application.mask] |= int(QCMaskFlag.BACKGROUND_CLUTTER)
        cleaned = data.copy()
        cleaned[mask != 0] = np.nan
        finite_before = int(np.isfinite(data).sum())
        finite_after = int(np.isfinite(cleaned).sum())
        background_count = int(application.mask.sum())
        sidecar = {
            "schema": "uk_wsr_background_qc_mask",
            "schema_version": 1,
            "radar": radar,
            "date": date,
            "time": entry["time"],
            "pulse": entry["pulse"],
            "quantity": quantity.upper(),
            "dataset": dataset,
            "shape": list(data.shape),
            "finite_before": finite_before,
            "finite_after": finite_after,
            "background_masked_count": background_count,
            "background_masked_fraction_finite": (background_count / finite_before) if finite_before else 0.0,
            "retained_fraction_finite": (finite_after / finite_before) if finite_before else 0.0,
            "dbzh_p50_before": finite_percentile(data, 50),
            "dbzh_p90_before": finite_percentile(data, 90),
            "dbzh_p50_after": finite_percentile(cleaned, 50),
            "dbzh_p90_after": finite_percentile(cleaned, 90),
            "companion_quantities": sorted(companions),
            "background_model": application.model,
            "evidence_counts": dict(application.evidence_counts),
            "config": config.to_dict(),
            "source_object": entry.get("object_key"),
            "source_url": entry.get("object_url"),
        }
        stem = f"{safe_name(radar)}_{date}_{entry['pulse']}_{dataset}_{entry['time']}_{quantity.upper()}_background_qc"
        npz_path = mask_dir / f"{stem}.npz"
        np.savez_compressed(npz_path, mask=mask, cleaned=cleaned.astype("float32"), raw=data.astype("float32"))
        json_path = npz_path.with_suffix(".npz.json")
        json_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True), encoding="utf-8")
        summary["validation"].append(sidecar | {"mask_path": str(npz_path), "sidecar_path": str(json_path)})
        if index in example_indices:
            raw_png = plot_dir / f"{entry['time']}_raw_dbzh.png"
            mask_png = plot_dir / f"{entry['time']}_background_mask.png"
            cleaned_png = plot_dir / f"{entry['time']}_cleaned_dbzh.png"
            png_heatmap(data, raw_png, f"{radar} {entry['time']} raw DBZH", vmin=-20, vmax=40)
            png_heatmap(application.mask.astype("float32"), mask_png, f"{radar} {entry['time']} background mask", vmin=0, vmax=1, palette="mask")
            png_heatmap(cleaned, cleaned_png, f"{radar} {entry['time']} cleaned DBZH", vmin=-20, vmax=40)
            example_images.extend([raw_png, mask_png, cleaned_png])
            example_captions.extend([f"{entry['time']} raw", f"{entry['time']} learned mask", f"{entry['time']} cleaned"])

    aggregate = aggregate_validation(summary["validation"])
    summary["aggregate"] = aggregate
    write_masked_percent_plot(summary["validation"], plot_dir / "validation_masked_percent_by_scan.png")
    if example_images:
        montage(example_images, plot_dir / "validation_holdout_examples.png", f"{radar} held-out examples", example_captions)
    return summary


def aggregate_validation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fractions = [row["background_masked_fraction_finite"] for row in rows]
    return {
        "finite_before_total": int(sum(row["finite_before"] for row in rows)),
        "finite_after_total": int(sum(row["finite_after"] for row in rows)),
        "background_masked_total": int(sum(row["background_masked_count"] for row in rows)),
        "background_masked_fraction_mean": float(np.mean(fractions)),
        "background_masked_fraction_min": float(np.min(fractions)),
        "background_masked_fraction_max": float(np.max(fractions)),
        "retained_fraction_mean": float(np.mean([row["retained_fraction_finite"] for row in rows])),
    }


def write_model_plots(model: BackgroundModel, plot_dir: Path) -> None:
    specs = [
        ("model_persistent_echo_frequency.png", "persistent_echo_frequency", 0.0, 1.0, "Persistent echo frequency"),
        ("model_near_zero_vrad_frequency.png", "near_zero_vrad_frequency", 0.0, 1.0, "Near-zero VRAD frequency"),
        ("model_low_sqi_frequency.png", "low_sqi_frequency", 0.0, 1.0, "Low SQI frequency"),
        ("model_dbzh_p90.png", "dbzh_p90", -20.0, 40.0, "Learned DBZH p90"),
    ]
    for filename, array_name, vmin, vmax, title in specs:
        png_heatmap(model.arrays[array_name], plot_dir / filename, title, vmin=vmin, vmax=vmax)


def write_radar_readme(report_dir: Path, summary: dict[str, Any]) -> None:
    aggregate = summary["aggregate"]
    text = f"""# Learned Background Validation: {summary['radar']} {summary['date']} {summary['pulse']} {summary['quantity']} {summary['dataset']}

Status: **same-day diagnostic only; not qualified for automatic use.**

- Training: {summary['training_file_count']} real public PVOL/HDF5 scans ({summary['training_times'][0]} to {summary['training_times'][-1]})
- Same-day diagnostic hold-out: {summary['validation_file_count']} scans ({summary['validation_times'][0]} to {summary['validation_times'][-1]})
- Registry qualification: `{summary.get('qualification_reason') or 'pending independent date-held-out validation'}`
- Model: `{summary['model_path']}`
- Shape: {summary['model_shape'][0]} azimuth rays x {summary['model_shape'][1]} range bins
- Mean held-out background-clutter mask share: {aggregate['background_masked_fraction_mean'] * 100:.2f}%
- Range across hold-out scans: {aggregate['background_masked_fraction_min'] * 100:.2f}% to {aggregate['background_masked_fraction_max'] * 100:.2f}%

## Plots

![Persistent echo frequency](plots/model_persistent_echo_frequency.png)

![Near-zero VRAD frequency](plots/model_near_zero_vrad_frequency.png)

![Low SQI frequency](plots/model_low_sqi_frequency.png)

![Learned DBZH p90](plots/model_dbzh_p90.png)

![Same-day diagnostic examples](plots/validation_holdout_examples.png)

![Masked share by scan](plots/validation_masked_percent_by_scan.png)

## Artifacts

- Summary: `summary.json`
- Per-scan persisted masks: `masks/*.npz` plus `masks/*.npz.json`
- Each mask `.npz` contains `raw`, `cleaned`, and `mask`; `BACKGROUND_CLUTTER` is bit 1024.
"""
    (report_dir / "README.md").write_text(text, encoding="utf-8")


def write_model_manifest(package_dir: Path, summaries: list[dict[str, Any]]) -> None:
    models = []
    for summary in sorted(
        summaries,
        key=lambda row: (
            row["radar"],
            row["pulse"],
            _dataset_sort_value(row["dataset"]),
            row["dataset"],
        ),
    ):
        path = Path(summary["model_path"])
        key = dict(summary["model_key"])
        model_manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        model_metadata = model_manifest.get("metadata") if isinstance(model_manifest.get("metadata"), dict) else {}
        models.append(
            {
                "filename": path.name,
                "radar": summary["radar"],
                "pulse": summary["pulse"],
                "quantity": summary["quantity"],
                "dataset": summary["dataset"],
                "elevation_deg": key.get("elevation_deg"),
                "shape": model_manifest.get("shape") or summary.get("model_shape"),
                "array_hash": model_manifest.get("array_hash"),
                "packaged_encoding": model_metadata.get("packaged_encoding"),
                "training_date": key.get("training_date"),
                "qc_version": summary.get("qc_version", BACKGROUND_MODEL_QC_VERSION),
                "source_date_count": model_metadata.get("source_date_count"),
                "source_start_date": model_metadata.get("source_start_date"),
                "source_end_date": model_metadata.get("source_end_date"),
                "training_span_days": model_metadata.get("training_span_days"),
                "season_bucket": key.get("season_bucket"),
                "time_of_day_bucket": key.get("time_of_day_bucket"),
                "source_count": summary["training_file_count"],
                "validation_file_count": summary["validation_file_count"],
                "validation_design": summary.get("validation_design"),
                "validation_dates": summary.get("validation_dates", []),
                "validation_date_count": summary.get("validation_date_count", 0),
                "mean_masked_fraction": summary["aggregate"]["background_masked_fraction_mean"],
                "json_sha256": summary["model_json_sha256"],
            }
        )
    raw_payload = {
        "schema": "uk_wsr_background_model_manifest",
        "schema_version": 2,
        "generated_at": now_utc(),
        "models": models,
    }
    manifest_path = package_dir / "manifest.json"
    manifest_path.write_text(json.dumps(raw_payload, indent=2, sort_keys=True), encoding="utf-8")
    payload = audit_background_model_registry(package_dir, manifest_path=manifest_path)
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_all_radar_report(report_root: Path, summaries: list[dict[str, Any]], errors: list[dict[str, str]]) -> None:
    payload = {
        "schema": "uk_wsr_background_all_sweep_validation",
        "schema_version": 1,
        "generated_at": now_utc(),
        "radar_count": len({summary["radar"] for summary in summaries}),
        "model_target_count": len(summaries),
        "errors": errors,
        "summaries": summaries,
    }
    (report_root / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    write_all_radar_bar(summaries, report_root / "masked_percent_by_target.png")
    rows = "\n".join(
        "| {radar} | {pulse} | {dataset} | {elevation} | {date} | {train} | {valid} | {mean:.2f}% | {lo:.2f}-{hi:.2f}% |".format(
            radar=summary["radar"],
            pulse=summary["pulse"],
            dataset=summary["dataset"],
            elevation=summary.get("elevation_deg"),
            date=summary["date"],
            train=summary["training_file_count"],
            valid=summary["validation_file_count"],
            mean=summary["aggregate"]["background_masked_fraction_mean"] * 100,
            lo=summary["aggregate"]["background_masked_fraction_min"] * 100,
            hi=summary["aggregate"]["background_masked_fraction_max"] * 100,
        )
        for summary in sorted(
            summaries,
            key=lambda row: (
                row["radar"],
                row["pulse"],
                _dataset_sort_value(row["dataset"]),
                row["dataset"],
            ),
        )
    )
    error_text = "\n".join(
        f"- `{error['radar']}` `{error.get('pulse', '')}`: {error['error']}" for error in errors
    ) or "None."
    readme = f"""# Learned Background Validation: All Radars, Pulses, and Elevations

Status: {len({summary['radar'] for summary in summaries})} radars and {len(summaries)} radar/pulse/elevation targets completed as same-day diagnostics; {len(errors)} failed. These models are not qualified for automatic use.

![Mean held-out masked share by target](masked_percent_by_target.png)

| Radar | Pulse | Dataset | Elevation deg | Date | Train scans | Hold-out scans | Mean masked | Hold-out range |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | --- |
{rows}

## Errors

{error_text}
"""
    (report_root / "README.md").write_text(readme, encoding="utf-8")


def write_all_radar_bar(summaries: list[dict[str, Any]], path: Path) -> None:
    ordered = sorted(
        summaries,
        key=lambda row: (
            row["radar"],
            row["pulse"],
            _dataset_sort_value(row["dataset"]),
            row["dataset"],
        ),
    )
    values = [summary["aggregate"]["background_masked_fraction_mean"] * 100 for summary in ordered]
    width = max(1100, len(ordered) * 78)
    height = 620
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((30, 20), "Mean held-out learned-background mask share by radar/pulse/elevation", fill=(25, 28, 34))
    left, top, bar_h = 80, 80, 400
    plot_w = width - left - 40
    max_y = max(1.0, math.ceil(max(values or [1]) / 5) * 5)
    for tick in range(0, int(max_y) + 1, max(1, int(max_y // 5) or 1)):
        y = top + bar_h - int((tick / max_y) * bar_h)
        draw.line((left, y, left + plot_w, y), fill=(230, 232, 235))
        draw.text((25, y - 8), f"{tick}%", fill=(95, 100, 108))
    slot = plot_w / max(1, len(values))
    for index, value in enumerate(values):
        x0 = left + index * slot + 6
        x1 = left + (index + 1) * slot - 6
        y0 = top + bar_h - int((value / max_y) * bar_h)
        draw.rectangle((x0, y0, x1, top + bar_h), fill=(54, 125, 160))
        label = f"{ordered[index]['radar']}\n{ordered[index]['pulse']} {ordered[index]['dataset']}".replace("-", "\n")
        draw.multiline_text((x0, top + bar_h + 12), label, fill=(80, 85, 92), spacing=2)
    canvas.save(path)


def write_masked_percent_plot(rows: list[dict[str, Any]], path: Path) -> None:
    fractions = [row["background_masked_fraction_finite"] * 100 for row in rows]
    canvas = Image.new("RGB", (1000, 540), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((30, 20), "Held-out background masked share by scan", fill=(25, 28, 34))
    left, top, bar_w, bar_h = 70, 80, 900, 420
    max_y = max(1.0, math.ceil(max(fractions or [1]) / 5) * 5)
    for tick in range(0, int(max_y) + 1, max(1, int(max_y // 5) or 1)):
        y = top + bar_h - int((tick / max_y) * bar_h)
        draw.line((left, y, left + bar_w, y), fill=(230, 232, 235))
        draw.text((20, y - 8), f"{tick}%", fill=(95, 100, 108))
    slot = bar_w / max(1, len(fractions))
    for index, value in enumerate(fractions):
        x0 = left + index * slot + 4
        x1 = left + (index + 1) * slot - 4
        y0 = top + bar_h - int((value / max_y) * bar_h)
        draw.rectangle((x0, y0, x1, top + bar_h), fill=(54, 125, 160))
        if index % 2 == 0:
            draw.text((x0, top + bar_h + 8), rows[index]["time"], fill=(80, 85, 92))
    canvas.save(path)


def png_heatmap(values: Any, path: Path, title: str, vmin: float | None = None, vmax: float | None = None, palette: str = "field") -> None:
    arr = np.asarray(values, dtype="float32")
    finite = np.isfinite(arr)
    if vmin is None:
        vmin = float(np.nanpercentile(arr, 2)) if finite.any() else 0.0
    if vmax is None:
        vmax = float(np.nanpercentile(arr, 98)) if finite.any() else 1.0
    if not math.isfinite(vmin):
        vmin = 0.0
    if not math.isfinite(vmax) or vmax <= vmin:
        vmax = vmin + 1.0
    scaled = np.clip((arr - vmin) / (vmax - vmin), 0, 1)
    scaled[~finite] = 0
    if palette == "mask":
        rgb = np.zeros((*arr.shape, 3), dtype=np.uint8)
        rgb[..., :] = 245
        rgb[(arr > 0) & finite] = (214, 67, 54)
        rgb[(arr == 0) & finite] = (44, 160, 90)
    else:
        stops = np.array(
            [[31, 40, 91], [20, 120, 145], [132, 190, 91], [244, 211, 94], [217, 75, 60]],
            dtype=np.float32,
        )
        x = scaled * (len(stops) - 1)
        lo = np.floor(x).astype(int)
        hi = np.clip(lo + 1, 0, len(stops) - 1)
        frac = (x - lo)[..., None]
        rgb = (stops[lo] * (1 - frac) + stops[hi] * frac).astype(np.uint8)
        rgb[~finite] = (248, 248, 248)
    img = Image.fromarray(rgb, "RGB").resize((850, 720), Image.Resampling.NEAREST)
    canvas = Image.new("RGB", (980, 820), "white")
    canvas.paste(img, (90, 70))
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 20), title, fill=(25, 28, 34))
    draw.text((90, 795), f"min {vmin:.2f}   max {vmax:.2f}", fill=(80, 85, 92))
    canvas.save(path)


def montage(images: list[Path], path: Path, title: str, captions: list[str]) -> None:
    thumb_w, thumb_h = 430, 330
    cols = 3
    rows = math.ceil(len(images) / cols)
    canvas = Image.new("RGB", (cols * thumb_w + 70, rows * (thumb_h + 48) + 90), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((25, 20), title, fill=(25, 28, 34))
    for index, image_path in enumerate(images):
        img = Image.open(image_path).convert("RGB").resize((thumb_w, thumb_h), Image.Resampling.BILINEAR)
        x = 25 + (index % cols) * thumb_w
        y = 65 + (index // cols) * (thumb_h + 48)
        canvas.paste(img, (x, y))
        draw.text((x, y + thumb_h + 8), captions[index], fill=(65, 70, 78))
    canvas.save(path)


def download(url: str, path: Path, *, expected_size: int | None = None) -> None:
    if path.exists() and (expected_size is None or path.stat().st_size == int(expected_size)):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, tmp.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    tmp.replace(path)


def finite_percentile(values: Any, percentile: float) -> float | None:
    finite = np.asarray(values)[np.isfinite(values)]
    if finite.size == 0:
        return None
    return float(np.percentile(finite, percentile))


def rounded_optional(value: Any, *, digits: int = 3) -> float | None:
    if value in ("", None):
        return None
    return round(float(value), digits)


def safe_name(value: str) -> str:
    return value.strip().lower().replace("/", "-").replace(" ", "-")


def _group_quantity(group: Any) -> str:
    what = group.get("what")
    if what is None or "quantity" not in what.attrs:
        return ""
    value = what.attrs["quantity"]
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value or "").strip().upper()


def _dataset_path_from_group_name(name: str) -> tuple[str, str]:
    parts = name.split("/")
    for index, part in enumerate(parts):
        if part.startswith("dataset"):
            return "/".join(parts[: index + 1]), _normalise_dataset_name(part)
    return "", ""


def _normalise_dataset_name(dataset: str) -> str:
    text = str(dataset or "").strip().lower()
    if text.startswith("dataset"):
        return text
    if text.isdigit():
        return f"dataset{text}"
    return text


def _dataset_sort_value(dataset: str) -> int:
    text = _normalise_dataset_name(dataset)
    suffix = text.removeprefix("dataset")
    return int(suffix) if suffix.isdigit() else 10_000


def season_bucket(date: str) -> str:
    month = int(date[4:6])
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def time_bucket(entries: list[dict[str, Any]]) -> str:
    hours = [int(str(entry["time"])[:2]) for entry in entries if str(entry.get("time", ""))[:2].isdigit()]
    if not hours:
        return "all"
    if all(6 <= hour < 18 for hour in hours):
        return "daytime"
    if all(hour >= 18 or hour < 6 for hour in hours):
        return "nighttime"
    return "mixed"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
