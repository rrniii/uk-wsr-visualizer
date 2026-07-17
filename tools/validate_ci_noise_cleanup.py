#!/usr/bin/env python3
"""Validate conservative CI-aware cleanup across all DBZH sweeps in PVOL files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uk_wsr_visualizer.export_types import FieldSelection
from uk_wsr_visualizer.geospatial import apply_polar_filters, read_polar_field_with_companions
from uk_wsr_visualizer.preview import apply_palette
from uk_wsr_visualizer.qc import QCMaskFlag


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radar", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--time", required=True)
    parser.add_argument("--lp", type=Path)
    parser.add_argument("--sp", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def require_numpy():
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("numpy is required") from exc
    return np


def require_h5py():
    try:
        import h5py
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("h5py is required") from exc
    return h5py


def require_plotting():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("Pillow is required") from exc
    return Image, ImageDraw, ImageFont


def dbzh_datasets(path: Path) -> list[str]:
    h5py = require_h5py()
    datasets: list[str] = []
    with h5py.File(path, "r") as h5:
        for name in sorted((key for key in h5 if key.startswith("dataset")), key=dataset_number):
            group = h5[name]
            for child_name in group:
                child = group[child_name]
                if not child_name.startswith("data") or "what" not in child:
                    continue
                quantity = child["what"].attrs.get("quantity", "")
                if isinstance(quantity, bytes):
                    quantity = quantity.decode("utf-8", errors="replace")
                if str(quantity).upper() == "DBZH":
                    datasets.append(name)
                    break
    return datasets


def dataset_number(name: str) -> int:
    suffix = "".join(character for character in name if character.isdigit())
    return int(suffix or 0)


def finite_stat(values: Any, operation: str, percentile: float | None = None) -> float | None:
    np = require_numpy()
    finite = np.asarray(values, dtype="float64")
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        return None
    if operation == "min":
        return float(finite.min())
    if operation == "max":
        return float(finite.max())
    if operation == "median":
        return float(np.median(finite))
    if operation == "percentile" and percentile is not None:
        return float(np.percentile(finite, percentile))
    raise ValueError(operation)


def field_summary(values: Any) -> dict[str, float | int | None]:
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    finite = np.isfinite(array)
    return {
        "finite_count": int(finite.sum()),
        "min": finite_stat(array, "min"),
        "p10": finite_stat(array, "percentile", 10),
        "median": finite_stat(array, "median"),
        "p90": finite_stat(array, "percentile", 90),
        "max": finite_stat(array, "max"),
    }


def validate_sweep(
    *,
    source: Path,
    radar: str,
    date: str,
    time: str,
    pulse: str,
    dataset: str,
    output_dir: Path,
) -> dict[str, Any]:
    np = require_numpy()
    raw, metadata, companions = read_polar_field_with_companions(
        source,
        radar,
        date,
        FieldSelection(pulse=pulse, time=time, quantity="DBZH", dataset=str(dataset_number(dataset))),
    )
    result = apply_polar_filters(
        raw,
        metadata,
        {"qc_mode": "signal_preserving"},
        return_metadata=True,
        companion_fields=companions,
    )
    if result.qc is None:
        raise RuntimeError(f"QC result missing for {pulse} {dataset}")

    cleaned = np.asarray(result.values, dtype="float32")
    raw = np.asarray(raw, dtype="float32")
    mask = np.asarray(result.qc.mask, dtype="uint16")
    finite_raw = np.isfinite(raw)
    removed = finite_raw & ~np.isfinite(cleaned)
    finite_count = int(finite_raw.sum())
    removed_count = int(removed.sum())
    retained_count = int((finite_raw & np.isfinite(cleaned)).sum())
    receiver_noise = (mask & int(QCMaskFlag.RECEIVER_NOISE)) != 0
    background_clutter = (mask & int(QCMaskFlag.BACKGROUND_CLUTTER)) != 0

    threshold_retention: dict[str, dict[str, float | int | None]] = {}
    for threshold in (0.0, 10.0, 20.0):
        candidates = finite_raw & (raw >= threshold)
        candidate_count = int(candidates.sum())
        removed_at_threshold = int((candidates & removed).sum())
        threshold_retention[f"ge_{int(threshold)}_dbz"] = {
            "input": candidate_count,
            "removed": removed_at_threshold,
            "retained": candidate_count - removed_at_threshold,
            "retained_percent": (
                100.0 * (candidate_count - removed_at_threshold) / candidate_count if candidate_count else None
            ),
        }

    companion_stats = {
        quantity: field_summary(values)
        for quantity, values in companions.items()
        if quantity
        in {
            "CI",
            "SQIH",
            "RHOHV",
            "PHIDP",
            "VRADH",
            "ZDR",
            "LONG_RANGE_NOISE_DBC_H",
            "LONG_RANGE_NOISE_DBC_V",
        }
    }
    key = f"{pulse}_{dataset}"
    artifact_path = output_dir / f"{key}_qc_v2_mask.npz"
    np.savez_compressed(
        artifact_path,
        original=raw,
        cleaned=cleaned,
        mask=mask,
        floor_profile=np.asarray(
            [np.nan if value is None else value for value in result.qc.floor_profile], dtype="float32"
        ),
    )

    metrics: dict[str, Any] = {
        "key": key,
        "source": str(source),
        "pulse": pulse,
        "dataset": metadata.dataset,
        "elevation_deg": metadata.elevation_deg,
        "shape": [int(raw.shape[0]), int(raw.shape[1])],
        "range_gate_m": metadata.rscale_m,
        "max_range_km": metadata.max_range_m / 1000.0,
        "finite_input": finite_count,
        "retained": retained_count,
        "removed": removed_count,
        "removed_percent": 100.0 * removed_count / finite_count if finite_count else 0.0,
        "receiver_noise_removed": int(receiver_noise.sum()),
        "background_clutter_removed": int(background_clutter.sum()),
        "max_removed_dbzh": finite_stat(raw[removed], "max"),
        "p95_removed_dbzh": finite_stat(raw[removed], "percentile", 95),
        "threshold_retention": threshold_retention,
        "flag_counts": result.qc.flag_counts,
        "evidence_counts": result.qc.evidence_counts,
        "noise_metadata": result.qc.noise_metadata,
        "background_model": result.qc.background_model,
        "companion_quantities": result.qc.companion_quantities,
        "companion_stats": companion_stats,
        "mask_artifact": artifact_path.name,
    }
    sidecar_path = artifact_path.with_suffix(".json")
    sidecar_path.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    metrics["mask_sidecar"] = sidecar_path.name
    metrics["_raw"] = raw
    metrics["_cleaned"] = cleaned
    metrics["_removed"] = removed
    metrics["_companions"] = companions
    metrics["_metadata"] = metadata
    return metrics


def report_font(size: int, *, bold: bool = False):
    _, _, ImageFont = require_plotting()
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def polar_image(
    values: Any,
    *,
    size: int = 340,
    vmin: float,
    vmax: float,
    palette: str,
    palette_stops: str | None = None,
):
    np = require_numpy()
    Image, ImageDraw, _ = require_plotting()
    array = np.asarray(values, dtype="float32")
    rows, columns = array.shape
    coordinate = np.arange(size, dtype="float32")
    x, y = np.meshgrid(coordinate, coordinate)
    centre = (size - 1) / 2.0
    dx = x - centre
    dy = y - centre
    radial = np.sqrt(dx * dx + dy * dy)
    inside = radial <= centre
    bin_index = np.minimum((radial / max(centre, 1.0) * columns).astype("int32"), columns - 1)
    azimuth = np.mod(np.arctan2(dx, -dy), 2.0 * np.pi)
    ray_index = np.minimum((azimuth / (2.0 * np.pi) * rows).astype("int32"), rows - 1)
    sampled = array[ray_index, bin_index]
    valid = inside & np.isfinite(sampled)
    scaled = np.clip((sampled - vmin) / max(vmax - vmin, 1.0e-6), 0.0, 1.0)
    rgb = apply_palette((np.nan_to_num(scaled) * 255.0).astype("uint8"), palette, palette_stops)
    rgba = np.full((size, size, 4), 255, dtype="uint8")
    rgba[valid, :3] = rgb[valid]
    rgba[~inside, 3] = 0
    image = Image.fromarray(rgba, mode="RGBA")
    draw = ImageDraw.Draw(image, mode="RGBA")
    for fraction in (0.25, 0.50, 0.75, 1.0):
        radius = centre * fraction
        draw.ellipse(
            (centre - radius, centre - radius, centre + radius, centre + radius),
            outline=(40, 50, 60, 70),
            width=1,
        )
    draw.line((centre, 0, centre, size), fill=(40, 50, 60, 55), width=1)
    draw.line((0, centre, size, centre), fill=(40, 50, 60, 55), width=1)
    return image


def titled_panel(image: Any, title: str, *, width: int = 370, height: int = 390):
    Image, ImageDraw, _ = require_plotting()
    panel = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(panel)
    font = report_font(16, bold=True)
    box = draw.textbbox((0, 0), title, font=font)
    draw.text(((width - (box[2] - box[0])) / 2, 8), title, fill="#17212b", font=font)
    radar = image.resize((340, 340))
    panel.paste(radar, ((width - 340) // 2, 42), radar)
    return panel


def draw_scale(canvas: Any, *, x: int, y: int, width: int, label: str, vmin: float, vmax: float) -> None:
    np = require_numpy()
    Image, ImageDraw, _ = require_plotting()
    gradient = np.tile(np.arange(256, dtype="uint8"), (18, 1))
    image = Image.fromarray(apply_palette(gradient, "homeyer"), mode="RGB").resize((width, 18))
    canvas.paste(image, (x, y))
    draw = ImageDraw.Draw(canvas)
    font = report_font(14)
    draw.text((x, y + 22), f"{vmin:g}", fill="#25313d", font=font)
    maximum = f"{vmax:g} {label}"
    box = draw.textbbox((0, 0), maximum, font=font)
    draw.text((x + width - (box[2] - box[0]), y + 22), maximum, fill="#25313d", font=font)


def plot_pulse_overview(records: list[dict[str, Any]], output_dir: Path, pulse: str) -> None:
    np = require_numpy()
    Image, ImageDraw, _ = require_plotting()
    selected = [record for record in records if record["pulse"] == pulse]
    if not selected:
        return
    panel_width = 370
    panel_height = 390
    margin = 18
    header = 92
    footer = 65
    canvas = Image.new(
        "RGB",
        (margin * 4 + panel_width * 3, header + panel_height * len(selected) + footer),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    title = f"High Moorsley {pulse.upper()} all DBZH sweeps: raw, removed mask, cleaned"
    draw.text((margin, 18), title, fill="#111820", font=report_font(25, bold=True))
    for row, record in enumerate(selected):
        elevation = record["elevation_deg"]
        label = f"{record['dataset']} {elevation:.2f} deg"
        outcome = np.where(record["_removed"], 1.0, 0.0)
        outcome[~np.isfinite(record["_raw"])] = np.nan
        panels = [
            titled_panel(
                polar_image(record["_raw"], vmin=-30, vmax=60, palette="homeyer"),
                f"{label} | raw DBZH",
            ),
            titled_panel(
                polar_image(
                    outcome,
                    vmin=0,
                    vmax=1,
                    palette="custom",
                    palette_stops="0:#dce3e8,0.49:#dce3e8,0.5:#c62828,1:#c62828",
                ),
                f"removed {record['removed_percent']:.1f}% (red)",
            ),
            titled_panel(
                polar_image(record["_cleaned"], vmin=-30, vmax=60, palette="homeyer"),
                "qc-v2 cleaned DBZH",
            ),
        ]
        top = header + row * panel_height
        for column, panel in enumerate(panels):
            canvas.paste(panel, (margin + column * (panel_width + margin), top))
    draw_scale(
        canvas,
        x=margin,
        y=header + panel_height * len(selected) + 8,
        width=panel_width * 2,
        label="dBZ",
        vmin=-30,
        vmax=60,
    )
    canvas.save(output_dir / f"high_moorsley_{pulse}_all_sweeps_qc_v2.png", optimize=True)


def histogram_panel(retained: Any, removed: Any, *, width: int = 370, height: int = 390):
    np = require_numpy()
    Image, ImageDraw, _ = require_plotting()
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((18, 8), "DBZH distribution: retained vs removed", fill="#17212b", font=report_font(16, bold=True))
    bins = np.linspace(-30, 60, 61)
    retained_counts, _ = np.histogram(np.asarray(retained), bins=bins)
    removed_counts, _ = np.histogram(np.asarray(removed), bins=bins)
    maximum = max(float(np.log1p(retained_counts).max()), float(np.log1p(removed_counts).max()), 1.0)
    left, top, right, bottom = 42, 55, width - 18, height - 48
    draw.line((left, bottom, right, bottom), fill="#45515d", width=1)
    draw.line((left, top, left, bottom), fill="#45515d", width=1)
    bar_width = (right - left) / len(retained_counts)
    for index, (retained_count, removed_count) in enumerate(zip(retained_counts, removed_counts)):
        x0 = left + index * bar_width
        x1 = left + (index + 1) * bar_width
        retained_height = np.log1p(retained_count) / maximum * (bottom - top)
        removed_height = np.log1p(removed_count) / maximum * (bottom - top)
        draw.rectangle((x0, bottom - retained_height, x1, bottom), fill="#7fa9cb")
        draw.rectangle((x0, bottom - removed_height, x1, bottom), fill="#c62828")
    font = report_font(13)
    draw.text((left, bottom + 8), "-30", fill="#25313d", font=font)
    draw.text((right - 42, bottom + 8), "60 dBZ", fill="#25313d", font=font)
    draw.rectangle((left, top + 5, left + 13, top + 18), fill="#7fa9cb")
    draw.text((left + 18, top + 3), "retained", fill="#25313d", font=font)
    draw.rectangle((left + 105, top + 5, left + 118, top + 18), fill="#c62828")
    draw.text((left + 123, top + 3), "removed", fill="#25313d", font=font)
    draw.text((8, top), "log count", fill="#25313d", font=font)
    return image


def plot_evidence(record: dict[str, Any], output_dir: Path) -> None:
    np = require_numpy()
    Image, ImageDraw, _ = require_plotting()
    companions = record["_companions"]
    outcome = np.where(record["_removed"], 1.0, 0.0)
    outcome[~np.isfinite(record["_raw"])] = np.nan
    panels = [
        titled_panel(polar_image(record["_raw"], vmin=-30, vmax=60, palette="homeyer"), "Raw DBZH"),
        titled_panel(
            polar_image(
                companions.get("CI", np.full_like(record["_raw"], np.nan)),
                vmin=0,
                vmax=8,
                palette="custom",
                palette_stops="0:#440154,0.33:#31688e,0.66:#35b779,1:#fde725",
            ),
            "CI: >=6 incoherent/noise evidence",
        ),
        titled_panel(
            polar_image(
                companions.get("SQIH", np.full_like(record["_raw"], np.nan)),
                vmin=0,
                vmax=1,
                palette="custom",
                palette_stops="0:#000004,0.5:#b5367a,1:#fcfdbf",
            ),
            "SQIH: <=0.05 required",
        ),
        titled_panel(
            polar_image(
                outcome,
                vmin=0,
                vmax=1,
                palette="custom",
                palette_stops="0:#dce3e8,0.49:#dce3e8,0.5:#c62828,1:#c62828",
            ),
            f"Receiver-noise mask: {record['removed_percent']:.1f}%",
        ),
        titled_panel(polar_image(record["_cleaned"], vmin=-30, vmax=60, palette="homeyer"), "Cleaned DBZH"),
        histogram_panel(
            record["_raw"][np.isfinite(record["_cleaned"])],
            record["_raw"][record["_removed"]],
        ),
    ]
    margin = 18
    panel_width = 370
    panel_height = 390
    header = 72
    canvas = Image.new("RGB", (margin * 4 + panel_width * 3, header + panel_height * 2 + margin), "white")
    draw = ImageDraw.Draw(canvas)
    title = (
        f"High Moorsley {record['pulse'].upper()} {record['dataset']} "
        f"({record['elevation_deg']:.2f} deg): qc-v2 evidence"
    )
    draw.text((margin, 18), title, fill="#111820", font=report_font(25, bold=True))
    for index, panel in enumerate(panels):
        row, column = divmod(index, 3)
        canvas.paste(panel, (margin + column * (panel_width + margin), header + row * panel_height))
    canvas.save(output_dir / "high_moorsley_qc_v2_evidence_detail.png", optimize=True)


def plot_summary(records: list[dict[str, Any]], output_dir: Path) -> None:
    Image, ImageDraw, _ = require_plotting()
    width, height = 1200, 650
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((55, 25), "qc-v2 real-data removal by pulse and elevation", fill="#111820", font=report_font(28, bold=True))
    left, top, right, bottom = 85, 100, width - 35, height - 115
    maximum = max([record["removed_percent"] for record in records] + [1.0]) * 1.2
    for fraction in (0.0, 0.25, 0.50, 0.75, 1.0):
        y = bottom - fraction * (bottom - top)
        draw.line((left, y, right, y), fill="#d8dee4", width=1)
        draw.text((15, y - 9), f"{maximum * fraction:.0f}%", fill="#45515d", font=report_font(14))
    slot = (right - left) / max(len(records), 1)
    for index, record in enumerate(records):
        value = record["removed_percent"]
        bar_width = slot * 0.62
        x0 = left + index * slot + (slot - bar_width) / 2
        x1 = x0 + bar_width
        y0 = bottom - value / maximum * (bottom - top)
        color = "#4c78a8" if record["pulse"] == "lp" else "#f58518"
        draw.rectangle((x0, y0, x1, bottom), fill=color)
        value_text = f"{value:.1f}%"
        value_box = draw.textbbox((0, 0), value_text, font=report_font(13, bold=True))
        draw.text(((x0 + x1 - (value_box[2] - value_box[0])) / 2, y0 - 22), value_text, fill="#25313d", font=report_font(13, bold=True))
        label = f"{record['pulse'].upper()}\n{record['elevation_deg']:.2f} deg"
        label_box = draw.multiline_textbbox((0, 0), label, font=report_font(13), align="center")
        draw.multiline_text(
            ((x0 + x1 - (label_box[2] - label_box[0])) / 2, bottom + 10),
            label,
            fill="#25313d",
            font=report_font(13),
            align="center",
        )
    draw.text((left, height - 35), "Blue = LP; orange = SP. Percentage denominator is finite DBZH input gates.", fill="#45515d", font=report_font(14))
    canvas.save(output_dir / "high_moorsley_qc_v2_removal_by_sweep.png", optimize=True)


def serializable_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def main() -> int:
    args = parse_args()
    sources = {pulse: path for pulse, path in (("lp", args.lp), ("sp", args.sp)) if path is not None}
    if not sources:
        raise SystemExit("at least one of --lp or --sp is required")
    for path in sources.values():
        if not path.is_file():
            raise SystemExit(f"PVOL source not found: {path}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for pulse, source in sources.items():
        for dataset in dbzh_datasets(source):
            records.append(
                validate_sweep(
                    source=source,
                    radar=args.radar,
                    date=args.date,
                    time=args.time,
                    pulse=pulse,
                    dataset=dataset,
                    output_dir=args.output_dir,
                )
            )

    records.sort(key=lambda record: (record["pulse"], dataset_number(record["dataset"])))
    plot_summary(records, args.output_dir)
    for pulse in sources:
        plot_pulse_overview(records, args.output_dir, pulse)
    evidence_record = max(records, key=lambda record: record["removed_percent"])
    plot_evidence(evidence_record, args.output_dir)

    total_input = sum(record["finite_input"] for record in records)
    total_removed = sum(record["removed"] for record in records)
    report = {
        "schema": "uk_wsr_qc_validation",
        "schema_version": 2,
        "qc_version": "qc-v2",
        "radar": args.radar,
        "date": args.date,
        "time": args.time,
        "sweep_count": len(records),
        "finite_input": total_input,
        "removed": total_removed,
        "removed_percent": 100.0 * total_removed / total_input if total_input else 0.0,
        "high_signal_removed_ge_20_dbz": sum(
            int(record["threshold_retention"]["ge_20_dbz"]["removed"]) for record in records
        ),
        "records": [serializable_record(record) for record in records],
    }
    (args.output_dir / "metrics.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
